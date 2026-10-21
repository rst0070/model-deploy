# Every deploy value lives sops-encrypted in deploy.sops.env (see README.md).
# Each public target checks sops and the age key, then re-runs itself as
# `_<target>` under `sops exec-env`, so the values exist only in the
# environment of that run and are never written to disk.
SOPS_FILE := deploy.sops.env
# Secrets stay shell references ($$VAR): `make -n` and echoed recipes show the
# name, never the value.
URL := "http://localhost:$$LLAMA_SWAP_PORT"
AUTH := -H "Authorization: Bearer $$LLAMA_SWAP_API_KEY"
# --env-file /dev/null: compose would otherwise read a leftover plaintext .env
# in the project dir. Every value comes from the sops environment instead.
COMPOSE := docker compose --env-file /dev/null
GHCR_USER := rst0070
# Engine containers carry this label (see llama-swap/config.yaml).
STOP_ENGINES := ids=$$(docker ps -q --filter label=model-deploy.engine); [ -z "$$ids" ] || docker stop $$ids
# The config llama-swap runs with. Overridable so a test harness that mounts
# another config pulls that config's images.
LLAMA_SWAP_CONFIG ?= llama-swap/config.yaml
# Images llama-swap will `docker run`. llama-swap has no registry login, so the
# host pulls them first; a failed pull stops `up` before llama-swap starts.
GHCR_IMAGES = $(shell grep -oE 'ghcr\.io/[A-Za-z0-9_./-]+:[A-Za-z0-9_.-]+' $(LLAMA_SWAP_CONFIG) | sort -u)
# Key names in the sops file (its own sops_* metadata excluded).
DEPLOY_KEYS = $(shell sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' $(SOPS_FILE) | grep -v '^sops_')

# Preflight, before any docker or curl call.
NEED_SOPS = command -v sops >/dev/null 2>&1 || { echo "make $@: sops not installed (not found on PATH). Install sops and age, see README.md." >&2; exit 1; }
# Decrypts to /dev/null only; keeps sops's stderr, which lists where it looked.
NEED_KEY = err=$$(sops -d $(SOPS_FILE) 2>&1 >/dev/null) || { echo "make $@: no age key that can decrypt $(SOPS_FILE). sops looked at SOPS_AGE_KEY_FILE ($${SOPS_AGE_KEY_FILE:-unset}), SOPS_AGE_KEY and the default keys.txt; its report:" >&2; printf '%s\n' "$$err" >&2; exit 1; }

TARGETS := up down gpu-free running logs
.PHONY: $(TARGETS) $(addprefix _,$(TARGETS))

$(TARGETS):
	@$(NEED_SOPS)
	@$(NEED_KEY)
	@sops exec-env $(SOPS_FILE) '$(MAKE) --no-print-directory _$@'

# The rest runs inside `sops exec-env`. Call the public targets, not these.

# Refuses while a value is still a REPLACE_ME_* placeholder, naming keys, never
# values. The trap logs out of ghcr.io even when a pull fails or is
# interrupted, so the token does not stay in ~/.docker/config.json.
_up:
	@bad=; for k in $(DEPLOY_KEYS); do case "$$(printenv $$k)" in REPLACE_ME_*) bad="$$bad $$k";; esac; done; \
	[ -z "$$bad" ] || { echo "make up: these keys in $(SOPS_FILE) still hold REPLACE_ME_* placeholders:$$bad. Set them with: sops edit $(SOPS_FILE)" >&2; exit 1; }
	@test -f $(LLAMA_SWAP_CONFIG) || { echo "make up: $(LLAMA_SWAP_CONFIG) not found" >&2; exit 1; }
	@trap 'docker logout ghcr.io >/dev/null' EXIT; trap 'exit 1' INT TERM; \
	printf '%s' "$$GHCR_TOKEN" | docker login ghcr.io -u $(GHCR_USER) --password-stdin || exit 1; \
	for img in $(GHCR_IMAGES); do docker pull $$img || exit 1; done
	$(COMPOSE) up -d --build

# Unload through llama-swap, then sweep any engine it could not stop.
_down:
	-@curl -fsS -X POST $(AUTH) $(URL)/api/models/unload && echo
	$(COMPOSE) down
	@$(STOP_ENGINES)

# Stop every engine through llama-swap, so the GPU is free for other work.
_gpu-free:
	@curl -fsS -X POST $(AUTH) $(URL)/api/models/unload && echo

_running:
	@curl -fsS $(AUTH) $(URL)/running; echo
	@docker ps --filter label=model-deploy.engine --format '{{.ID}} {{.Names}} {{.Image}}'

_logs:
	$(COMPOSE) logs -f llama-swap
