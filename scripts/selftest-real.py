#!/usr/bin/env python3
"""Local inference smoke test after models are installed (NOT a quality benchmark)."""
import argparse
import sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--audio",required=True,help="Existing short WAV with intelligible EN/KM speech")
    p.add_argument("--source",choices=["en","km"],default="en")
    p.add_argument("--target",choices=["en","km"],default="km")
    p.add_argument("--asr",default="/models/asr")
    p.add_argument("--mt",default="/models/mt")
    p.add_argument("--device",choices=["cpu","cuda"],default="cpu")
    args=p.parse_args()
    if args.source==args.target:
        p.error("Source and target languages must differ")
    if not Path(args.audio).is_file():
        p.error("Audio not found inside the container: "+args.audio)
    from app.real_inference import translate_audio,build_srt
    result=translate_audio(Path(args.audio),args.source,args.target,
                           args.asr,args.mt,args.device)
    srt=build_srt(result)
    if not srt.strip():
        raise RuntimeError("Empty subtitle result")
    print("segments:",len(result))
    for segment in result[:5]:
        print(segment.start_ms,segment.end_ms,
              repr(segment.source_text),"=>",repr(segment.target_text))
    print("PASS: local inference returned text. Quality and accuracy are NOT validated.")
    return 0

if __name__=="__main__":
    sys.exit(main())
