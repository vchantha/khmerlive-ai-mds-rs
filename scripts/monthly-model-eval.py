#!/usr/bin/env python3
"""Monthly model-quality evaluation on human-reviewed bilingual audio samples.

Never fabricates accuracy: if weights, reference data or dependencies are
missing, the command fails without writing a pass report.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time

def main():
    ap=argparse.ArgumentParser(description="Monthly KhmerLive offline model benchmark")
    ap.add_argument("--manifest",required=True,help="JSONL samples with audio/source_reference/target_reference")
    ap.add_argument("--report-dir",default="benchmarks/reports")
    ap.add_argument("--asr",default="/models/asr")
    ap.add_argument("--mt",default="/models/mt")
    ap.add_argument("--device",choices=["cpu","cuda"],default="cpu")
    ap.add_argument("--min-chrf",type=float,default=None,help="Optional quality gate in 0–100")
    ap.add_argument("--max-cer",type=float,default=None,help="Optional source ASR CER gate, 0–1")
    args=ap.parse_args()
    if args.min_chrf is not None and not 0<=args.min_chrf<=100:ap.error("--min-chrf must be in [0,100]")
    if args.max_cer is not None and not 0<=args.max_cer<=1:ap.error("--max-cer must be in [0,1]")
    manifest=Path(args.manifest).resolve()
    if not manifest.is_file():ap.error("Benchmark manifest does not exist")
    rows=[]
    for index,line in enumerate(manifest.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():continue
        try:row=json.loads(line)
        except json.JSONDecodeError as exc:ap.error(f"Manifest JSON error at line {index}: {exc}")
        if row.get("source_lang") not in ("en","km") or row.get("target_lang") not in ("en","km") or row["source_lang"]==row["target_lang"]:
            ap.error(f"Invalid language pair on line {index}")
        if not row.get("source_reference") or not row.get("target_reference"):
            ap.error(f"Missing human reference text on line {index}")
        audio=Path(row["audio"])
        if not audio.is_absolute():audio=manifest.parent/audio
        if not audio.is_file():ap.error(f"Missing audio for line {index}: {audio}")
        row["audio"]=str(audio)
        rows.append(row)
    if not rows:ap.error("No reviewed benchmark samples supplied")
    try:
        from sacrebleu.metrics import CHRF
    except ImportError as exc:
        raise RuntimeError("Install sacrebleu in the real model environment") from exc
    from app.real_inference import translate_audio,model_paths
    from app.quality_metrics import corpus_error
    model_paths(args.asr,args.mt)
    group={}
    for row in rows:
        direction=row["source_lang"]+"_"+row["target_lang"]
        group.setdefault(direction,{"source_preds":[],"source_refs":[],
            "target_preds":[],"target_refs":[],"times":[]})
        start=time.monotonic()
        segments=translate_audio(Path(row["audio"]),row["source_lang"],row["target_lang"],
                                 args.asr,args.mt,args.device)
        elapsed=round(time.monotonic()-start,2)
        if not segments:raise RuntimeError("Empty recognition/translation result for "+row["audio"])
        sample=group[direction]
        sample["source_preds"].append(" ".join(s.source_text for s in segments))
        sample["source_refs"].append(row["source_reference"])
        sample["target_preds"].append(" ".join(s.target_text for s in segments))
        sample["target_refs"].append(row["target_reference"])
        sample["times"].append(elapsed)
    report={"month":datetime.now(timezone.utc).strftime("%Y-%m"),
            "generated_utc":datetime.now(timezone.utc).isoformat(),
            "samples":len(rows),"device":args.device,"directions":{},"passed_gates":True}
    for direction,data in group.items():
        language=direction.split("_")[0]
        asr=corpus_error(data["source_preds"],data["source_refs"],language)
        chrf=CHRF(word_order=2).corpus_score(data["target_preds"],[data["target_refs"]]).score
        passed=(args.max_cer is None or asr["cer"]<=args.max_cer) and (args.min_chrf is None or chrf>=args.min_chrf)
        report["directions"][direction]={"count":len(data["source_refs"]),
            "source_cer":asr["cer"],"source_wer":asr["wer"],
            "translation_chrf2":round(chrf,3),
            "inference_wall_seconds":round(sum(data["times"]),2),
            "passed_gates":passed}
        report["passed_gates"]=report["passed_gates"] and passed
    reportdir=Path(args.report_dir)
    reportdir.mkdir(parents=True,exist_ok=True)
    output=reportdir/(report["month"]+"-evaluation.json")
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(output),"summary":report["directions"],
                      "passed_gates":report["passed_gates"]},ensure_ascii=False,indent=2))
    return 0 if report["passed_gates"] else 2

if __name__=="__main__":sys.exit(main())
