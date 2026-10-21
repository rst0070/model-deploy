-include .env

COMPOSE := docker compose --env-file .env
URL := http://localhost:8080
AUTH := -H "Authorization: Bearer $(LLAMA_SWAP_API_KEY)"
# Host path of engines/. Engines mount it, and the host daemon resolves
# their bind mounts, so llama-swap needs the host path, not its own.
export ENGINES_DIR := $(CURDIR)/engines
# Engine containers carry this label (see llama-swap/config.yaml).
STOP_ENGINES := ids=$$(docker ps -q --filter label=model-deploy.engine); [ -z "$$ids" ] || docker stop $$ids

.PHONY: up down gpu-free running logs

up:
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
