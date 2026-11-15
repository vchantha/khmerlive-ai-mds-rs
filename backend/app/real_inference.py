"""Local-only Whisper ASR and M2M100 translation for subtitle generation.

Model weights must be provisioned in /models before enabling real_subtitles.
No network model resolution happens in these adapters.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

@dataclass(frozen=True)
class TimedText:
    start_ms: int
    end_ms: int
    source_text: str
    target_text: str = ""

def model_paths(asr_path: str, mt_path: str) -> tuple[Path, Path]:
    asr, mt = Path(asr_path), Path(mt_path)
    required = [(asr, "model.bin"), (asr, "config.json"), (mt, "config.json")]
    for directory, name in required:
        if not (directory / name).is_file():
            raise FileNotFoundError(
                f"Offline model asset missing: {directory / name}. "
                "Run scripts/download-models.py on an online staging machine."
            )
    if not any((mt / n).is_file() for n in ("model.safetensors", "pytorch_model.bin")):
        raise FileNotFoundError("Offline M2M100 weight file missing at " + str(mt))
    return asr, mt

def timestamp(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def build_srt(items: list[TimedText]) -> str:
    parts = []
    for index, row in enumerate(items, 1):
        if not row.target_text.strip():
            continue
        end = max(row.start_ms + 250, row.end_ms)
        # One translation per recognized speech segment, no invented dialog.
        parts.append(f"{index}\n{timestamp(row.start_ms)} --> {timestamp(end)}\n{row.target_text.strip()}\n")
    return "\n".join(parts) + ("\n" if parts else "")

class OfflineWhisper:
    def __init__(self, path: Path, device: str = "cpu", compute_type: str = "int8",
                 cpu_threads: int = 0):
        import os
        from faster_whisper import WhisperModel
        # CTranslate2 defaults to 4 threads; use every core unless told otherwise.
        threads = cpu_threads or (os.cpu_count() or 4)
        self._model = WhisperModel(str(path), device=device, compute_type=compute_type,
                                   cpu_threads=threads, local_files_only=True)

    def transcribe(self, wav_path: Path, language: str) -> list[TimedText]:
        segments, info = self._model.transcribe(
            str(wav_path), language=language, task="transcribe",
            beam_size=5, condition_on_previous_text=False,
            # Skip silence/music instead of decoding it: large speedup on long
            # media and fewer hallucinated segments in non-speech regions.
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 500}
        )
        results: list[TimedText] = []
        for s in segments:
            raw = s.text.strip()
            if not raw:
                continue
            results.append(TimedText(
                start_ms=max(0, round(s.start * 1000)),
                end_ms=max(0, round(s.end * 1000)),
                source_text=raw
            ))
        return results

class OfflineM2M100:
    def __init__(self, path: Path, device: str = "cpu"):
        import torch
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
        self._torch = torch
        self.device = device
        self.tok = M2M100Tokenizer.from_pretrained(str(path), local_files_only=True)
        self.model = M2M100ForConditionalGeneration.from_pretrained(
            str(path), local_files_only=True
        ).to(device).eval()

    def translate(self, rows: list[TimedText], src: str, dst: str) -> list[TimedText]:
        if src not in ("en", "km") or dst not in ("en", "km") or src == dst:
            raise ValueError("Only EN↔KM translation is supported")
        self.tok.src_lang = src
        result: list[TimedText] = []
        # Bound peak memory on CPU; text segmentation is ASR timestamp-driven.
        for i in range(0, len(rows), 8):
            batch = rows[i:i + 8]
            data = self.tok([s.source_text for s in batch], return_tensors="pt",
                            padding=True, truncation=True, max_length=256)
            data = {k: v.to(self.device) for k, v in data.items()}
            with self._torch.inference_mode():
                encoded = self.model.generate(
                    **data, forced_bos_token_id=self.tok.get_lang_id(dst),
                    max_new_tokens=256, num_beams=4
                )
            decoded = self.tok.batch_decode(encoded, skip_special_tokens=True)
            result.extend(TimedText(s.start_ms, s.end_ms, s.source_text, t.strip())
                          for s, t in zip(batch, decoded, strict=True))
        return result

@lru_cache(maxsize=2)
def load_engines(asr_dir: str, mt_dir: str, device: str, cpu_threads: int = 0):
    asr, mt = model_paths(asr_dir, mt_dir)
    compute = "float16" if device == "cuda" else "int8"
    return OfflineWhisper(asr, device, compute, cpu_threads), OfflineM2M100(mt, device)

def translate_audio(wav_path: Path, src: str, dst: str, asr_dir: str,
                    mt_dir: str, device: str = "cpu", cpu_threads: int = 0) -> list[TimedText]:
    whisper, translator = load_engines(asr_dir, mt_dir, device, cpu_threads)
    segments = whisper.transcribe(wav_path, src)
    if not segments:
        raise ValueError("No intelligible speech segments detected; no subtitle output")
    result = translator.translate(segments, src, dst)
    if not any(s.target_text.strip() for s in result):
        raise ValueError("Translation model produced no text")
    return result
