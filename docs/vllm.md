# Experiment with vLLM on an M1 Mac

Lalaland supports `INFERENCE_PROVIDER=ollama` (default) or `vllm` for both agents.
The vLLM adapter uses `/v1/chat/completions` and `/v1/models`; no vLLM package is
needed in the application image or its Python environment.

## Start an inference server

For GPU acceleration, run vLLM Metal natively on macOS, separately from Lalaland's
containers. Its [installation guide](https://github.com/vllm-project/vllm-metal/blob/main/docs/installation.md)
requires Apple Silicon and macOS 15 or later:

```bash
brew tap vllm-project/vllm-metal https://github.com/vllm-project/vllm-metal
brew install vllm-project/vllm-metal/vllm-metal
```

Start with [mlx-community/Qwen2.5-3B-Instruct-4bit](https://huggingface.co/mlx-community/Qwen2.5-3B-Instruct-4bit): a quantized instruction model
in the same 3B size class as Lalaland's Granite4.2 default. The Metal matrix lists
Qwen2.5 as supported and says other sizes and quantizations of supported families
generally work; this exact checkpoint still needs validation on your machine.
Granite4.2 is not listed, so do not reuse the Ollama default for this experiment.

```bash
vllm serve mlx-community/Qwen2.5-3B-Instruct-4bit \
  --served-model-name local-model --host 0.0.0.0 --port 8001 \
  --max-model-len 24576
curl http://127.0.0.1:8001/v1/models
```

The model is an experiment starting point, not a briefing quality benchmark.
Port 8001 avoids Lalaland's default API port. Binding to `0.0.0.0` allows host
access from containers and also exposes the server on network interfaces; use
`--host 127.0.0.1` for native-only use, or vLLM's `--api-key` with
`VLLM_API_KEY` when authentication is needed.

Check the [current model matrix](https://github.com/vllm-project/vllm-metal/blob/main/docs/supported_models.md)
for compatibility. Ollama model names such as `granite4.2:3b` are not vLLM model
identifiers. For CPU-only experimentation, follow vLLM's separate
[macOS CPU build instructions](https://docs.vllm.ai/en/latest/getting_started/installation/cpu/);
native Apple Silicon CPU support is experimental and requires a source build.

## Point Lalaland at the server

For Docker Compose, add these settings to `.env`:

```dotenv
INFERENCE_PROVIDER=vllm
VLLM_BASE_URL=http://host.docker.internal:8001/v1
VLLM_MODEL=local-model
CORPUS_MODEL=local-model
```

Rebuild and recreate the application with `docker compose up -d --build`.
For native use, export the same settings with `VLLM_BASE_URL=http://127.0.0.1:8001/v1`
and restart both API and worker. An unset `CORPUS_MODEL` defaults to `VLLM_MODEL`
when vLLM is selected. `VLLM_API_KEY` is optional and must match the server key.

For Kubernetes, publish and promote the changed application image as described in
[image releases](releases.md). Set the same provider, URL, and model variables on
**both** backend and worker through their GitOps `env` values or managed runtime
secret. Use a host address reachable from the cluster; `127.0.0.1` inside a pod
refers to that pod. A Metal server stays on the macOS host.

Open Corpus to check model discovery, then submit a new article and choose
**Run queued articles now**. Existing articles retain their saved model ID;
retry failed articles with a model served by the selected provider. Existing
pending articles using Ollama IDs need to finish before switching, or be deleted
and resubmitted with a vLLM model.

## Compare results

Start with one RSS run and one small corpus article. Record elapsed time, memory
use, completion failures, and factual quality. Keep the model, inputs, and output
budget comparable when measuring runtime differences. A smaller model's quality
can differ substantially from your Ollama default.

Corpus final writing requests a JSON schema through
[vLLM structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/).
The installed server/backend must support that feature. Unsupported schema
requests fail explicitly; the adapter does not silently relax validation.
Malformed or truncated final briefings keep the existing bounded writing retries.
The application still serializes inference, so this experiment measures individual
requests rather than vLLM's concurrent serving throughput.

The existing `OLLAMA_TIMEOUT_SECONDS`, `CORPUS_OLLAMA_TIMEOUT_SECONDS`,
`CORPUS_FINAL_TIMEOUT_SECONDS`, and `CORPUS_FINAL_NUM_PREDICT` settings also apply
to vLLM. The server context limit must fit the full prompt plus output tokens;
reduce the output budget if needed. No automatic switch to Ollama occurs on errors.

To switch back, set `INFERENCE_PROVIDER=ollama`, restore an Ollama `CORPUS_MODEL`
(or unset it), and recreate/restart backend and worker. The legacy
`/api/ollama/models` route remains an alias for `/api/inference/models`, which
discovers models from the selected provider.
