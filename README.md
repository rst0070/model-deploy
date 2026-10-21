# model-deploy

llama-swap in front of on-demand engine containers (vLLM, llama.cpp, YOLO) on a
local GPU host. llama-swap listens on host port **8000** (container port 8080)
and accepts one bearer key.

## Deploy values

Every deploy value lives in `deploy.sops.env`, encrypted with
[sops](https://github.com/getsops/sops) for the age recipients listed in
`.sops.yaml`. `HOST_CACHE_DIR` is stored in plaintext; the rest is `ENC[...]`.
There is no `.env`: the Makefile runs everything under `sops exec-env`, so
decrypted values exist only in the environment of that run.

| Key | Meaning |
|---|---|
| `HOST_CACHE_DIR` | Absolute host path holding `huggingface/` and `vllm/` |
| `LLAMA_SWAP_PORT` | Host port llama-swap is published on (8000) |
| `LLAMA_SWAP_API_KEY` | The bearer key llama-swap accepts, no spaces |
| `HUGGING_FACE_HUB_TOKEN` | HF download token, passed to engines |
| `GHCR_TOKEN` | Classic PAT with `read:packages`, to pull `ghcr.io/rst0070/*` |

Edit values with `sops edit deploy.sops.env`. `make up` refuses to start while
any value is still a `REPLACE_ME_*` placeholder.

## GPU host bootstrap

1. Install sops (3.9 or later) and age, plus Docker with the NVIDIA runtime.
2. Generate the host's own age key; the private key never leaves the host:
   `age-keygen -o ~/.config/sops/age/keys.txt`
   (or point `SOPS_AGE_KEY_FILE` at it).
3. Add the printed `age1…` public key to `.sops.yaml` as the GPU host
   recipient (replace `REPLACE_ME_GPU_HOST_AGE_PUBKEY` and uncomment the line).
4. From a machine that can already decrypt the file, re-key it and commit:
   `sops updatekeys deploy.sops.env`
5. On the host, clone the repo and run `make up`.

## Make targets

| Target | Effect |
|---|---|
| `make up` | Log in to ghcr.io, pull the pinned images, log out, `docker compose up` |
| `make down` | Unload models, stop llama-swap, stop any leftover engine |
| `make gpu-free` | Unload every model so the GPU is free |
| `make running` | Show loaded models and engine containers |
| `make logs` | Follow llama-swap logs |

Each target fails before touching Docker if sops is missing or no age key can
decrypt `deploy.sops.env`. `LLAMA_SWAP_CONFIG=<path> make up` pulls the images
of another llama-swap config.

```sh
curl -H "Authorization: Bearer $KEY" http://<host>:8000/v1/models
```
