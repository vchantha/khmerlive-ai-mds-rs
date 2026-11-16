"""LoRA fine-tuning of the M2M100 translation model on human-verified subtitle lines.

Input: the JSONL from GET /api/dataset/corrections?format=jsonl (source -> target).
Steps: split by video (no leakage) -> score the base model on held-out lines (chrF++)
-> LoRA training -> score again -> if better, merge and convert to CTranslate2.
Writes <out>/report.json; the wrapper scripts/finetune-mt.sh decides whether to deploy.
"""
import argparse, hashlib, json, math, random, shutil, sys, time
from pathlib import Path


def load_pairs(path, src, dst):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("source_lang") == src and r.get("target_lang") == dst and r.get("source") and r.get("target"):
            rows.append(r)
    return rows


def source_key(text):
    """Same as app.evaluation.source_key (kept in sync by tests/test_evaluation.py)."""
    import re, unicodedata
    t = " ".join(unicodedata.normalize("NFC", text or "").translate({0x200B: None, 0xFEFF: None}).split()).lower()
    t = re.sub(r"[^\w\s]", "", t)
    return hashlib.sha256(" ".join(t.split()).encode()).hexdigest()[:16]


def drop_eval_sentences(rows, key_files):
    """Never train on evaluation sentences (eval_source_keys.txt from scripts/build-eval-set.py)."""
    keys = set()
    for f in key_files:
        keys |= {k.strip() for k in Path(f).read_text(encoding="utf-8").splitlines() if k.strip()}
    kept = [r for r in rows if source_key(r["source"]) not in keys]
    return kept, len(rows) - len(kept)


def split_by_video(rows, dev_frac, seed):
    """Whole videos go to dev, so the score reflects unseen content."""
    jobs = sorted({r["job_id"] for r in rows})
    random.Random(seed).shuffle(jobs)
    dev, n = set(), 0
    for j in jobs:
        if n >= len(rows) * dev_frac:
            break
        dev.add(j); n += sum(1 for r in rows if r["job_id"] == j)
    if len(jobs) == 1 or not dev:   # single video: fall back to a line split
        idx = list(range(len(rows))); random.Random(seed).shuffle(idx)
        k = max(1, int(len(rows) * dev_frac)); devi = set(idx[:k])
        return [r for i, r in enumerate(rows) if i not in devi], [r for i, r in enumerate(rows) if i in devi]
    return [r for r in rows if r["job_id"] not in dev], [r for r in rows if r["job_id"] in dev]


def translate(model, tok, texts, dst, device, beams=4, bs=16):
    import torch
    out = []
    model.eval()
    for i in range(0, len(texts), bs):
        enc = tok(texts[i:i + bs], return_tensors="pt", padding=True, truncation=True, max_length=256).to(device)
        with torch.inference_mode():
            gen = model.generate(**enc, forced_bos_token_id=tok.get_lang_id(dst), num_beams=beams, max_new_tokens=256,
                                 no_repeat_ngram_size=3, repetition_penalty=1.2)
        out += [t.strip() for t in tok.batch_decode(gen, skip_special_tokens=True)]
    return out


def chrf(hyps, refs):
    from sacrebleu.metrics import CHRF
    return round(CHRF(word_order=2).corpus_score(hyps, [refs]).score, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="/models/mt")
    ap.add_argument("--out", default="/models/mt-ft")
    ap.add_argument("--src", default="en"); ap.add_argument("--dst", default="km")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--dev-frac", type=float, default=0.15)
    ap.add_argument("--min-pairs", type=int, default=100)
    ap.add_argument("--min-gain", type=float, default=1.0, help="chrF++ points required to recommend deploying")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--exclude-keys", action="append", default=[],
                    help="eval_source_keys.txt of a held-out evaluation set; its sentences are removed")
    a = ap.parse_args()

    import torch
    from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
    from peft import LoraConfig, get_peft_model
    torch.manual_seed(a.seed); random.seed(a.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    rows = load_pairs(a.data, a.src, a.dst)
    rows, dropped = drop_eval_sentences(rows, a.exclude_keys)
    if a.exclude_keys:
        print(f"Removed {dropped} line(s) that belong to a held-out evaluation set", flush=True)
    print(f"{len(rows)} verified {a.src}->{a.dst} pairs from {len({r['job_id'] for r in rows})} video(s)", flush=True)
    if len(rows) < a.min_pairs:
        sys.exit(f"Need at least {a.min_pairs} verified lines (have {len(rows)}). Review more videos first.")
    train, dev = split_by_video(rows, a.dev_frac, a.seed)
    print(f"train {len(train)} / held-out {len(dev)} lines · device {device}", flush=True)

    tok = M2M100Tokenizer.from_pretrained(a.base, local_files_only=True)
    tok.src_lang, tok.tgt_lang = a.src, a.dst
    model = M2M100ForConditionalGeneration.from_pretrained(a.base, local_files_only=True).to(device)
    dev_src, dev_ref = [r["source"] for r in dev], [r["target"] for r in dev]
    t0 = time.monotonic()
    base_hyp = translate(model, tok, dev_src, a.dst, device)
    base_score = chrf(base_hyp, dev_ref)
    print(f"base model chrF++ on held-out lines: {base_score} ({time.monotonic()-t0:.0f}s)", flush=True)

    model = get_peft_model(model, LoraConfig(r=a.lora_r, lora_alpha=a.lora_r * 2, lora_dropout=0.05,
                                             target_modules=["q_proj", "k_proj", "v_proj", "out_proj", "fc1", "fc2"]))
    model.print_trainable_parameters()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.01)
    steps = math.ceil(len(train) / a.batch) * a.epochs
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / max(1, steps // 10)) * max(0.0, 1 - s / steps))
    scaler = torch.amp.GradScaler(enabled=device == "cuda")
    model.train(); step = 0; t0 = time.monotonic()
    for ep in range(a.epochs):
        random.shuffle(train); total = 0.0
        for i in range(0, len(train), a.batch):
            b = train[i:i + a.batch]
            enc = tok([r["source"] for r in b], text_target=[r["target"] for r in b], return_tensors="pt",
                      padding=True, truncation=True, max_length=128).to(device)
            enc["labels"][enc["labels"] == tok.pad_token_id] = -100
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=device == "cuda"):
                loss = model(**enc).loss
            scaler.scale(loss).backward(); scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt); scaler.update(); opt.zero_grad(); sched.step()
            total += loss.item(); step += 1
        print(f"epoch {ep+1}/{a.epochs} loss {total / math.ceil(len(train) / a.batch):.3f} ({time.monotonic()-t0:.0f}s)", flush=True)

    model = model.merge_and_unload()
    ft_hyp = translate(model, tok, dev_src, a.dst, device)
    ft_score = chrf(ft_hyp, dev_ref)
    gain = round(ft_score - base_score, 2)
    print(f"fine-tuned chrF++ on held-out lines: {ft_score} (change {gain:+})", flush=True)

    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    model.save_pretrained(out, safe_serialization=False)
    tok.save_pretrained(out)
    report = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "pairs": len(rows), "train": len(train), "held_out": len(dev),
              "videos": len({r["job_id"] for r in rows}), "base_chrf": base_score, "finetuned_chrf": ft_score, "gain": gain,
              "recommend_deploy": gain >= a.min_gain, "min_gain": a.min_gain, "epochs": a.epochs, "lr": a.lr, "lora_r": a.lora_r,
              "data_sha256": hashlib.sha256(Path(a.data).read_bytes()).hexdigest(),
              "examples": [{"source": s, "reference": r, "base": b, "finetuned": f}
                           for s, r, b, f in list(zip(dev_src, dev_ref, base_hyp, ft_hyp))[:20]]}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ("pairs", "held_out", "base_chrf", "finetuned_chrf", "gain", "recommend_deploy")}))


if __name__ == "__main__":
    main()
