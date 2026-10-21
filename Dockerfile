# llama-swap plus the docker CLI, so llama-swap can start and stop engine
# containers on the host daemon through the mounted socket.
FROM docker:29.8.2-cli

ARG LLAMA_SWAP_VERSION=265
RUN arch=$(case "$(uname -m)" in aarch64) echo arm64;; *) echo amd64;; esac) \
    && wget -qO- "https://github.com/mostlygeek/llama-swap/releases/download/v${LLAMA_SWAP_VERSION}/llama-swap_${LLAMA_SWAP_VERSION}_linux_${arch}.tar.gz" \
    | tar -xz -C /usr/local/bin llama-swap

EXPOSE 8080
# Engines bind-mount engines/, and the host daemon resolves bind-mount sources,
# so llama-swap needs the host path. Compose mounts ./engines at /engines and
# resolves it to an absolute host path; ask the daemon for that source. No
# fallback: a wrong path would only surface later, as a broken engine mount.
# An engine still running when llama-swap starts was orphaned by a crash. Remove
# it first, or it holds its name and VRAM and a second engine could start.
COPY <<'EOF' /usr/local/bin/entrypoint.sh
ENGINES_DIR=$(docker inspect llama-swap \
  --format '{{range .Mounts}}{{if eq .Destination "/engines"}}{{.Source}}{{end}}{{end}}')
if [ -z "$ENGINES_DIR" ]; then
  echo "llama-swap: no /engines mount found on container llama-swap;" \
    "start it with docker compose from the repo, which mounts ./engines" >&2
  exit 1
fi
export ENGINES_DIR
docker ps -aq --filter label=model-deploy.engine | xargs -r docker rm -f
exec llama-swap --config /etc/llama-swap/config.yaml --listen :8080
EOF
ENTRYPOINT ["sh", "/usr/local/bin/entrypoint.sh"]
