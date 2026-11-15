import pytest
from app.quality_metrics import distance,normal,corpus_error

def test_exact_match():
    assert distance(list("abc"),list("abc"))==0
    assert corpus_error(["hello world"],["hello world"],"en")["wer"]==0

def test_source_english_substitution():
    score=corpus_error(["hello there"],["hello world"],"en")
    assert score["wer"]==0.5
    assert score["cer"]>0

def test_khmer_ignores_whitespace_for_character_scoring():
    a=corpus_error(["សួស្តី ខ្មែរ"],["សួស្តីខ្មែរ"],"km")
    assert a["cer"]==0
    assert a["wer"] is None

def test_empty_references_rejected():
    with pytest.raises(ValueError):
        corpus_error(["sample"],[""],"en")
