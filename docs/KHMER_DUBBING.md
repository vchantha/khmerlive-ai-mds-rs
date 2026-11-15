# Offline English → Khmer voice dubbing (research preview)

**Implemented:** Whisper speech recognition → M2M100 text translation →
Meta MMS Khmer VITS text-to-speech → 24 kHz timed voice track → FFmpeg
H.264/AAC MP4 with translated Khmer subtitles. Original English audio is
**replaced** on English→Khmer dubbing jobs, not mixed underneath.

**Not implemented:** voice cloning, lip-sync, background-music preservation,
multiple speaker voices, or Khmer→English spoken dubbing. This first version
generates one synthetic Khmer voice; the timing engine fits each synthesized
utterance into its recognized speech segment, potentially changing pitch.
If a segment requires an extreme speedup, the job **fails explicitly** rather
than silently delivering unintelligible or original-English audio.

## Model licensing

The proposed local Khmer model `facebook/mms-tts-khm` is licensed
**CC-BY-NC-4.0 (non-commercial)**. Do not deploy it for commercial use
without suitable permission or replacing it with a commercially licensed
Khmer TTS checkpoint. The downloader records model revisions and license
metadata. Verify licenses for every ASR/MT/TTS component independently.

## Install on an online staging host

```bash
python3 -m venv .venv-models
source .venv-models/bin/activate
python -m pip install huggingface-hub==0.30.2
python scripts/download-models.py --output models
deactivate
```

Transfer `models/asr`, `models/mt`, `models/tts` and the manifest
to the offline host. Model weights are not committed to Git.

## Start real dubbing mode

Set your private `.env` to include:

```env
ENABLE_KHMER_DUBBING=true
KHMER_TTS_MODEL_PATH=/models/tts
```

Start the real-mode services:

```bash
docker compose -f compose.yaml -f compose.real.yaml up -d --build
docker compose -f compose.yaml -f compose.real.yaml run --rm --no-deps api pytest -q
python3 scripts/e2e-real.py --video /path/to/english-speech.mp4 --from-lang en
```

Do **not** run only `docker compose up` without the real override: default
mode is DEMO and will preserve the English soundtrack. The `/api/models`
endpoint reports `speech_dubbing_available`; English→Khmer jobs are
rejected with HTTP 503 if any required model is absent.

A newly completed English→Khmer real job produces
`outputs/<job-id>.khmer-dubbed.mp4` in MinIO and a translated SRT.
Existing previously completed jobs remain unchanged: **submit the original
video as a new job** to generate a Khmer voice. The UI shows a distinct
`Khmer voice dubbing` label only for the new dubbed artifact.

## Acceptance and limitations

A completed worker task validates an H.264 video stream, AAC audio stream
and translated subtitle track. The included unit tests verify that generated
WAV audio is placed in the intended speech time slots and silence exists
outside them. Test the output with human Khmer reviewers for intelligibility,
timing, pronunciation, proper names and translation accuracy.

No full end-to-end inference run on downloaded model weights or on the user's
Ubuntu server has been confirmed. Do not describe this feature as
production-ready or perfect translation before that validation.
