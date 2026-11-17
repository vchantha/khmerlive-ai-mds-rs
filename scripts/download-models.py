#!/usr/bin/env python3
"""Download pinned, inspectable local assets on an ONLINE staging machine.

Do not run on offline/production host. Review license and use permissions.
"""
import argparse
import hashlib
import json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

CANDIDATES = {
    "asr": ("Systran/faster-whisper-small", "mit"),
    # Default ASR for GPU deployments: 41% fewer word errors than small (LibriSpeech
    # clean 7.48% -> 4.43% WER, measured), ~1.1 GB VRAM. Slow on CPU-only machines.
    "asr-large-v3-turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", "mit"),
    "mt": ("facebook/m2m100_418M", "mit"),
    # Research use only: CC-BY-NC-4.0 prohibits commercial use without rights.
    "tts": ("facebook/mms-tts-khm", "cc-by-nc-4.0"),
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="models")
    parser.add_argument("--only", default="asr,mt,tts",
                        help="comma-separated components: " + ",".join(CANDIDATES) + " (default: asr,mt,tts)")
    parser.add_argument("--asr-revision", default=None, help="40-character Git commit SHA")
    parser.add_argument("--mt-revision", default=None, help="40-character Git commit SHA")
    parser.add_argument("--tts-revision", default=None, help="40-character Git commit SHA")
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    wanted = [c.strip() for c in args.only.split(",") if c.strip()]
    unknown = set(wanted) - set(CANDIDATES)
    if unknown:
        raise SystemExit("Unknown component(s): " + ", ".join(sorted(unknown)))
    lock = root / "manifest.lock.json"
    manifest = json.loads(lock.read_text()) if lock.exists() else {"format":1,"models":[]}
    # Keep entries for components not downloaded in this run.
    manifest["models"] = [m for m in manifest["models"] if m.get("component") not in wanted]
    for key in wanted:
        repo, license_name = CANDIDATES[key]
        revision = getattr(args, key.replace("-", "_") + "_revision", None)
        if not revision:
            revision = api.model_info(repo).sha
        if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision.lower()):
            raise ValueError("Revision must be a full immutable Git commit SHA")
        target = root / key
        target.mkdir(parents=True, exist_ok=True)
        print("Downloading", repo, "@", revision, "to", target)
        snapshot_download(repo_id=repo, revision=revision, local_dir=str(target),
                          ignore_patterns=["*.ot", "*.h5", ".gitattributes"])
        files = {}
        for p in sorted(target.rglob("*")):
            if not p.is_file() or ".cache" in p.parts:
                continue
            digest = hashlib.sha256()
            with p.open("rb") as inp:
                for chunk in iter(lambda: inp.read(1024 * 1024), b""):
                    digest.update(chunk)
            files[str(p.relative_to(target))] = digest.hexdigest()
        manifest["models"].append({"id":repo,"component":key,"revision":revision,
                                     "card_license":license_name,"sha256":files})
    (root / "manifest.lock.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Done. Review model cards/licenses before distributing weights.")
    print("Lock manifest:", root / "manifest.lock.json")

if __name__ == "__main__":
    main()
