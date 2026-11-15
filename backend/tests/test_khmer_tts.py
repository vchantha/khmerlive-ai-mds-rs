from types import SimpleNamespace
from pathlib import Path
import wave
import pytest
np=pytest.importorskip("numpy",reason="NumPy is installed only in real model image")
from app.khmer_tts import require_tts_model,build_dubbed_audio,resample_to_length

def test_missing_tts_model_rejected(tmp_path):
    with pytest.raises(FileNotFoundError,match="Khmer TTS model missing"):
        require_tts_model(str(tmp_path))

def test_valid_model_layout(tmp_path):
    for name in ("config.json","vocab.json","model.safetensors"):
        (tmp_path/name).write_bytes(b"test")
    assert require_tts_model(str(tmp_path))==tmp_path

def test_dubbed_track_uses_khmer_speech_and_silence(tmp_path):
    rows=[SimpleNamespace(start_ms=500,end_ms=1500,target_text="សួស្តី")]
    def fake_synth(text):
        assert text=="សួស្តី"
        return np.full(12000,0.3,dtype=np.float32),12000
    target=tmp_path/"dub.wav"
    build_dubbed_audio(rows,target,2.0,"unused",synthesizer=fake_synth)
    with wave.open(str(target),"rb") as audio:
        assert audio.getframerate()==24000
        assert audio.getnframes()==48000
        samples=np.frombuffer(audio.readframes(48000),dtype="<i2")
    assert not np.any(samples[:10000])
    assert np.any(samples[14000:35000])
    assert not np.any(samples[40000:])

def test_extreme_speedup_fails_instead_of_unintelligible_dub():
    with pytest.raises(ValueError,match="speedup"):
        resample_to_length(np.ones(240000,dtype=np.float32),24000,24000)

def test_no_translated_speech_rejected(tmp_path):
    with pytest.raises(ValueError,match="No translated Khmer"):
        build_dubbed_audio([],tmp_path/"dub.wav",2,"unused",synthesizer=lambda _:None)

@pytest.mark.parametrize("duration",[0,-1,float("nan"),float("inf"),601])
def test_duration_guard_rejects_invalid_or_over_limit(tmp_path,duration):
    with pytest.raises(ValueError,match="Invalid video duration"):
        build_dubbed_audio([],tmp_path/"dub.wav",duration,"unused")
    assert not list(tmp_path.iterdir())

def test_long_video_profile_preserves_speech_at_end(tmp_path):
    # Regression: the reported 6643s input previously hit a separate 3600s
    # TTS cap after increasing the worker's initial duration limit.
    rows=[SimpleNamespace(start_ms=6642000,end_ms=6643000,target_text="សួស្តី")]
    target=tmp_path/"long.wav"
    build_dubbed_audio(rows,target,6643,"unused",max_duration_seconds=7200,
                      synthesizer=lambda _: (np.full(24000,0.3,dtype=np.float32),24000))
    with wave.open(str(target),"rb") as audio:
        assert audio.getnframes()==6643*24000
        assert not np.any(np.frombuffer(audio.readframes(24000),dtype="<i2"))
        audio.setpos(6642*24000)
        assert np.all(np.frombuffer(audio.readframes(24000),dtype="<i2")>9000)
    assert list(tmp_path.iterdir())==[target]

def test_overlap_normalizes_and_cleans_temporary_track(tmp_path):
    rows=[SimpleNamespace(start_ms=0,end_ms=1000,target_text="សួស្តី")]*2
    target=tmp_path/"overlap.wav"
    build_dubbed_audio(rows,target,1,"unused",
                      synthesizer=lambda _: (np.ones(24000,dtype=np.float32),24000))
    with wave.open(str(target),"rb") as audio:
        samples=np.frombuffer(audio.readframes(24000),dtype="<i2")
        assert np.all(samples==int(0.95*32767))
    assert list(tmp_path.iterdir())==[target]
