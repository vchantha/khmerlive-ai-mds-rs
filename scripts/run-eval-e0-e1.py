#!/usr/bin/env python3
"""Run E0 (M2M100) and E1 (M2M100 + offline LLM post-edit) on a frozen held-out set.

Runs inside the worker image (scripts/run-eval-e0-e1.sh mounts everything) and uses the
production code paths: app.real_inference.load_translator for E0 and
app.llm_postedit.postedit_rows (same prompt, guards and settings as jobs) for E1.

Writes an immutable run directory under benchmarks/reports/runs/. A run with --limit is
marked partial and must not be reported as a result. The run aborts (no scores) if the
LLM server becomes unreachable or any line is skipped, because silently keeping the E0
text would bias E1 toward E0.
"""
import argparse
import csv
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")
from app import evaluation as ev  # noqa: E402
from app.config import settings  # noqa: E402


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_e0(rows):
    from app.real_inference import TimedText, load_translator
    tr = load_translator(settings.translation_model_path, settings.device_for("mt"), settings.threads_per_job(),
                         settings.mt_engine, settings.mt_ct2_path, settings.mt_beam_size)
    items = [TimedText(0, ev.estimated_duration_ms(r["source"]), r["source"]) for r in rows]
    t = time.monotonic()
    out = tr.translate(items, "en", "km")
    return out, {"engine": tr.engine, "seconds": round(time.monotonic() - t, 2), "device": settings.device_for("mt"),
                 "beam_size": settings.mt_beam_size}


def run_e1(rows, e0_items):
    from app import llm_postedit as lp
    status = lp.llm_status()
    if status["status"] != "ready":
        sys.exit(f"ERROR: LLM not ready ({status['status']}): {status.get('detail')}")
    smoke = lp.llm_smoke_test()
    if not smoke["ok"]:
        sys.exit(f"ERROR: LLM smoke test failed: {smoke['error']}")
    # The per-job time budget protects users; an experiment must finish every line instead.
    settings.llm_total_budget_seconds = 10 ** 9
    edited, report = list(e0_items), []
    # Post-edit document by document so neighbouring-line context (translate mode) never
    # crosses an article/video boundary.
    groups, start = [], 0
    for i in range(1, len(rows) + 1):
        if i == len(rows) or rows[i]["doc_id"] != rows[start]["doc_id"]:
            groups.append((start, i)); start = i
    t = time.monotonic()
    for n, (a, b) in enumerate(groups, 1):
        part = []
        out = lp.postedit_rows(e0_items[a:b], "en", "km", report=part, terms=None)
        for task in part:
            task["index"] += a
            if task["status"].startswith(("failed", "skipped")):
                sys.exit(f"ERROR: line {task['index']} {task['status']} ({task['error']}); "
                         "run aborted so unedited lines are not counted as E1")
        edited[a:b] = out
        report += part
        if n % 20 == 0 or n == len(groups):
            done = b
            rate = (time.monotonic() - t) / done
            log(f"E1 {done}/{len(rows)} lines, {rate:.2f}s/line, ~{rate * (len(rows) - done) / 60:.0f} min left")
    return edited, report, {"seconds": round(time.monotonic() - t, 2), "status": status, "smoke": smoke}


def llm_summary(report):
    counts, reasons = {}, {}
    for t in report:
        key = t["status"].split(" (")[0] if t["status"].startswith(("edited", "unchanged")) else t["status"]
        counts[key] = counts.get(key, 0) + 1
        if t.get("error"):
            r = t["error"].split(":")[0]
            reasons[r] = reasons.get(r, 0) + 1
    secs = sorted(t["seconds"] for t in report if t.get("seconds") is not None)
    lat = {"mean": round(statistics.mean(secs), 3), "median": round(statistics.median(secs), 3),
           "p95": round(secs[int(0.95 * (len(secs) - 1))], 3)} if secs else None
    n = len(report)
    return {"lines": n, "outcomes": counts, "rates": {k: round(v / n, 4) for k, v in counts.items()} if n else {},
            "rejection_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
            "latency_seconds_per_line": lat}


def ollama_digest(model):
    import httpx
    from app.llm_postedit import validate_local_endpoint
    try:
        root = validate_local_endpoint(settings.llm_base_url).removesuffix("/v1")
        with httpx.Client(timeout=5, trust_env=False) as c:
            for m in c.get(root + "/api/tags").json().get("models", []):
                if m.get("name") == model or m.get("model") == model:
                    return {"digest": m.get("digest"), "size": m.get("size"), "details": m.get("details")}
    except Exception as exc:   # provenance is best effort; recorded as unknown
        return {"error": str(exc)[:200]}
    return None


def write_report(path, cfg, scores):
    s, sys_ = scores, scores["corpus"]["systems"]
    bleu = scores["corpus"]["bleu_variant"]
    lines = [f"# E0 vs E1 — {cfg['dataset']['name']} / {cfg['dataset']['split']}", "",
             f"Run `{cfg['run_id']}` · {cfg['created_utc']} · {'**PARTIAL — not reportable**' if cfg['partial'] else 'full split'}",
             f"Lines: {s['n']} · E1: {cfg['e1']['provider']} `{cfg['e1']['model']}` prompt `{cfg['e1']['prompt_version']}` "
             f"mode `{cfg['e1']['mode']}` · E0: M2M100 ({cfg['e0']['engine']}, beam {cfg['e0']['beam_size']})", "",
             "| System | chrF++ (95% CI) | " + bleu + " (95% CI) |", "|---|---|---|"]
    for name, m in sys_.items():
        c, b = m["chrF++"], m[bleu]
        lines.append(f"| {name} | {c['score']} ± {c['ci95_halfwidth']} | {b['score']} ± {b['ci95_halfwidth']} |")
    e1c = sys_["E1"]["chrF++"]
    ps = s["sentence_chrf_paired"]
    lines += ["", f"Corpus chrF++ difference E1−E0: **{round(e1c['score'] - sys_['E0']['chrF++']['score'], 2)}** "
              f"(paired bootstrap p={e1c['p_value_vs_baseline_bs']}, approximate randomization p={e1c['p_value_vs_baseline_ar']}).",
              f"Sentence chrF++ mean delta {ps['mean_delta']} (95% CI {ps['ci95'][0]} to {ps['ci95'][1]}), "
              f"Cohen's dz {ps['cohens_dz']}; E1 better on {ps['wins']}, equal on {ps['ties']}, worse on {ps['losses']}.", "",
              "## By domain (corpus chrF++)", "", "| Domain | n | E0 | E1 |", "|---|---|---|---|"]
    for d, v in s["by_domain"].items():
        lines.append(f"| {d} | {v['n']} | {v['E0']} | {v['E1']} |")
    nf = s["number_fidelity"]
    lines += ["", "## Numbers (source digits kept in output)", "",
              f"E0 {nf['E0']['all_numbers_kept_rate']} · E1 {nf['E1']['all_numbers_kept_rate']} "
              f"of {nf['E0']['sentences_with_numbers']} sentences with numbers; invented numbers: "
              f"E0 {nf['E0']['sentences_with_invented_numbers']}, E1 {nf['E1']['sentences_with_invented_numbers']}.", "",
              "## LLM outcomes", "", "```json", json.dumps(s["llm"], ensure_ascii=False, indent=2), "```", "",
              "## Limitations", ""] + [f"- {x}" for x in cfg["dataset"]["limitations"]] + [
              "- Automatic metrics with one reference are not a quality verdict; score human_eval_sheet.csv "
              "(blind; the key is in human_eval_key.json) before drawing conclusions for RQ1.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="Directory with DATASET_CARD.json")
    ap.add_argument("--split", default="heldout_test", choices=["heldout_test", "prompt_dev"])
    ap.add_argument("--limit", type=int, default=0, help="First N lines only (smoke run; marked partial)")
    ap.add_argument("--human-n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--reports", default="/bench/reports/runs")
    a = ap.parse_args()

    dataset = Path(a.dataset)
    rows, card = ev.load_heldout(dataset, a.split)
    partial = bool(a.limit and a.limit < len(rows))
    if partial:
        rows = rows[:a.limit]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-{card['name']}-{a.split}" + ("-partial" if partial else "")
    final = Path(a.reports) / run_id
    if final.exists():
        sys.exit(f"ERROR: {final} exists")
    # Written under .incomplete and renamed only after every file is complete, so an
    # aborted run can never be mistaken for a result.
    out = final.with_name(run_id + ".incomplete")
    out.mkdir(parents=True, exist_ok=False)
    log(f"{len(rows)} lines from {card['name']}/{a.split} -> {out}")

    log("E0: M2M100")
    e0_items, e0_info = run_e0(rows)
    log(f"E0 done in {e0_info['seconds']}s ({e0_info['engine']})")
    log("E1: LLM post-editing of the E0 output")
    e1_items, report, e1_info = run_e1(rows, e0_items)

    refs = [r["reference"] for r in rows]
    e0 = [ev.normalize_text(x.target_text) for x in e0_items]
    e1 = [ev.normalize_text(x.target_text) for x in e1_items]
    for x, y in zip(e0_items, e1_items):
        assert (x.start_ms, x.end_ms, x.source_text) == (y.start_ms, y.end_ms, y.source_text)
    log("Scoring (paired bootstrap + approximate randomization)")
    systems = {"E0": e0, "E1": e1}
    by_domain = {}
    from sacrebleu.metrics import CHRF
    for d in sorted({r["domain"] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r["domain"] == d]
        by_domain[d] = {"n": len(idx), **{k: round(CHRF(word_order=2).corpus_score([v[i] for i in idx], [[refs[i] for i in idx]]).score, 2)
                                         for k, v in systems.items()}}
    s0, s1 = ev.sentence_chrf(e0, refs), ev.sentence_chrf(e1, refs)
    scores = {"n": len(rows), "corpus": ev.corpus_scores(systems, refs, seed=a.seed),
              "sentence_chrf_paired": ev.paired_stats(s0, s1, seed=a.seed), "by_domain": by_domain,
              "number_fidelity": {k: ev.number_fidelity([r["source"] for r in rows], v) for k, v in systems.items()},
              "identical_outputs": sum(x == y for x, y in zip(e0, e1)), "llm": llm_summary(report),
              "wall_seconds": {"E0": e0_info["seconds"], "E1_llm_only": e1_info["seconds"]}}

    try:
        manifest = json.loads(Path(settings.whisper_model_path).parent.joinpath("manifest.lock.json").read_text())
        models = {m["component"]: {"id": m.get("id"), "revision": m.get("revision")} for m in manifest.get("models", [])}
    except (OSError, ValueError, KeyError):
        models = None
    from app.llm_postedit import prompt_version, SYSTEM_PROMPT, TRANSLATE_PROMPT
    import sacrebleu
    cfg = {"run_id": run_id, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "partial": partial, "git_commit": os.getenv("GIT_COMMIT", "unknown"), "seed": a.seed,
           "dataset": {"name": card["name"], "split": a.split, "sha256": card["files"][a.split]["sha256"],
                       "rows_used": len(rows), "limitations": card.get("limitations", [])},
           "e0": {**e0_info, "models": models},
           "e1": {"provider": settings.llm_provider, "model": settings.llm_model, "mode": settings.llm_mode,
                  "prompt_version": prompt_version(),
                  "prompt": TRANSLATE_PROMPT if settings.llm_mode == "translate" else SYSTEM_PROMPT,
                  "temperature": 0, "max_tokens": settings.llm_max_tokens, "concurrency": settings.llm_concurrency,
                  "retries": settings.llm_max_retries, "glossary": "disabled (isolates the LLM effect)",
                  "duration_budget": "estimated 2.5 words/s (text set has no timestamps)",
                  "ollama_model": ollama_digest(settings.llm_model) if settings.llm_provider == "ollama" else None,
                  "smoke_test": e1_info["smoke"]},
           "software": {"python": platform.python_version(), "sacrebleu": sacrebleu.__version__},
           "text_normalization": "NFC, U+200B/U+FEFF removed, whitespace collapsed (hypotheses and references)"}
    try:
        import torch
        cfg["hardware"] = {"cuda": torch.cuda.is_available(),
                           "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}
    except Exception:
        pass

    with open(out / "hypotheses.jsonl", "w", encoding="utf-8") as fh:
        for i, r in enumerate(rows):
            t = report[i] if i < len(report) and report[i]["index"] == i else next((x for x in report if x["index"] == i), {})
            fh.write(json.dumps({"id": r["id"], "doc_id": r["doc_id"], "domain": r["domain"], "source": r["source"],
                                 "reference": r["reference"], "E0": e0[i], "E1": e1[i], "chrf_E0": round(s0[i], 2),
                                 "chrf_E1": round(s1[i], 2), "e1_status": t.get("status"), "e1_error": t.get("error"),
                                 "e1_seconds": t.get("seconds")}, ensure_ascii=False) + "\n")
    sheet, key = ev.human_eval_pack(rows, systems, n=a.human_n, seed=a.seed)
    with open(out / "human_eval_sheet.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=ev.HUMAN_FIELDS); w.writeheader(); w.writerows(sheet)
    (out / "human_eval_key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    (out / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(out / "REPORT.md", cfg, scores)
    for f in out.iterdir():
        f.chmod(0o444)   # immutable research output
    out.rename(final)
    log(f"Done: {final}")
    print((final / "REPORT.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
