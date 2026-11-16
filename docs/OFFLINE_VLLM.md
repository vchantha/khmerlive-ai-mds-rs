# Offline vLLM post-editing (experimental)

This optional component post-edits M2M100 English→Khmer text before Khmer TTS and subtitle muxing. It is **disabled by default**, so existing jobs are unaffected. It uses vLLM's OpenAI-compatible local endpoint and requires an NVIDIA GPU and NVIDIA Container Toolkit for the supplied Compose overlay. See [vLLM Docker docs](https://docs.vllm.ai/en/stable/deployment/docker/).

## Requirements and offline preparation

1. Check `nvidia-smi` and `docker info` on the deployment host. The supplied overlay requests all NVIDIA GPUs; size the model and memory parameters for your actual GPU.
2. While connected to the Internet, pre-download the selected compatible model and tokenizer to `./models/huggingface` using a Hugging Face cache layout, or transfer the full cache from another machine. Also pre-pull the pinned vLLM image. The default small model is for **smoke testing**, not a validated Khmer-quality recommendation.
3. Set `VLLM_IMAGE` to a vetted version compatible with your GPU drivers, `VLLM_MODEL` to the model's cached Hugging Face identifier, and `VLLM_SERVED_MODEL=khmerlive-postedit`. The Compose image is pinned to v0.11.0 as an initial candidate; validate compatibility before production use.
4. Run the base + real + vLLM overlays. The vLLM service is behind a Compose profile and is not exposed on a public host port.

```bash
docker compose -f compose.yaml -f compose.real.yaml -f compose.vllm.yaml --profile vllm config
docker compose -f compose.yaml -f compose.real.yaml -f compose.vllm.yaml --profile vllm up -d --build
docker compose -f compose.yaml -f compose.real.yaml -f compose.vllm.yaml --profile vllm exec vllm curl -fsS http://localhost:8000/v1/models
```

Only **after** the model server is healthy, set `VLLM_POSTEDIT_ENABLED=true` in the deployment environment and recreate the worker. The overlay forwards that variable to the worker. If `VLLM_FAIL_OPEN=true` (default), network/response errors revert the entire job to the unedited M2M100 translation; set it to false for strict research experiments.

For tests:

```bash
cd backend
pytest -q tests/test_llm_postedit.py
```

## Research and safety notes

- The system preserves original ASR segment timestamps, but the generated Khmer audio duration may still differ. Post-editing is not the same as verified duration alignment.
- Outputs must be evaluated by Khmer-speaking reviewers for semantic adequacy, fluency, hallucinations, and named-entity preservation.
- The vLLM endpoint is restricted to internal/local hostnames in application code and does not use environment proxy settings. Do not expose the vLLM service to the public Internet.
- Model weights and image must be present before disconnected operation; `HF_HUB_OFFLINE=1` prevents runtime downloads.
- This integration does **not** fine-tune the LLM. LoRA training and reproducible benchmark datasets are separate research tasks.
- GPU startup and actual model inference have not been verified by GitHub-only checks; run the documented commands on the target machine.
