#!/usr/bin/env python3
"""Build the frozen English→Khmer held-out evaluation sets (standard library only).

  # 1. Text benchmark from FLORES-200 (professional human translations, CC BY-SA 4.0).
  #    Download once on a connected machine:
  #      curl -fL -o benchmarks/private/downloads/flores200_dataset.tar.gz \
  #           https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz
  python3 scripts/build-eval-set.py flores --tarball benchmarks/private/downloads/flores200_dataset.tar.gz

  # 2. Spoken-video set: export your completed jobs for a Khmer translator ...
  python3 scripts/build-eval-set.py video-template --job <job-id> [--job <job-id> ...]
  # ... then, after the translator fills reference_km, freeze it:
  python3 scripts/build-eval-set.py video-import --csv benchmarks/private/eval/video-template.csv

Splits are by document (FLORES article / whole video). Sets are written to
benchmarks/private/eval/<name>/ (git-ignored) with a DATASET_CARD.json holding sha256
checksums; an existing set is never overwritten. See docs/EVALUATION_E0_E1.md.
"""
import argparse
import csv
import io
import json
import os
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app import evaluation as ev  # noqa: E402  (stdlib-only parts)

FLORES_URL = "https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz"
# sha256 of the tarball this project's first evaluation set was built from (2026-11-17).
FLORES_SHA256 = "b8b0b76783024b85797e5cc75064eb83fc5288b41e9654dabc7be6ae944011f6"


def _exclusions(paths):
    keys = ev.load_exclusions([Path(p) for p in paths])
    if paths:
        print(f"Excluding {len(keys)} sentence(s) found in training data", flush=True)
    return keys


def _freeze(out: Path, splits: dict, card: dict):
    if out.exists():
        sys.exit(f"ERROR: {out} already exists. Evaluation sets are immutable; pass --name for a new version.")
    leakage = ev.check_leakage(splits)
    files = {}
    for split, rows in splits.items():
        files[split] = {"file": f"{split}.jsonl", "rows": len(rows), "sha256": ev.write_jsonl(out / f"{split}.jsonl", rows)}
    # Source keys of every split, so MT fine-tuning can refuse evaluation sentences.
    keys = sorted({ev.source_key(r["source"]) for rows in splits.values() for r in rows})
    (out / "eval_source_keys.txt").write_text("\n".join(keys) + "\n", encoding="utf-8")
    card.update(schema_version=ev.SCHEMA_VERSION, created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                files=files, leakage_check=leakage, text_normalization="NFC, U+200B/U+FEFF removed, whitespace collapsed")
    (out / "DATASET_CARD.json").write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(out), "files": files, "leakage_check": leakage}, indent=2))


def cmd_flores(a):
    tarball = Path(a.tarball)
    digest = ev.sha256_file(tarball)
    if digest != FLORES_SHA256 and not a.allow_other_tarball:
        sys.exit(f"ERROR: tarball sha256 {digest} differs from the pinned {FLORES_SHA256}. "
                 "Pass --allow-other-tarball only for a deliberate new dataset version.")
    with tarfile.open(tarball) as tf:
        def read(name):
            for prefix in ("./flores200_dataset/", "flores200_dataset/"):
                try:
                    return tf.extractfile(prefix + name).read().decode("utf-8")
                except KeyError:
                    continue
            raise KeyError(name)
        def lines(name):
            return read(name).rstrip("\n").split("\n")
        # FLORES dev/devtest come from disjoint Wikipedia articles; check_leakage verifies it.
        dev = ev.flores_rows(lines("dev/eng_Latn.dev"), lines("dev/khm_Khmr.dev"), read("metadata_dev.tsv"), "prompt_dev", "dev")
        test = ev.flores_rows(lines("devtest/eng_Latn.devtest"), lines("devtest/khm_Khmr.devtest"),
                              read("metadata_devtest.tsv"), "heldout_test", "devtest")
    excluded = _exclusions(a.exclude)
    before = len(dev) + len(test)
    dev = [r for r in dev if ev.source_key(r["source"]) not in excluded]
    test = [r for r in test if ev.source_key(r["source"]) not in excluded]
    card = {"name": a.name, "language_pair": "en-km",
            "source": {"corpus": "FLORES-200 (NLLB Team, Meta AI)", "url": FLORES_URL, "tarball_sha256": digest,
                       "license": "CC BY-SA 4.0 — keep attribution; do not commit the text to this repository"},
            "splits": {"prompt_dev": "FLORES-200 dev — use for prompt/setting development only",
                       "heldout_test": "FLORES-200 devtest — frozen; report final E0/E1 results here only"},
            "split_unit": "source document (Wikipedia article URL)",
            "excluded_training_overlap": before - len(dev) - len(test),
            "limitations": ["Written Wikipedia text, not spoken video dialogue: domain mismatch with dubbing.",
                            "No timestamps: E1 receives an estimated 2.5 words/s duration budget.",
                            "FLORES is public; LLMs (e.g. Qwen3) may have seen it during pre-training.",
                            "One human reference per sentence: chrF++/BLEU under-reward valid paraphrases."]}
    _freeze(ROOT / "benchmarks/private/eval" / a.name, {"prompt_dev": dev, "heldout_test": test}, card)


def _api(base, path):
    key = os.getenv("API_KEY")
    if not key and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    req = Request(base.rstrip("/") + path, headers={"X-API-Key": key or ""})
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def cmd_video_template(a):
    out = Path(a.out)
    if out.exists():
        sys.exit(f"ERROR: {out} exists; choose another --out so a translator's work is never overwritten.")
    rows = []
    for job in a.job:
        data = _api(a.base, f"/api/jobs/{job}/segments")
        if data.get("source_lang") != "en" or data.get("target_lang") != "km" or not data.get("available"):
            sys.exit(f"ERROR: job {job} is not a completed English→Khmer job with segments")
        rows += ev.video_template_rows(job, data["items"], a.heldout_fraction)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=ev.TEMPLATE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        by[r["split"]] = by.get(r["split"], 0) + 1
    print(f"Wrote {len(rows)} lines from {len(a.job)} video(s) to {out}: {by}")
    print("A bilingual translator fills reference_km from the ENGLISH (not by editing the machine column).")


def cmd_video_import(a):
    rows = ev.video_rows_from_template(Path(a.csv).read_text(encoding="utf-8"))
    excluded = _exclusions(a.exclude)
    rows = [r for r in rows if ev.source_key(r["source"]) not in excluded]
    splits = {s: [r for r in rows if r["split"] == s] for s in ("prompt_dev", "heldout_test")}
    splits = {k: v for k, v in splits.items() if v}
    if "heldout_test" not in splits:
        sys.exit("ERROR: no translated held-out lines yet")
    card = {"name": a.name, "language_pair": "en-km",
            "source": {"corpus": "KhmerLive video jobs, human reference translations", "template": str(a.csv)},
            "split_unit": "whole video (deterministic hash of job id)",
            "translators": sorted({r["translator"] for r in rows if r["translator"]}),
            "limitations": ["Single translator per line unless noted; check inter-translator agreement.",
                            "Speech recognition errors in source_en propagate to E0 and E1 equally."]}
    _freeze(ROOT / "benchmarks/private/eval" / a.name, splits, card)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("flores")
    f.add_argument("--tarball", required=True)
    f.add_argument("--name", default="flores200-en-km-v1")
    f.add_argument("--exclude", action="append", default=[], help="Training JSONL (corrections export) to exclude")
    f.add_argument("--allow-other-tarball", action="store_true")
    t = sub.add_parser("video-template")
    t.add_argument("--job", action="append", required=True)
    t.add_argument("--out", default=str(ROOT / "benchmarks/private/eval/video-template.csv"))
    t.add_argument("--base", default="http://localhost:8080")
    t.add_argument("--heldout-fraction", type=float, default=0.5)
    i = sub.add_parser("video-import")
    i.add_argument("--csv", required=True)
    i.add_argument("--name", default="video-en-km-v1")
    i.add_argument("--exclude", action="append", default=[])
    a = p.parse_args()
    {"flores": cmd_flores, "video-template": cmd_video_template, "video-import": cmd_video_import}[a.cmd](a)


if __name__ == "__main__":
    main()
