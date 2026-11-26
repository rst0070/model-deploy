# Use the models from opencode

Point [opencode](https://opencode.ai) at the llama-swap host so its models show up in `/models`.

## 1. Set the environment variables

Add to `~/.zshrc`:

```sh
export LLAMA_SWAP_API_HOST="http://<gpu-host>:8000"   # scheme + port, no trailing slash, no /v1
export LLAMA_SWAP_API_KEY="<same value as in deploy.sops.env>"
```

Port 8000 is `LLAMA_SWAP_PORT` (see the README).

## 2. Check the connection

```sh
curl -H "Authorization: Bearer $LLAMA_SWAP_API_KEY" "$LLAMA_SWAP_API_HOST/v1/models"
```

It should list the models. Fix this before touching opencode.

## 3. Configure opencode

Create `~/.config/opencode/opencode.json` (macOS). A project-level `opencode.json` also works.
opencode expands `{env:NAME}`, so no secret goes in the file.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "llama-swap": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "GPU host (llama-swap)",
      "options": {
        "baseURL": "{env:LLAMA_SWAP_API_HOST}/v1",
        "apiKey": "{env:LLAMA_SWAP_API_KEY}",
        "timeout": false
      },
      "models": {
        "qwen3.8-27b-gsq-iq3s-gguf": {
          "name": "Qwen3.8 27B (IQ3_S)",
          "limit": { "context": 16384, "output": 4096 }
        },
        "gemma-3-4b-it": { "name": "Gemma 3 4B it" },
        "qwen3.5-0.8b-gguf": {
          "name": "Qwen3.5 0.8B (GGUF)",
          "limit": { "context": 4096, "output": 1024 }
        }
      }
    }
  },
  "model": "llama-swap/qwen3.8-27b-gsq-iq3s-gguf"
}
```

Restart opencode, then pick a model with `/models`.

## Notes

- **Model IDs** are the keys under `models:` in `llama-swap/config.yaml`. Add a model there, then add it here.
- **`limit.context`** mirrors each model's `-c` flag. Without it opencode assumes a window the server rejects.
- **Left out on purpose:** `yolo26x` (unlisted, not a chat model) and `qwen3.5-0.8b` (vLLM entry, no tool-call flags, which opencode needs).
- **First request is slow.** llama-swap loads a model on demand; the first Qwen3.8-27B request downloads ≈ 12 GB (up to `healthCheckTimeout`, 900 s). `"timeout": false` stops opencode giving up early.
- **Switching models evicts the previous one.** Qwen3.8-27B runs alone and unloads everything else.
