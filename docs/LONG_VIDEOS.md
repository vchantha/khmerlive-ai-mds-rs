# Processing videos up to two hours

The standard worker limit is 600 seconds. A video of 6,643 seconds
(1:50:43) fails at duration validation under that configuration. Retry alone
does not change the configured limit.

For long inputs, add the opt-in profile **last** in the Compose command:

```sh
# Demo processing (original speech retained)
docker compose -f compose.yaml -f compose.long-video.yaml up -d --build api worker web

# Real translation / Khmer dubbing (requires installed models)
docker compose -f compose.yaml -f compose.real.yaml -f compose.long-video.yaml up -d --build api worker web
```

The profile overrides existing `.env` duration values for both API and worker:

- Maximum input duration: 7,200 seconds (two hours).
- Worker hard timeout: 21,600 seconds (six hours); soft timeout five minutes earlier.
- Upload size limit remains unchanged.

Wait for active jobs to finish before recreating the worker. Once the new
worker is running, use Retry on the failed job; the uploaded source is reused.
Include the same profile in subsequent Compose updates to retain these limits.

The upload form displays the effective server duration and file-size limits.
Khmer TTS uses the worker's configured duration limit and assembles the track
on disk, with normalization and PCM export in ten-second blocks. This removes
the previous independent one-hour TTS ceiling and avoids full-track temporary
RAM copies. Two hours require roughly 0.7 GB for the float timeline and
0.35 GB for its PCM WAV, in addition to source, extracted audio, output, and
model resources. ASR/translation still use their existing inference paths.

The six-hour timeout is a processing budget, not a throughput guarantee.
Regression tests use synthetic speech to check 6,643-second track timing;
they do not establish full-video model performance or pronunciation quality.
