import pytest
from app.media_preview import (
    issue_playback_token,check_playback_token,InvalidPlaybackToken,
    parse_byte_range,InvalidByteRange,srt_to_webvtt
)

SECRET="a-long-unique-random-signing-key-for-tests-not-production"
def test_token_scope_expiry_and_tampering():
    token=issue_playback_token("job-123","user-1",SECRET,60,now=100)
    check_playback_token(token,"job-123","user-1",SECRET,now=159)
    for job,owner,at in [("job-999","user-1",101),("job-123","user-2",101),("job-123","user-1",160)]:
        with pytest.raises(InvalidPlaybackToken):
            check_playback_token(token,job,owner,SECRET,now=at)
    with pytest.raises(InvalidPlaybackToken):
        check_playback_token(token[:-1]+"x","job-123","user-1",SECRET,now=101)

@pytest.mark.parametrize("value,size,start,end",[
    ("bytes=0-9",100,0,9),("bytes=25-",100,25,99),("bytes=-12",100,88,99),
    ("bytes=0-999",100,0,99)
])
def test_valid_ranges(value,size,start,end):
    r=parse_byte_range(value,size)
    assert (r.start,r.end,r.length)==(start,end,end-start+1)
    assert r.s3_range==f"bytes={start}-{end}"
def test_full_response():
    assert parse_byte_range(None,100) is None
@pytest.mark.parametrize("value",["bytes=99-98","bytes=100-200","bytes=0-1,5-10","bytes=--","bytes=-0","items=0-10"])
def test_unsatisfiable_ranges(value):
    with pytest.raises(InvalidByteRange):
        parse_byte_range(value,100)
def test_utf8_webvtt():
    text="1\n00:00:00,000 --> 00:00:02,250\nសួស្តី ពិភពលោក\n"
    vtt=srt_to_webvtt(text)
    assert vtt.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:02.250" in vtt
    assert "សួស្តី" in vtt
