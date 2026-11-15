"""Offline Khmer speech synthesis and timed voice-dub track assembly.

Audio is synthetic and replaces the source speech. Do not imply voice cloning.
The MMS Khmer checkpoint is CC-BY-NC-4.0: obtain commercial rights before
using it in any commercial product.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import subprocess
import wave
import math
import tempfile


def require_tts_model(path:str)->Path:
    root=Path(path)
    for name in ("config.json","vocab.json"):
        if not (root/name).is_file():
            raise FileNotFoundError(f"Khmer TTS model missing: {root/name}")
    if not any((root/name).is_file() for name in ("model.safetensors","pytorch_model.bin")):
        raise FileNotFoundError("Khmer TTS weights missing in "+str(root))
    return root

@lru_cache(maxsize=1)
def load_khmer_tts(path:str,device:str="cpu"):
    from transformers import VitsModel,AutoTokenizer
    model_path=require_tts_model(path)
    tok=AutoTokenizer.from_pretrained(str(model_path),local_files_only=True)
    model=VitsModel.from_pretrained(str(model_path),local_files_only=True).to(device).eval()
    return tok,model

def synthesize_khmer(text:str,model_path:str,device:str="cpu")->tuple[np.ndarray,int]:
    import torch
    import numpy as np
    if not text.strip():
        raise ValueError("Cannot synthesize empty Khmer speech")
    if not any("\u1780"<=c<="\u17ff" for c in text):
        raise ValueError("Khmer TTS input must contain Khmer Unicode")
    tok,model=load_khmer_tts(model_path,device)
    inputs=tok(text,return_tensors="pt")
    inputs={k:v.to(device) for k,v in inputs.items()}
    with torch.inference_mode():
        output=model(**inputs).waveform.squeeze().float().cpu().numpy()
    rate=int(model.config.sampling_rate)
    if output.size==0 or not np.isfinite(output).all():
        raise RuntimeError("Khmer TTS returned invalid audio")
    return np.clip(output,-1,1).astype(np.float32),rate

def resample_to_length(audio:np.ndarray,sample_rate:int,samples:int)->np.ndarray:
    """Stretch/compress synthesized speech to the ASR subtitle time slot.

    Linear interpolation preserves timing but changes pitch; a future
    pitch-preserving stretch engine should replace this research MVP.
    """
    import numpy as np
    if samples<=0: return np.zeros(0,dtype=np.float32)
    if len(audio)==0:return np.zeros(samples,dtype=np.float32)
    source_seconds=len(audio)/sample_rate
    target_seconds=samples/24000
    # Reject extreme speedups: this is unintelligible and should fail visibly.
    ratio=source_seconds/max(target_seconds,0.001)
    if ratio>2.5:
        raise ValueError(f"Khmer dubbing needs {ratio:.1f}x speedup; subtitle timing is too short")
    positions=np.linspace(0,len(audio)-1,samples)
    return np.interp(positions,np.arange(len(audio)),audio).astype(np.float32)

def build_dubbed_audio(rows,output:Path,duration_seconds:float,model_path:str,
                       device:str="cpu",synthesizer=None,max_duration_seconds:float=600)->Path:
    """Produce a 24kHz mono PCM track with silence outside translated speech."""
    import numpy as np
    if not math.isfinite(duration_seconds) or not 0<duration_seconds<=max_duration_seconds:
        raise ValueError("Invalid video duration")
    rate=24000
    # Disk-backed assembly avoids allocating several full-length audio arrays
    # in RAM when an administrator enables long videos.
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryFile(dir=output.parent) as backing:
        samples=round(duration_seconds*rate)
        if samples<1:
            raise ValueError("Invalid video duration")
        backing.truncate(samples*4)
        timeline=np.memmap(backing,dtype=np.float32,mode="r+",shape=(samples,))
        try:
            return _assemble_track(rows,output,timeline,rate,model_path,device,synthesizer)
        finally:
            timeline._mmap.close()

def _assemble_track(rows,output,timeline,rate,model_path,device,synthesizer):
    import numpy as np
    synth=synthesizer or (lambda text:synthesize_khmer(text,model_path,device))
    populated=0
    for row in rows:
        if not row.target_text.strip():continue
        start=max(0,round(row.start_ms*rate/1000))
        end=min(len(timeline),round(row.end_ms*rate/1000))
        if end<=start:continue
        waveform,source_rate=synth(row.target_text)
        piece=resample_to_length(waveform,source_rate,end-start)
        timeline[start:end]+=piece
        populated+=1
    if not populated:
        raise ValueError("No translated Khmer speech segments available for dubbing")
    block_size=rate*10
    peak=max(float(np.max(np.abs(timeline[i:i+block_size])))
             for i in range(0,len(timeline),block_size))
    gain=0.95/peak if peak>0.95 else 1.0
    with wave.open(str(output),"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
        for i in range(0,len(timeline),block_size):
            block=timeline[i:i+block_size]*gain
            wav.writeframes((np.clip(block,-1,1)*32767).astype("<i2").tobytes())
    return output
