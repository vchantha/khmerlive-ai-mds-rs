# Held-out evaluation: E0 (M2M100) vs E1 (M2M100 + offline LLM post-edit)

This answers **RQ1** (*does offline LLM post-editing improve English→Khmer translation?*)
with a frozen held-out set, the production code paths, paired significance tests and a
blind human-rating sheet. Automatic scores alone are not the answer to RQ1; the human
ratings are.

## 1. Evaluation sets

| Set | Source | Split unit | Status |
| --- | --- | --- | --- |
| `flores200-en-km-v1` | FLORES-200 eng_Latn↔khm_Khmr, professional human translations (CC BY-SA 4.0) | Wikipedia article | **Built** — `heldout_test` 1012 sentences / 281 articles; `prompt_dev` 997 / 281 |
| `video-en-km-v1` | Your completed jobs, references written by a Khmer translator | Whole video | **Tooling ready, no references yet** |

- **heldout_test** is frozen: its sha256 is in `DATASET_CARD.json` and checked before
  every run. Report final E0/E1 numbers on it only.
- **prompt_dev** is for prompt and setting development. Never tune on `heldout_test`.
- The builder fails if any article/video or sentence (case/punctuation-insensitive) is
  shared between splits; the first build found 0 shared articles and 0 shared sentences.
- Sentences found in training data (`--exclude <corrections export>.jsonl`) are removed,
  and `scripts/finetune-mt.sh` passes every set's `eval_source_keys.txt` to the MT LoRA
  trainer, which removes those sentences (RQ2/E3 must not train on evaluation data).
- Text is normalized identically for references and hypotheses: NFC, zero-width space
  (U+200B, present throughout the FLORES Khmer references) removed, whitespace collapsed.
- Sets live in `benchmarks/private/eval/` (git-ignored). Do not commit FLORES text: CC BY-SA
  requires attribution and share-alike, and the repository is public.

### Build

```bash
# once, on a connected machine (pinned sha256 b8b0b767…11f6 is verified by the builder)
curl -fL -o benchmarks/private/downloads/flores200_dataset.tar.gz \
     https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz
# spBLEU tokenizer model, so scoring runs offline
mkdir -p benchmarks/private/sacrebleu/models
curl -fL -o benchmarks/private/sacrebleu/models/flores200sacrebleuspm https://tinyurl.com/flores200sacrebleuspm

python3 scripts/build-eval-set.py flores --tarball benchmarks/private/downloads/flores200_dataset.tar.gz
```

An existing set is never overwritten; build a new version with `--name …-v2`.

### Spoken-video references (in-domain; strongly recommended for the thesis)

FLORES is written text. To evaluate dubbing speech, export your own English videos:

```bash
python3 scripts/build-eval-set.py video-template --job <job-id> --job <job-id> ...
```

Each whole video goes to `heldout_test` or `prompt_dev` by a deterministic hash. A bilingual
translator fills `reference_km` **from the English** (`machine_km_do_not_copy` is shown only
for context; a reference identical to it is rejected because it would bias the test toward
E0). Then freeze it:

```bash
python3 scripts/build-eval-set.py video-import --csv benchmarks/private/eval/video-template.csv
./scripts/run-eval-e0-e1.sh --dataset /bench/private/eval/video-en-km-v1
```

Aim for ≥ 300 held-out lines from ≥ 10 videos and several speakers; use rights-cleared videos.

## 2. Running E0 vs E1

```bash
./scripts/run-eval-e0-e1.sh --limit 40     # smoke run, marked PARTIAL — not reportable
./scripts/run-eval-e0-e1.sh                # full held-out test
```

- **E0** = `app.real_inference.load_translator` with the job settings (M2M100 418M,
  CTranslate2 int8, beam `MT_BEAM_SIZE`).
- **E1** = `app.llm_postedit.postedit_rows` on the E0 output: the same prompt, output guards
  and fallback as jobs. The glossary is disabled to isolate the LLM's effect. Text sets
  have no timestamps, so E1 receives an estimated duration budget (2.5 words/s).
- The run first requires the LLM `ready` status **and** a passing smoke inference.
- The per-job LLM time budget is lifted so every line is post-edited. If the server
  becomes unreachable or any line is skipped, the run aborts without scores, because
  keeping E0 text would silently pull E1 toward E0.
- Lines rejected by the output guards keep the E0 text **and count as E1**: that is what
  the deployed E1 system produces. The rejection rate is reported separately.

### Output (immutable)

`benchmarks/reports/runs/<UTC>-<set>-<split>[-partial]/` is written under `.incomplete`
and renamed only when complete; files are made read-only.

| File | Content |
| --- | --- |
| `REPORT.md` | Summary table and limitations |
| `scores.json` | Corpus chrF++ and spBLEU per system with paired bootstrap 95% CI (1000 resamples) and p-values (paired bootstrap; approximate randomization, 10 000 trials); sentence-level chrF++ mean delta with bootstrap 95% CI, Cohen's dz, wins/ties/losses; per-domain chrF++; number fidelity; LLM outcome rates, rejection reasons and latency |
| `hypotheses.jsonl` | Per sentence: source, reference, E0, E1, sentence chrF++, E1 status/error/seconds |
| `config.json` | Git commit, dataset sha256, model revisions (`models/manifest.lock.json`), Ollama model digest, prompt text and `prompt_version`, LLM settings, sacrebleu signatures, seed, GPU |
| `human_eval_sheet.csv` | Blind direct-assessment sheet (default 100 random sentences) |
| `human_eval_key.json` | Which system produced each sheet item — keep it away from raters |

### Results: first full run (2026-11-16, automatic metrics only)

Run `20261116T193510Z-flores200-en-km-v1-heldout_test` · commit `baec5f4` · FLORES-200
devtest, 1012 sentences / 281 articles · E1 = Ollama `qwen3:4b-instruct`, prompt
`polish-6aad1b376d` · E0 = M2M100 418M (CTranslate2 int8, beam 4) · Quadro T1000 4 GB.

| System | chrF++ (95% CI) | spBLEU-flores200 (95% CI) |
| --- | --- | --- |
| E0 | 23.13 ± 0.46 | 4.67 ± 0.32 |
| E1 | 25.56 ± 0.53 | 7.01 ± 0.43 |

- Corpus chrF++ E1−E0 = **+2.43** (paired bootstrap p = 0.001; approximate randomization
  p = 0.0001, 10 000 trials).
- Sentence chrF++ mean delta +2.47 (95% CI 2.14 to 2.78), Cohen's dz = 0.47; E1 better on
  702, equal on 19, worse on 291 sentences.
- By domain (corpus chrF++ E0 → E1): wikibooks 21.98 → 24.91 (n = 351), wikinews
  24.52 → 26.52 (n = 341), wikivoyage 22.40 → 24.86 (n = 320).
- Number fidelity (196 sentences with digits): all numbers kept E0 92.9% → E1 96.9%;
  sentences with invented numbers E0 56, E1 50 (upper bound, see §3).
- LLM outcomes: edited 994 (98.2%), unchanged 2 (0.2%), rejected by output guards and kept
  E0 text 16 (1.6%): changed/dropped number 8, introduced number 5, mostly Latin script 3.
- Latency: E1 mean 8.7 s/line (median 8.5, p95 14.1) on the T1000; E0 668 s for all 1012
  lines on CPU.

**Status of this result.** One E1 run with `LLM_CONCURRENCY` > 1, so it is not
bit-reproducible; repeat E1 at least twice more (or once with `LLM_CONCURRENCY=1`) before
reporting it as final. The blind human-rating sheet (198 items from 100 sentences) has
been generated but **not yet rated**: these automatic scores do not answer RQ1 on their
own. Domain mismatch and possible FLORES contamination (§4) apply. Per-sentence outputs,
full scores and configuration are in the run folder (git-ignored, read-only).

## 3. Metrics and their limits for Khmer

- **chrF++** (primary): character n-grams handle unspaced Khmer script reasonably.
- **spBLEU (FLORES-200 SentencePiece)**: BLEU with the standard `13a` tokenizer is
  meaningless for Khmer (no spaces between words). Falls back to character BLEU, recorded
  as `charBLEU`, if the tokenizer model is missing.
- **Number fidelity**: share of sentences whose source digits all appear in the output
  (Khmer digits count). "Invented" also counts a digit written for a spelled-out English
  number ("two" → "2"), so treat it as an upper bound on hallucinated numbers.
- One reference per sentence: a valid paraphrase scores low. Automatic metrics
  rank systems; they do not certify quality.
- **Human evaluation** (required for RQ1): bilingual raters score each sheet row for
  adequacy 1–5 (meaning preserved versus the English), fluency 1–5 (natural spoken Khmer),
  added content (hallucination) and missing content (omission). Sheet rows are shuffled and
  unlabeled; an output that E0 and E1 share is rated once and credited to both. Use ≥ 2
  raters on a common subset and report agreement (e.g. Krippendorff's α).
- **Reproducibility**: E0 is deterministic. E1 uses temperature 0, but Ollama batching
  with `LLM_CONCURRENCY` > 1 is not bit-for-bit deterministic. A 40-line smoke run repeated
  twice differed in one guard rejection. Report at least 3 E1 runs, or run with
  `LLM_CONCURRENCY=1` for the reported numbers.

## 4. Known threats to validity

1. Domain: FLORES is Wikipedia prose, longer and more formal than dubbing lines.
2. Contamination: FLORES is public. Qwen3 may have seen it; M2M100's training data is
   CCMatrix/CCAligned and not FLORES devtest, but overlap cannot be ruled out.
3. ASR is not involved in text sets. In the video set, ASR errors affect E0 and E1 equally.
4. The E1 prompt was written before this set existed and has not been tuned on it. Keep it
   that way: any change must be developed on `prompt_dev` and gets a new `prompt_version`.
