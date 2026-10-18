# llama-swap plus the docker CLI, so llama-swap can start and stop engine
# containers on the host daemon through the mounted socket.
FROM docker:29.8.2-cli

ARG LLAMA_SWAP_VERSION=265
RUN arch=$(case "$(uname -m)" in aarch64) echo arm64;; *) echo amd64;; esac) \
    && wget -qO- "https://github.com/mostlygeek/llama-swap/releases/download/v${LLAMA_SWAP_VERSION}/llama-swap_${LLAMA_SWAP_VERSION}_linux_${arch}.tar.gz" \
    | tar -xz -C /usr/local/bin llama-swap

EXPOSE 8080
# An engine still running when llama-swap starts was orphaned by a crash. Remove
# it first, or it holds its name and VRAM and a second engine could start.
ENTRYPOINT ["sh", "-c", "docker ps -aq --filter label=model-deploy.engine | xargs -r docker rm -f; exec llama-swap --config /etc/llama-swap/config.yaml --listen :8080"]
