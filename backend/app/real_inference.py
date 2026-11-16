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

def asr_compute_type(device: str, requested: str = "") -> str:
    """int8_float16 on GPU halves Whisper's VRAM versus float16 at about the same speed."""
    if requested:
        return requested
    return "int8_float16" if device == "cuda" else "int8"


class OfflineWhisper:
    def __init__(self, path: Path, device: str = "cpu", compute_type: str = "int8",
                 cpu_threads: int = 0):
        import os
        from faster_whisper import WhisperModel
        # CTranslate2 defaults to 4 threads; use every core unless told otherwise.
        threads = cpu_threads or (os.cpu_count() or 4)
        self.device = device
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


# Shared decoding settings for both M2M100 engines.
# M2M100-418M can loop a phrase for EN->KM; block repeats.
NO_REPEAT_NGRAM = 3
REPETITION_PENALTY = 1.2
MAX_NEW_TOKENS = 256


def _check_pair(src: str, dst: str):
    if src not in ("en", "km") or dst not in ("en", "km") or src == dst:
        raise ValueError("Only EN↔KM translation is supported")


class OfflineM2M100:
    """Hugging Face Transformers M2M100 (fallback engine; no conversion needed)."""
    engine = "transformers"

    def __init__(self, path: Path, device: str = "cpu", beam_size: int = 4):
        import torch
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
        self._torch = torch
        self.device = device
        self.beam_size = beam_size
        self.tok = M2M100Tokenizer.from_pretrained(str(path), local_files_only=True)
        model = M2M100ForConditionalGeneration.from_pretrained(str(path), local_files_only=True)
        if device == "cuda":
            model = model.half()   # fp16 halves VRAM; no quality-relevant change for decoding
        self.model = model.to(device).eval()

    def translate(self, rows: list[TimedText], src: str, dst: str) -> list[TimedText]:
        _check_pair(src, dst)
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
                    max_new_tokens=MAX_NEW_TOKENS, num_beams=self.beam_size,
                    no_repeat_ngram_size=NO_REPEAT_NGRAM, repetition_penalty=REPETITION_PENALTY
                )
            decoded = self.tok.batch_decode(encoded, skip_special_tokens=True)
            result.extend(TimedText(s.start_ms, s.end_ms, s.source_text, t.strip())
                          for s, t in zip(batch, decoded, strict=True))
        return result


class CTranslate2M2M100:
    """M2M100 converted to CTranslate2 int8: same model, typically 3-4x faster on CPU.

    Create it once with scripts/convert-mt-ct2.sh. The tokenizer still comes from
    the original Hugging Face directory.
    """
    engine = "ctranslate2"

    def __init__(self, ct2_path: Path, hf_path: Path, device: str = "cpu",
                 cpu_threads: int = 0, beam_size: int = 4):
        import ctranslate2
        from transformers import M2M100Tokenizer
        self.device = device
        self.beam_size = beam_size
        self.tok = M2M100Tokenizer.from_pretrained(str(hf_path), local_files_only=True)
        compute = "int8_float16" if device == "cuda" else "int8"
        self.translator = ctranslate2.Translator(str(ct2_path), device=device, compute_type=compute,
                                                 inter_threads=1, intra_threads=cpu_threads or 0)

    def translate(self, rows: list[TimedText], src: str, dst: str) -> list[TimedText]:
        _check_pair(src, dst)
        self.tok.src_lang = src
        sources = [self.tok.convert_ids_to_tokens(self.tok.encode(r.source_text, truncation=True, max_length=256))
                   for r in rows]
        target_token = self.tok.lang_code_to_token[dst]
        out = self.translator.translate_batch(
            sources, target_prefix=[[target_token]] * len(sources), beam_size=self.beam_size,
            max_batch_size=16, max_decoding_length=MAX_NEW_TOKENS,
            no_repeat_ngram_size=NO_REPEAT_NGRAM, repetition_penalty=REPETITION_PENALTY)
        result = []
        for row, res in zip(rows, out, strict=True):
            tokens = [t for t in res.hypotheses[0] if t != target_token]
            text = self.tok.decode(self.tok.convert_tokens_to_ids(tokens), skip_special_tokens=True)
            result.append(TimedText(row.start_ms, row.end_ms, row.source_text, text.strip()))
        return result


def ct2_model_ready(path: str) -> bool:
    return bool(path) and (Path(path) / "model.bin").is_file()


@lru_cache(maxsize=2)
def load_whisper(asr_dir: str, device: str, compute_type: str, cpu_threads: int) -> OfflineWhisper:
    return OfflineWhisper(Path(asr_dir), device, compute_type, cpu_threads)


@lru_cache(maxsize=2)
def load_translator(mt_dir: str, device: str, cpu_threads: int = 0, engine: str = "auto",
                    ct2_dir: str = "", beam_size: int = 4):
    if engine not in ("auto", "ctranslate2", "transformers"):
        raise ValueError("MT_ENGINE must be auto, ctranslate2 or transformers")
    if engine == "ctranslate2" or (engine == "auto" and ct2_model_ready(ct2_dir)):
        if not ct2_model_ready(ct2_dir):
            raise FileNotFoundError(f"CTranslate2 model missing at {ct2_dir}; run scripts/convert-mt-ct2.sh")
        return CTranslate2M2M100(Path(ct2_dir), Path(mt_dir), device, cpu_threads, beam_size)
    return OfflineM2M100(Path(mt_dir), device, beam_size)


def release_whisper():
    """Drop cached Whisper models (frees their GPU memory for the LLM)."""
    load_whisper.cache_clear()
    import gc
    gc.collect()


def load_engines(asr_dir: str, mt_dir: str, device: str, cpu_threads: int = 0):
    """Back-compat helper: both engines on one device."""
    asr, mt = model_paths(asr_dir, mt_dir)
    return (load_whisper(str(asr), device, asr_compute_type(device), cpu_threads),
            load_translator(str(mt), device, cpu_threads))


def translate_audio(wav_path: Path, src: str, dst: str, asr_dir: str,
                    mt_dir: str, device: str = "cpu", cpu_threads: int = 0, *,
                    mt_device: str | None = None, asr_compute: str = "", mt_engine: str = "auto",
                    mt_ct2_dir: str = "", beam_size: int = 4, timings: dict | None = None,
                    keep_asr_loaded: bool = True) -> list[TimedText]:
    """Speech recognition then translation. `device` is the ASR device; MT uses `mt_device` (default: same)."""
    import time
    asr, mt = model_paths(asr_dir, mt_dir)
    t0 = time.monotonic()
    whisper = load_whisper(str(asr), device, asr_compute_type(device, asr_compute), cpu_threads)
    segments = whisper.transcribe(wav_path, src)
    if not keep_asr_loaded:
        del whisper
        release_whisper()
    t1 = time.monotonic()
    if timings is not None:
        timings["asr"] = timings.get("asr", 0) + round(t1 - t0, 2)
    if not segments:
        raise ValueError("No intelligible speech segments detected; no subtitle output")
    translator = load_translator(str(mt), mt_device or device, cpu_threads, mt_engine, mt_ct2_dir, beam_size)
    result = translator.translate(segments, src, dst)
    if timings is not None:
        timings["translate"] = timings.get("translate", 0) + round(time.monotonic() - t1, 2)
        timings["mt_engine"] = translator.engine
        timings["segments"] = timings.get("segments", 0) + len(result)
    if not any(s.target_text.strip() for s in result):
        raise ValueError("Translation model produced no text")
    return result
