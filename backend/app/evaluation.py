"""Held-out evaluation set and E0 (M2M100) vs E1 (M2M100 + offline LLM post-edit) scoring.

Dataset building uses only the standard library (it runs on the host); scoring imports
numpy and sacrebleu lazily (worker image). Nothing here downloads data or calls a model.

Rules this module enforces (see docs/EVALUATION_E0_E1.md):
- Splits are by source document (FLORES article URL / video), never by sentence.
- The held-out test split is frozen: its sha256 is in the dataset card and checked
  before every run. Prompt or setting changes are tuned on the prompt_dev split only.
- Sentences present in any training data (the corrections export used for MT LoRA)
  are excluded, and the fine-tuning script refuses held-out sentences.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import unicodedata
from pathlib import Path

SCHEMA_VERSION = 1
# U+200B ZERO WIDTH SPACE marks word boundaries in some Khmer text (e.g. FLORES references)
# and is invisible; it is removed so chrF does not count it as characters.
_INVISIBLE = dict.fromkeys(map(ord, "​﻿"), None)


def normalize_text(text: str) -> str:
    """NFC, no zero-width spaces, single spaces, stripped quotes-free outer whitespace."""
    text = unicodedata.normalize("NFC", text or "").translate(_INVISIBLE)
    return " ".join(text.split())


def source_key(text: str) -> str:
    """Stable id of an English sentence for leakage checks (case/space/punctuation-insensitive)."""
    t = normalize_text(text).lower()
    t = re.sub(r"[^\w\s]", "", t)
    return hashlib.sha256(" ".join(t.split()).encode()).hexdigest()[:16]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- dataset building
def flores_rows(eng_lines: list[str], khm_lines: list[str], metadata_tsv: str, split: str, corpus_split: str) -> list[dict]:
    """Rows from one FLORES-200 split. Document id = hash of the source article URL."""
    meta = list(csv.DictReader(metadata_tsv.splitlines(), delimiter="\t"))
    if not (len(eng_lines) == len(khm_lines) == len(meta)):
        raise ValueError(f"FLORES {corpus_split}: line counts differ "
                         f"(eng={len(eng_lines)}, khm={len(khm_lines)}, meta={len(meta)})")
    rows = []
    for i, (en, km, m) in enumerate(zip(eng_lines, khm_lines, meta)):
        en, km = normalize_text(en), normalize_text(km)
        if not en or not km:
            raise ValueError(f"FLORES {corpus_split} line {i + 1} is empty")
        rows.append({"id": f"flores200-{corpus_split}-{i + 1:04d}", "split": split,
                     "doc_id": "doc-" + hashlib.sha256(m["URL"].encode()).hexdigest()[:12],
                     "domain": m.get("domain", ""), "topic": m.get("topic", ""),
                     "source_lang": "en", "target_lang": "km", "source": en, "reference": km,
                     "corpus": "FLORES-200", "corpus_split": corpus_split})
    return rows


def load_exclusions(paths: list[Path]) -> set[str]:
    """Source keys of sentences that appear in training data (corrections JSONL exports)."""
    keys = set()
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                text = row.get("source") or row.get("source_text") or ""
                if text:
                    keys.add(source_key(text))
    return keys


def check_leakage(splits: dict[str, list[dict]]) -> dict:
    """Fail if any document or sentence is shared between splits."""
    docs = {name: {r["doc_id"] for r in rows} for name, rows in splits.items()}
    sents = {name: {source_key(r["source"]) for r in rows} for name, rows in splits.items()}
    names = sorted(splits)
    report = {"documents": {n: len(docs[n]) for n in names}, "sentences": {n: len(splits[n]) for n in names},
              "shared_documents": 0, "shared_sentences": 0}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared_d, shared_s = docs[a] & docs[b], sents[a] & sents[b]
            if shared_d:
                raise ValueError(f"{len(shared_d)} document(s) appear in both {a} and {b}")
            if shared_s:
                raise ValueError(f"{len(shared_s)} sentence(s) appear in both {a} and {b}")
    return report


def write_jsonl(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return sha256_file(path)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def load_heldout(dataset_dir: Path, split: str = "heldout_test") -> tuple[list[dict], dict]:
    """Load a split and verify it against the frozen checksum in DATASET_CARD.json."""
    card = json.loads((dataset_dir / "DATASET_CARD.json").read_text(encoding="utf-8"))
    entry = card["files"][split]
    path = dataset_dir / entry["file"]
    actual = sha256_file(path)
    if actual != entry["sha256"]:
        raise ValueError(f"{path} changed since it was frozen (sha256 {actual[:12]} != {entry['sha256'][:12]}); "
                         "an evaluation set must not be edited — build a new versioned set instead")
    rows = read_jsonl(path)
    if any(r.get("split") != split for r in rows):
        raise ValueError(f"{path} contains rows from another split")
    return rows, card


# ---------------------------------------------------------- spoken (video) references
TEMPLATE_FIELDS = ["id", "split", "video_id", "segment_index", "start_ms", "end_ms", "source_en",
                   "machine_km_do_not_copy", "reference_km", "translator", "notes"]


def assign_video_split(video_id: str, heldout_fraction: float = 0.5, salt: str = "khmerlive-eval-v1") -> str:
    """Deterministic whole-video split: the same video always lands in the same split."""
    bucket = int(hashlib.sha256((salt + video_id).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "heldout_test" if bucket < heldout_fraction else "prompt_dev"


def video_template_rows(video_id: str, segments: list[dict], heldout_fraction: float = 0.5) -> list[dict]:
    split = assign_video_split(video_id, heldout_fraction)
    return [{"id": f"video-{video_id[:8]}-{i + 1:04d}", "split": split, "video_id": video_id, "segment_index": i,
             "start_ms": s.get("start_ms"), "end_ms": s.get("end_ms"), "source_en": s.get("source", ""),
             "machine_km_do_not_copy": s.get("machine") or "", "reference_km": "", "translator": "", "notes": ""}
            for i, s in enumerate(segments) if (s.get("source") or "").strip()]


def video_rows_from_template(csv_text: str) -> list[dict]:
    """Rows a translator completed. Unfilled or copied-from-machine references are rejected."""
    rows, problems = [], []
    for r in csv.DictReader(csv_text.splitlines()):
        ref, src = normalize_text(r.get("reference_km", "")), normalize_text(r.get("source_en", ""))
        if not ref:
            continue   # not translated yet
        if ref == normalize_text(r.get("machine_km_do_not_copy", "")):
            problems.append(f"{r['id']}: reference is identical to the machine output (would bias toward E0)")
            continue
        if not any("ក" <= c <= "៿" for c in ref):
            problems.append(f"{r['id']}: reference has no Khmer script")
            continue
        rows.append({"id": r["id"], "split": r["split"], "doc_id": "video-" + r["video_id"][:12],
                     "domain": "video", "topic": "", "source_lang": "en", "target_lang": "km",
                     "source": src, "reference": ref, "start_ms": int(r["start_ms"] or 0),
                     "end_ms": int(r["end_ms"] or 0), "translator": r.get("translator", ""),
                     "corpus": "khmerlive-video", "corpus_split": r["split"]})
    if problems:
        raise ValueError("Template has invalid references:\n" + "\n".join(problems[:20]))
    return rows


# ----------------------------------------------------------------------- scoring
def estimated_duration_ms(source: str, words_per_second: float = 2.5) -> int:
    """Text-only sets have no timestamps; give the LLM a typical speaking-rate budget."""
    return max(1000, int(len(source.split()) / words_per_second * 1000))


def number_fidelity(sources: list[str], hyps: list[str]) -> dict:
    """Share of sentences whose source digits all appear in the hypothesis, and invented numbers."""
    from app.llm_postedit import numbers_in
    with_numbers = kept = invented = 0
    for s, h in zip(sources, hyps, strict=True):
        src, out = numbers_in(s), numbers_in(h)
        if src:
            with_numbers += 1
            kept += src <= out
        invented += bool(out - src)
    return {"sentences_with_numbers": with_numbers,
            "all_numbers_kept": kept,
            "all_numbers_kept_rate": round(kept / with_numbers, 4) if with_numbers else None,
            "sentences_with_invented_numbers": invented}


def sentence_chrf(hyps: list[str], refs: list[str]) -> list[float]:
    from sacrebleu.metrics import CHRF
    m = CHRF(word_order=2)
    return [m.sentence_score(h, [r]).score for h, r in zip(hyps, refs, strict=True)]


def paired_stats(a: list[float], b: list[float], n_boot: int = 2000, seed: int = 13) -> dict:
    """Sentence-level paired comparison of b against a: mean delta, bootstrap 95% CI, Cohen's dz,
    and win/tie/loss counts. Complements sacrebleu's corpus-level paired tests."""
    import numpy as np
    d = np.asarray(b, float) - np.asarray(a, float)
    rng = np.random.default_rng(seed)
    boots = d[rng.integers(0, len(d), size=(n_boot, len(d)))].mean(axis=1)
    sd = d.std(ddof=1) if len(d) > 1 else 0.0
    return {"n": int(len(d)), "mean_delta": round(float(d.mean()), 3),
            "ci95": [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)],
            "cohens_dz": round(float(d.mean() / sd), 3) if sd > 0 else None,
            "wins": int((d > 1e-9).sum()), "ties": int((abs(d) <= 1e-9).sum()), "losses": int((d < -1e-9).sum())}


def bleu_metric():
    """spBLEU with the FLORES-200 SentencePiece model when cached locally, else character BLEU.

    Plain BLEU with the 13a tokenizer is not meaningful for Khmer (no spaces between words)."""
    from sacrebleu.metrics import BLEU
    try:
        m = BLEU(tokenize="flores200")
        m.corpus_score(["ក"], [["ក"]])   # forces the tokenizer model to load
        return "spBLEU-flores200", m
    except Exception:   # model not cached and offline
        return "charBLEU", BLEU(tokenize="char")


def corpus_scores(systems: dict[str, list[str]], refs: list[str], n_boot: int = 1000, seed: int = 13) -> dict:
    """Corpus chrF++ and BLEU per system, with sacrebleu paired bootstrap (95% CI) and
    approximate-randomization p-values of every system against the first (baseline)."""
    import numpy as np
    from sacrebleu.metrics import CHRF
    from sacrebleu.significance import PairedTest
    bleu_name, bleu = bleu_metric()
    metrics = {"chrF++": CHRF(word_order=2), bleu_name: bleu}
    named = list(systems.items())
    out = {"bleu_variant": bleu_name, "systems": {}, "signatures": {}}
    np.random.seed(seed)   # sacrebleu's resampling uses numpy's global RNG
    sigs, bs = PairedTest(named, metrics, [refs], test_type="bs", n_samples=n_boot)()
    np.random.seed(seed)
    _, ar = PairedTest(named, metrics, [refs], test_type="ar", n_samples=10000)()
    out["signatures"] = {k: str(v) for k, v in sigs.items()}
    # Results are keyed by sacrebleu's display names (e.g. "chrF2++") in the order of `metrics`.
    bs_keys = [k for k in bs if k != "System"]
    ar_keys = [k for k in ar if k != "System"]
    if len(bs_keys) != len(metrics) or len(ar_keys) != len(metrics):
        raise RuntimeError(f"Unexpected sacrebleu PairedTest result keys: {list(bs)}")
    num = lambda v: None if v is None else round(float(v), 4)
    for metric, kb, ka in zip(metrics, bs_keys, ar_keys):
        for i, (name, _) in enumerate(named):
            r_bs, r_ar = bs[kb][i], ar[ka][i]
            entry = out["systems"].setdefault(name, {})
            entry[metric] = {"score": round(float(r_bs.score), 2), "bootstrap_mean": round(float(r_bs.mean), 2),
                             "ci95_halfwidth": round(float(r_bs.ci), 2),
                             "p_value_vs_baseline_bs": None if i == 0 else num(r_bs.p_value),
                             "p_value_vs_baseline_ar": None if i == 0 else num(r_ar.p_value)}
    return out


# ----------------------------------------------------------------- human evaluation
HUMAN_FIELDS = ["item", "english", "khmer_output", "adequacy_1to5", "fluency_1to5",
                "added_content_yes_no", "missing_content_yes_no", "comment"]


def human_eval_pack(rows: list[dict], systems: dict[str, list[str]], n: int = 100, seed: int = 13):
    """Blind direct-assessment sheet: n random sentences, each distinct system output rated once,
    shuffled so raters cannot tell which system produced it. Returns (sheet_rows, key)."""
    rng = random.Random(seed)
    picked = sorted(rng.sample(range(len(rows)), min(n, len(rows))))
    sheet, key = [], {"seed": seed, "sample_indices": picked, "items": {}}
    for idx in picked:
        outputs: dict[str, list[str]] = {}
        for name, hyps in systems.items():
            outputs.setdefault(hyps[idx], []).append(name)
        for text, names in outputs.items():
            sheet.append({"english": rows[idx]["source"], "khmer_output": text, "_systems": names, "_row": rows[idx]["id"]})
    rng.shuffle(sheet)
    for i, s in enumerate(sheet, 1):
        item = f"H{i:04d}"
        key["items"][item] = {"row_id": s.pop("_row"), "systems": s.pop("_systems")}
        s.update(item=item, adequacy_1to5="", fluency_1to5="", added_content_yes_no="",
                 missing_content_yes_no="", comment="")
    return [{k: s[k] for k in HUMAN_FIELDS} for s in sheet], key
