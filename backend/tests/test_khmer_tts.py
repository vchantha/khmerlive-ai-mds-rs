from types import SimpleNamespace
from pathlib import Path
import wave
import pytest
np=pytest.importorskip("numpy",reason="NumPy is installed only in real model image")
from app.khmer_tts import require_tts_model,build_dubbed_audio

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
        assert audio.getframerate()==12000            # TTS native rate: no resampling
        assert audio.getnframes()==24000
        samples=np.frombuffer(audio.readframes(24000),dtype="<i2")
    assert not np.any(samples[:5900])
    assert np.any(samples[7000:17000])
    assert not np.any(samples[18100:])

def test_short_line_is_not_stretched_to_fill_its_slot(tmp_path):
    # 0.5 s of speech in a 3 s subtitle slot used to be slowed 6x (deep, drawn-out voice).
    rows=[SimpleNamespace(start_ms=0,end_ms=3000,target_text="ក")]
    build_dubbed_audio(rows,tmp_path/"dub.wav",4.0,"unused",
                       synthesizer=lambda t:(np.full(8000,0.3,dtype=np.float32),16000))
    with wave.open(str(tmp_path/"dub.wav"),"rb") as audio:
        samples=np.frombuffer(audio.readframes(audio.getnframes()),dtype="<i2")
    voiced=np.flatnonzero(samples)
    assert voiced[-1]<8000                          # plays at natural length, then silence

def test_lines_have_even_loudness_and_fades(tmp_path):
    rows=[SimpleNamespace(start_ms=0,end_ms=1000,target_text="quiet"),
          SimpleNamespace(start_ms=2000,end_ms=3000,target_text="loud")]
    def synth(t):
        return np.full(8000,0.03 if t=="quiet" else 0.3,dtype=np.float32),16000
    build_dubbed_audio(rows,tmp_path/"dub.wav",4.0,"unused",synthesizer=synth)
    with wave.open(str(tmp_path/"dub.wav"),"rb") as audio:
        s=np.frombuffer(audio.readframes(audio.getnframes()),dtype="<i2").astype(float)
    a,b=np.abs(s[1000:7000]).mean(),np.abs(s[33000:39000]).mean()
    assert 0.7<a/b<1.4                              # normalised (was 10x apart)
    assert abs(s[0])<abs(s[1000])                   # fade-in, no click

def test_long_khmer_line_uses_following_pause(tmp_path):
    # 2.4 s of speech for a 1 s English slot fits naturally in the pause before the next line.
    rows=[SimpleNamespace(start_ms=0,end_ms=1000,target_text="a"),
          SimpleNamespace(start_ms=2500,end_ms=3000,target_text="b")]
    def fake_synth(text):
        return (np.full(24000*24//10,0.3,dtype=np.float32) if text=="a" else np.full(12000,0.3,dtype=np.float32)),24000
    target=tmp_path/"dub.wav"
    build_dubbed_audio(rows,target,4.0,"unused",synthesizer=fake_synth)
    with wave.open(str(target),"rb") as audio:
        samples=np.frombuffer(audio.readframes(audio.getnframes()),dtype="<i2")
    assert np.all(samples[200:24000*24//10-700])   # first line plays at natural speed
    assert np.any(samples[60000:72000])            # second line starts on time
    assert not np.any(samples[24000*35//10:])      # silence after the last line

def test_too_long_line_is_sped_up_with_pitch_preserving_tempo(tmp_path):
    from app.khmer_tts import fit_line
    rate=16000
    tone=(0.3*np.sin(2*np.pi*440*np.arange(rate*3)/rate)).astype(np.float32)   # 3 s
    out,how=fit_line(tone,rate,int(rate*2))                                      # 2 s slot -> 1.5x
    assert how=="tempo" and abs(len(out)-rate*2)<rate*0.05
    spectrum=np.abs(np.fft.rfft(out[:rate]));peak=np.argmax(spectrum)*rate/rate
    assert 430<peak<450                              # pitch unchanged (resampling would give 660 Hz)

def test_extreme_overflow_is_trimmed_not_failed():
    from app.khmer_tts import fit_line
    out,how=fit_line(np.full(160000,0.3,dtype=np.float32),16000,16000)          # needs 10x
    assert len(out)==16000 and how.endswith("trimmed")

def test_no_translated_speech_rejected(tmp_path):
    with pytest.raises(ValueError,match="No translated Khmer"):
        build_dubbed_audio([],tmp_path/"dub.wav",2,"unused",synthesizer=lambda _:None)
