-include .env

COMPOSE := docker compose --env-file .env
URL := http://localhost:8080
AUTH := -H "Authorization: Bearer $(LLAMA_SWAP_API_KEY)"
# Engine containers carry this label (see llama-swap/config.yaml).
STOP_ENGINES := ids=$$(docker ps -q --filter label=model-deploy.engine); [ -z "$$ids" ] || docker stop $$ids
# The config llama-swap runs with. Overridable so a test harness that mounts
# another config pulls that config's images.
LLAMA_SWAP_CONFIG ?= llama-swap/config.yaml
# Images llama-swap will `docker run`. llama-swap has no registry login, so the
# host pulls them first; a failed pull stops `up` before llama-swap starts.
GHCR_IMAGES = $(shell grep -oE 'ghcr\.io/[A-Za-z0-9_./-]+:[A-Za-z0-9_.-]+' $(LLAMA_SWAP_CONFIG) | sort -u)

.PHONY: up down gpu-free running logs

up:
	@test -f $(LLAMA_SWAP_CONFIG) || { echo "make up: $(LLAMA_SWAP_CONFIG) not found" >&2; exit 1; }
	@for img in $(GHCR_IMAGES); do docker pull $$img || exit 1; done
	$(COMPOSE) up -d --build

# Unload through llama-swap, then sweep any engine it could not stop.
down:
	-@curl -fsS -X POST $(AUTH) $(URL)/api/models/unload && echo
	$(COMPOSE) down
	@$(STOP_ENGINES)

# Stop every engine through llama-swap, so the GPU is free for other work.
gpu-free:
	@curl -fsS -X POST $(AUTH) $(URL)/api/models/unload && echo

running:
	@curl -fsS $(AUTH) $(URL)/running; echo
	@docker ps --filter label=model-deploy.engine --format '{{.ID}} {{.Names}} {{.Image}}'

logs:
	$(COMPOSE) logs -f llama-swap
