"""Offline Khmer speech synthesis and timed voice-dub track assembly.

Audio is synthetic and replaces the source speech. Do not imply voice cloning.
The MMS Khmer checkpoint is CC-BY-NC-4.0: obtain commercial rights before
using it in any commercial product.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import logging
import subprocess
import wave

logger=logging.getLogger(__name__)


# Speed-ups beyond this through VITS' own duration control start to sound rushed.
MAX_NATIVE_SPEAKING_RATE=1.5
# Total speed-up allowed (native rate x pitch-preserving tempo). Longer lines are trimmed with a fade.
MAX_TOTAL_SPEEDUP=2.0
# The dub may start this much before the English speech when it needs the room.
MAX_LEAD_SECONDS=0.2
FADE_IN_SECONDS=0.008
FADE_OUT_SECONDS=0.025
# Every line is normalised to the same loudness (RMS) so the voice level doesn't jump.
TARGET_RMS=0.08

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

def synthesize_khmer(text:str,model_path:str,device:str="cpu",speaking_rate:float=1.0)->tuple[np.ndarray,int]:
    import torch
    import numpy as np
    if not text.strip():
        raise ValueError("Cannot synthesize empty Khmer speech")
    if not any("\u1780"<=c<="\u17ff" for c in text):
        raise ValueError("Khmer TTS input must contain Khmer Unicode")
    tok,model=load_khmer_tts(model_path,device)
    inputs=tok(text,return_tensors="pt")
    inputs={k:v.to(device) for k,v in inputs.items()}
    # VITS speaking_rate shortens phoneme durations without changing pitch.
    default_rate=model.speaking_rate
    try:
        model.speaking_rate=speaking_rate
        # VITS samples noise for prosody; a fixed seed keeps the voice consistent run to run.
        torch.manual_seed(1234)
        with torch.inference_mode():
            output=model(**inputs).waveform.squeeze().float().cpu().numpy()
    finally:
        model.speaking_rate=default_rate
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

def time_stretch(audio:np.ndarray,sample_rate:int,factor:float)->np.ndarray:
    """Pitch-preserving speed change (ffmpeg atempo, WSOLA). factor>1 = faster/shorter."""
    import numpy as np
    if abs(factor-1.0)<0.01 or len(audio)==0:
        return audio
    proc=subprocess.run(["ffmpeg","-v","error","-nostdin","-f","f32le","-ar",str(sample_rate),"-ac","1",
                         "-i","pipe:0","-filter:a",f"atempo={factor:.4f}","-f","f32le","pipe:1"],
                        input=audio.astype("<f4").tobytes(),capture_output=True,check=True,timeout=60)
    return np.frombuffer(proc.stdout,dtype="<f4").astype(np.float32)

def _resample(audio:np.ndarray,src:int,dst:int)->np.ndarray:
    """Band-limited sample-rate conversion via ffmpeg (only used if lines differ in rate)."""
    import numpy as np
    if src==dst or len(audio)==0:
        return audio
    proc=subprocess.run(["ffmpeg","-v","error","-nostdin","-f","f32le","-ar",str(src),"-ac","1","-i","pipe:0",
                         "-ar",str(dst),"-f","f32le","pipe:1"],input=audio.astype("<f4").tobytes(),
                        capture_output=True,check=True,timeout=60)
    return np.frombuffer(proc.stdout,dtype="<f4").astype(np.float32)

def _polish(piece:np.ndarray,rate:int)->np.ndarray:
    """Even loudness plus short fades so lines don't click or jump in volume."""
    import numpy as np
    piece=piece.astype(np.float32).copy()
    rms=float(np.sqrt(np.mean(piece**2))) if len(piece) else 0.0
    if rms>1e-4:
        piece*=min(4.0,max(0.3,TARGET_RMS/rms))
    fi=min(len(piece)//2,int(FADE_IN_SECONDS*rate));fo=min(len(piece)//2,int(FADE_OUT_SECONDS*rate))
    if fi:piece[:fi]*=np.linspace(0,1,fi,dtype=np.float32)
    if fo:piece[-fo:]*=np.linspace(1,0,fo,dtype=np.float32)
    return piece

def fit_line(waveform:np.ndarray,rate:int,available:int,native=None)->tuple[np.ndarray,str]:
    """Fit one synthesized line into `available` samples without ever slowing it down.

    native(speed) re-synthesizes with VITS' own speaking rate (most natural); the rest
    is a pitch-preserving tempo change; beyond MAX_TOTAL_SPEEDUP the line is trimmed.
    """
    import numpy as np
    if len(waveform)<=available:
        return waveform,"natural"
    need=len(waveform)/max(available,1)
    how=""
    if native is not None:
        speed=min(MAX_NATIVE_SPEAKING_RATE,need)
        waveform,src=native(speed)
        if src!=rate:waveform=_resample(waveform,src,rate)
        how="native"
        if len(waveform)<=available:
            return waveform,how
    # 1% margin: atempo output can run a few ms long.
    factor=min(len(waveform)/available*1.01,MAX_TOTAL_SPEEDUP/(min(MAX_NATIVE_SPEAKING_RATE,need) if native else 1.0))
    if factor>1.0:
        waveform=time_stretch(waveform,rate,factor);how=(how+"+tempo").lstrip("+")
    if len(waveform)>available:
        if len(waveform)>available*1.02:how+="+trimmed"
        waveform=waveform[:available]
    return waveform,how or "natural"

def build_dubbed_audio(rows,output:Path,duration_seconds:float,model_path:str,
                       device:str="cpu",synthesizer=None,stats_out:dict|None=None)->Path:
    """Produce a mono PCM track: each Khmer line at natural pitch, placed at its subtitle time.

    Lines play at natural speed. Lines longer than the gap to the next one are sped up
    (native VITS rate first, then pitch-preserving tempo); they are never slowed down or
    resampled in a way that changes pitch. Silence outside translated speech.
    """
    import numpy as np
    if duration_seconds<=0 or duration_seconds>3600:
        raise ValueError("Invalid video duration")
    synth=synthesizer or (lambda text:synthesize_khmer(text,model_path,device))
    # Native (pitch-preserving) speed-up is only possible with the real model.
    native_for=None if synthesizer else (lambda text:(lambda r:synthesize_khmer(text,model_path,device,speaking_rate=r)))
    spoken=sorted((r for r in rows if r.target_text.strip()),key=lambda r:r.start_ms)
    if not spoken:
        raise ValueError("No translated Khmer speech segments available for dubbing")
    rate=None;timeline=None;written_to=0;stats={}
    for index,row in enumerate(spoken):
        waveform,src=synth(row.target_text)
        if rate is None:
            rate=int(src);timeline=np.zeros(round(duration_seconds*rate),dtype=np.float32)
        if src!=rate:waveform=_resample(waveform,src,rate)
        start=min(len(timeline),round(row.start_ms*rate/1000))
        following=[r.start_ms for r in spoken[index+1:] if r.start_ms>row.start_ms]
        limit=min(round(following[0]*rate/1000) if following else len(timeline),len(timeline))
        if limit<=start:continue
        # Borrow up to MAX_LEAD_SECONDS before the English line if the speech needs room.
        if len(waveform)>limit-start:
            start=max(written_to,start-int(MAX_LEAD_SECONDS*rate),0)
        piece,how=fit_line(waveform,rate,limit-start,native_for(row.target_text) if native_for else None)
        piece=_polish(piece,rate)
        timeline[start:start+len(piece)]+=piece
        written_to=start+len(piece)
        stats[how]=stats.get(how,0)+1
    if not stats:
        raise ValueError("No translated Khmer speech segments available for dubbing")
    logger.info("Khmer dub: %d lines placed %s",sum(stats.values()),stats)
    if stats_out is not None:stats_out.update(stats)
    peak=float(np.max(np.abs(timeline)))
    if peak>0.95:timeline*=0.95/peak
    output.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(output),"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
        wav.writeframes((np.clip(timeline,-1,1)*32767).astype("<i2").tobytes())
    return output
