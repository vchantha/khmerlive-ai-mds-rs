"""Held-out evaluation set: splits, leakage checks, immutability, scoring helpers, human-eval blinding."""
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
import pytest
from app import evaluation as ev

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
BUILDER = ROOT / "scripts/build-eval-set.py"
# The API image contains only backend/; the builder tests run in the LLM adapter workflow (full checkout).
needs_builder = pytest.mark.skipif(not BUILDER.is_file(), reason="scripts/ not present (backend-only image)")


def test_normalize_removes_zero_width_space_and_collapses():
    assert ev.normalize_text("  ខ្ញុំ​ទៅ   ផ្សារ﻿ ") == "ខ្ញុំទៅ ផ្សារ"


def test_source_key_ignores_case_space_punctuation():
    assert ev.source_key("Hello,  World!") == ev.source_key("hello world")
    assert ev.source_key("Hello world") != ev.source_key("Hello word")


META = "URL\tdomain\ttopic\thas_image\thas_hyperlink\n"


def _meta(urls):
    return META + "".join(f"{u}\twikinews\tt\tno\tno\n" for u in urls)


def test_flores_rows_use_article_as_document():
    rows = ev.flores_rows(["A one.", "A two.", "B one."], ["ក", "ខ", "គ"], _meta(["u/a", "u/a", "u/b"]), "heldout_test", "devtest")
    assert rows[0]["doc_id"] == rows[1]["doc_id"] != rows[2]["doc_id"]
    assert rows[0]["id"] == "flores200-devtest-0001" and rows[0]["split"] == "heldout_test"


def test_flores_rows_reject_misaligned_files():
    with pytest.raises(ValueError, match="line counts"):
        ev.flores_rows(["a", "b"], ["ក"], _meta(["u", "u"]), "heldout_test", "devtest")


def _row(i, doc, src, split):
    return {"id": i, "doc_id": doc, "source": src, "split": split}


def test_leakage_shared_document_rejected():
    with pytest.raises(ValueError, match="document"):
        ev.check_leakage({"prompt_dev": [_row(1, "d1", "a", "prompt_dev")], "heldout_test": [_row(2, "d1", "b", "heldout_test")]})


def test_leakage_shared_sentence_rejected():
    with pytest.raises(ValueError, match="sentence"):
        ev.check_leakage({"prompt_dev": [_row(1, "d1", "Same text.", "prompt_dev")],
                          "heldout_test": [_row(2, "d2", "same text", "heldout_test")]})


def test_leakage_clean_report():
    rep = ev.check_leakage({"prompt_dev": [_row(1, "d1", "a", "prompt_dev")], "heldout_test": [_row(2, "d2", "b", "heldout_test")]})
    assert rep["shared_documents"] == 0 and rep["sentences"] == {"heldout_test": 1, "prompt_dev": 1}


def _fake_flores(tmp_path):
    files = {"dev/eng_Latn.dev": "Dev one.\nDev two.\n", "dev/khm_Khmr.dev": "ក​ខ\nគ\n",
             "devtest/eng_Latn.devtest": "Test 12 one.\nTest two.\n", "devtest/khm_Khmr.devtest": "ឃ 12\nង\n",
             "metadata_dev.tsv": _meta(["u/d1", "u/d1"]), "metadata_devtest.tsv": _meta(["u/t1", "u/t2"])}
    tar = tmp_path / "flores.tar.gz"
    with tarfile.open(tar, "w:gz") as tf:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo("./flores200_dataset/" + name); info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return tar


def _builder(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("build_eval_set", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    return mod


@needs_builder
def test_builder_freezes_set_and_refuses_overwrite(monkeypatch, tmp_path):
    mod = _builder(monkeypatch, tmp_path)
    tar = _fake_flores(tmp_path)
    args = lambda **kw: type("A", (), dict(tarball=str(tar), name="t1", exclude=[], allow_other_tarball=True, **kw))
    mod.cmd_flores(args())
    out = tmp_path / "benchmarks/private/eval/t1"
    card = json.loads((out / "DATASET_CARD.json").read_text())
    assert card["files"]["heldout_test"]["rows"] == 2 and card["files"]["prompt_dev"]["rows"] == 2
    assert card["leakage_check"]["shared_documents"] == 0
    rows, _ = ev.load_heldout(out)
    assert rows[0]["reference"] == "ឃ 12"
    dev, _ = ev.load_heldout(out, "prompt_dev")
    assert dev[0]["reference"] == "កខ"   # zero-width space removed
    assert len((out / "eval_source_keys.txt").read_text().split()) == 4
    with pytest.raises(SystemExit):
        mod.cmd_flores(args())


@needs_builder
def test_builder_rejects_unpinned_tarball(monkeypatch, tmp_path):
    mod = _builder(monkeypatch, tmp_path)
    tar = _fake_flores(tmp_path)
    with pytest.raises(SystemExit, match="pinned"):
        mod.cmd_flores(type("A", (), dict(tarball=str(tar), name="t2", exclude=[], allow_other_tarball=False)))


@needs_builder
def test_builder_excludes_training_sentences(monkeypatch, tmp_path):
    mod = _builder(monkeypatch, tmp_path)
    tar = _fake_flores(tmp_path)
    train = tmp_path / "corrections.jsonl"
    train.write_text(json.dumps({"source": "test two", "target": "x"}) + "\n")
    mod.cmd_flores(type("A", (), dict(tarball=str(tar), name="t3", exclude=[str(train)], allow_other_tarball=True)))
    rows, card = ev.load_heldout(tmp_path / "benchmarks/private/eval/t3")
    assert [r["source"] for r in rows] == ["Test 12 one."] and card["excluded_training_overlap"] == 1


@needs_builder
def test_edited_heldout_file_is_refused(monkeypatch, tmp_path):
    mod = _builder(monkeypatch, tmp_path)
    tar = _fake_flores(tmp_path)
    mod.cmd_flores(type("A", (), dict(tarball=str(tar), name="t4", exclude=[], allow_other_tarball=True)))
    f = tmp_path / "benchmarks/private/eval/t4/heldout_test.jsonl"
    f.write_text(f.read_text().replace("ឃ 12", "ឃ 13"))
    with pytest.raises(ValueError, match="changed since it was frozen"):
        ev.load_heldout(f.parent)


# ---- spoken video references -------------------------------------------
def test_video_split_is_whole_video_and_deterministic():
    rows = ev.video_template_rows("job-abc", [{"source": "a", "machine": "ក"}, {"source": "b", "machine": "ខ"}, {"source": " "}])
    assert len(rows) == 2 and len({r["split"] for r in rows}) == 1
    assert ev.assign_video_split("job-abc") == rows[0]["split"]


def _csv(rows):
    import csv
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=ev.TEMPLATE_FIELDS); w.writeheader(); w.writerows(rows)
    return buf.getvalue()


def test_video_import_skips_blank_and_rejects_copied_machine_output():
    base = ev.video_template_rows("job-1", [{"source": "Hello", "machine": "សួស្តី", "start_ms": 0, "end_ms": 900},
                                            {"source": "Bye", "machine": "លា", "start_ms": 900, "end_ms": 1500}])
    base[0]["reference_km"] = "សួស្តីបាទ"
    rows = ev.video_rows_from_template(_csv(base))
    assert len(rows) == 1 and rows[0]["end_ms"] == 900 and rows[0]["doc_id"].startswith("video-")
    base[1]["reference_km"] = "លា"
    with pytest.raises(ValueError, match="identical to the machine"):
        ev.video_rows_from_template(_csv(base))


def test_video_import_rejects_non_khmer_reference():
    base = ev.video_template_rows("job-1", [{"source": "Hello", "machine": "សួស្តី"}])
    base[0]["reference_km"] = "hello"
    with pytest.raises(ValueError, match="no Khmer"):
        ev.video_rows_from_template(_csv(base))


# ---- scoring helpers ----------------------------------------------------
def test_number_fidelity():
    r = ev.number_fidelity(["In 2016 there were 12.", "No numbers.", "It costs 50."],
                           ["ក្នុងឆ្នាំ ២០១៦ មាន 12", "គ្មាន 7", "តម្លៃ 5"])
    assert r == {"sentences_with_numbers": 2, "all_numbers_kept": 1, "all_numbers_kept_rate": 0.5,
                 "sentences_with_invented_numbers": 2}


def test_paired_stats():
    pytest.importorskip("numpy")
    r = ev.paired_stats([10, 20, 30, 40], [12, 20, 35, 39], n_boot=500)
    assert r["wins"] == 2 and r["ties"] == 1 and r["losses"] == 1
    assert r["mean_delta"] == 1.5 and r["ci95"][0] <= 1.5 <= r["ci95"][1]


def test_estimated_duration():
    assert ev.estimated_duration_ms("one two") == 1000
    assert ev.estimated_duration_ms(" ".join(["w"] * 10)) == 4000


def test_human_eval_is_blind_and_dedupes_identical_outputs():
    rows = [{"id": f"r{i}", "source": f"s{i}"} for i in range(5)]
    systems = {"E0": ["a0", "a1", "a2", "a3", "a4"], "E1": ["a0", "b1", "b2", "a3", "b4"]}
    sheet, key = ev.human_eval_pack(rows, systems, n=5, seed=1)
    assert len(sheet) == 8   # 2 identical pairs rated once each
    assert all("E0" not in json.dumps(s) and "E1" not in json.dumps(s) for s in sheet)
    assert set(sheet[0]) == set(ev.HUMAN_FIELDS)
    shared = [v for v in key["items"].values() if v["systems"] == ["E0", "E1"]]
    assert len(shared) == 2
    again, _ = ev.human_eval_pack(rows, systems, n=5, seed=1)
    assert again == sheet   # reproducible with the seed


# ---- training never sees evaluation sentences ---------------------------
def _finetune():
    spec = importlib.util.spec_from_file_location("finetune_mt", BACKEND / "training/finetune_mt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("text", ["Hello, World!", "ខ្ញុំ​ទៅ ផ្សារ។", "  The course has 12 lessons. "])
def test_finetune_source_key_matches_evaluation(text):
    assert _finetune().source_key(text) == ev.source_key(text)


def test_finetune_drops_eval_sentences(tmp_path):
    keys = tmp_path / "eval_source_keys.txt"
    keys.write_text(ev.source_key("Held out line.") + "\n")
    rows = [{"source": "held out line", "target": "ក", "job_id": "j"}, {"source": "Train me", "target": "ខ", "job_id": "j"}]
    kept, dropped = _finetune().drop_eval_sentences(rows, [keys])
    assert dropped == 1 and [r["source"] for r in kept] == ["Train me"]
