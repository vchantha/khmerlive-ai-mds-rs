"""Interfaces and safe demo adapters. No fabricated Khmer translations.

Production offline adapters must be benchmarked and installed separately.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

@dataclass(frozen=True)
class SpeechResult:
    text:str

class ASR(Protocol):
    def transcribe(self,audio:Path,language:str)->SpeechResult:...
class MT(Protocol):
    def translate(self,text:str,source:str,target:str)->str:...

class DemoASR:
    def transcribe(self,audio:Path,language:str)->SpeechResult:
        return SpeechResult(f"[DEMO ONLY: no {language.upper()} speech recognition performed]")
class DemoMT:
    def translate(self,text:str,source:str,target:str)->str:
        return f"[DEMO ONLY: no {source.upper()}→{target.upper()} translation performed]"

def get_adapters():
    from app.config import settings
    if settings.model_mode != "demo":
        raise RuntimeError("Real model adapters not installed. Use MODEL_MODE=demo; see docs/REAL_MODELS.md")
    return DemoASR(),DemoMT()
