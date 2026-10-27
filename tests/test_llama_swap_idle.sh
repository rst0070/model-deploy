#!/usr/bin/env bash
# Runtime test for rst0070/rtsp-dashboard#61's AC-10: with llama-swap running
# the real config and yolo26x loaded, after IDLE_S seconds with no request
# (default 900, the spec's 15 minutes) GET /running still lists yolo26x ready.
# Slow and needs a Docker daemon, so opt-in. Run from the repo root:
#   RUN_IDLE_TEST=1 tests/test_llama_swap_idle.sh
#   RUN_IDLE_TEST=1 IDLE_S=30 tests/test_llama_swap_idle.sh   # harness debug
#   RUN_IDLE_TEST=1 tests/test_llama_swap_idle.sh --runxfail  # show the failure
# Needs docker, yq (mikefarah v4), curl, and the local images
# model-deploy/llama-swap:265 and python:3.12-alpine (never pulled).
#
# No GPU: yolo26x's engine is a python:3.12-alpine stand-in that answers every
# GET with 200. llama-swap's own entrypoint is bypassed: it removes every
# container labelled model-deploy.engine on the daemon, and this test must never
# touch a real deployment. Everything the test creates is named mdtest-<run id>
# and labelled model-deploy.test=<run id>, and is removed on exit.
set -u

if [ "${RUN_IDLE_TEST:-}" != 1 ]; then
  echo "SKIP  tests/test_llama_swap_idle.sh: slow; set RUN_IDLE_TEST=1 to run"
  exit 0
fi

REPO=$(cd "$(dirname "$0")/.." && pwd)
CONFIG="$REPO/llama-swap/config.yaml"
IDLE_S=${IDLE_S:-900}
SWAP_IMAGE=model-deploy/llama-swap:265
ENGINE_IMAGE=python:3.12-alpine
API_KEY=mdtest-api-key
RUN_ID=mdtest-$$-$(date +%s)
LABEL=model-deploy.test=$RUN_ID
NET=$RUN_ID
SWAP=$RUN_ID-llama-swap
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/test_llama_swap_idle.XXXXXX")
TEST_PID=

# --- harness -----------------------------------------------------------------

cleanup() {
  trap - EXIT HUP INT TERM
  if [ -n "$TEST_PID" ]; then
    pkill -P "$TEST_PID" 2>/dev/null
    kill "$TEST_PID" 2>/dev/null
  fi
  # llama-swap first, so it cannot start an engine after the sweep.
  docker rm -f "$SWAP" >/dev/null 2>&1
  docker ps -aq --filter "label=$LABEL" | xargs -r docker rm -f >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
  rm -rf "$TMP_ROOT"
}
trap 'cleanup' EXIT
trap 'cleanup; exit 130' HUP INT TERM

# Tests run in a subshell, so exit ends only the current test.
fail() { echo "$*"; exit 1; }

# Not a test result: stop with exit 2, so a strict xfail never passes on a
# broken harness.
harness_error() { echo "HARNESS ERROR: $*" >&2; exit 2; }

preflight() {
  local t
  for t in docker yq curl; do
    command -v "$t" >/dev/null || harness_error "$t not on PATH"
  done
  yq --version 2>&1 | grep -q mikefarah || harness_error "yq is not mikefarah yq v4"
  docker info >/dev/null 2>&1 || harness_error "no Docker daemon reachable"
  for t in "$SWAP_IMAGE" "$ENGINE_IMAGE"; do
    docker image inspect "$t" >/dev/null 2>&1 || harness_error "image $t not present locally"
  done
  [ -f "$CONFIG" ] || harness_error "$CONFIG missing"
}

# The real config with only yolo26x's cmd and cmdStop rewritten: a fake engine
# on the test network, under a test-unique name, reachable by the alias
# ${MODEL_ID} so `proxy` stays exactly as the real file has it. cmdStop must
# change with the name, or it would stop a real engine called yolo26x.
build_config() {
  local engine_cmd stop_cmd
  engine_cmd="docker run --name $RUN_ID-\${MODEL_ID} --rm --init --pull never
--label $LABEL
--network $NET --network-alias \${MODEL_ID}
$ENGINE_IMAGE
sh -c 'mkdir -p /srv && echo ok > /srv/health && cd /srv && exec python -m http.server 8000'"
  stop_cmd="docker stop $RUN_ID-\${MODEL_ID}"
  ENGINE_CMD=$engine_cmd STOP_CMD=$stop_cmd yq '
    .models.yolo26x.cmd = strenv(ENGINE_CMD)
    | .models.yolo26x.cmdStop = strenv(STOP_CMD)
  ' "$CONFIG" > "$TMP_ROOT/config.yaml" || harness_error "yq could not rewrite $CONFIG"

  # Self-check: every yolo26x key but cmd/cmdStop, and the rest of the file,
  # are as the real config says (ttl included).
  local q='del(.models.yolo26x.cmd, .models.yolo26x.cmdStop) | sort_keys(..)'
  [ "$(yq -o=json "$q" "$CONFIG")" = "$(yq -o=json "$q" "$TMP_ROOT/config.yaml")" ] ||
    harness_error "test config differs from the real one beyond yolo26x cmd/cmdStop"
}

# curl to llama-swap with the test key. Sets CODE and BODY.
api() {
  BODY=$(curl -sS -m 30 -o - -w '\n%{http_code}' \
    -H "Authorization: Bearer $API_KEY" "http://127.0.0.1:$PORT$1" 2>&1)
  CODE=${BODY##*$'\n'}
  BODY=${BODY%$'\n'*}
}

# The state /running reports for yolo26x, or "absent".
yolo_state() {
  local s
  s=$(printf '%s' "$1" |
    yq -p=json '[.running[] | select(.model == "yolo26x") | .state][0] // "absent"' 2>/dev/null) ||
    s="unparseable"
  echo "$s"
}

start_llama_swap() {
  docker network create --label "$LABEL" "$NET" >/dev/null ||
    harness_error "could not create network $NET"
  # --entrypoint bypasses the image's entrypoint (see the header). The config
  # is copied in, not bind-mounted: the daemon may not share $TMPDIR.
  docker create --name "$SWAP" --init --label "$LABEL" --network "$NET" \
    -p 127.0.0.1::8080 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -e LLAMA_SWAP_API_KEY="$API_KEY" \
    -e HOST_CACHE_DIR=/nonexistent/mdtest-cache \
    -e ENGINES_DIR=/nonexistent/mdtest-engines \
    --entrypoint llama-swap \
    "$SWAP_IMAGE" --config /mdtest-config.yaml --listen :8080 >/dev/null ||
    harness_error "could not create $SWAP"
  docker cp "$TMP_ROOT/config.yaml" "$SWAP:/mdtest-config.yaml" >/dev/null ||
    harness_error "could not copy the test config into $SWAP"
  docker start "$SWAP" >/dev/null || harness_error "could not start $SWAP"
  PORT=$(docker port "$SWAP" 8080/tcp | head -1 | sed 's/.*://')
  [ -n "$PORT" ] || harness_error "no host port published for $SWAP"

  local tries=60
  while [ "$tries" -gt 0 ]; do
    tries=$((tries - 1))
    api /running
    [ "$CODE" = 200 ] && return 0
    sleep 1
  done
  harness_error "llama-swap never answered /running (last: $CODE $BODY); logs: $(docker logs "$SWAP" 2>&1 | tail -20)"
}

# --- tests -------------------------------------------------------------------

test_ac10_yolo26x_loads() {
  api /upstream/yolo26x/health
  [ "$CODE" = 200 ] ||
    fail "expected /upstream/yolo26x/health to load yolo26x and answer 200, got $CODE: $BODY; llama-swap logs: $(docker logs "$SWAP" 2>&1 | tail -20)"
  api /running
  [ "$(yolo_state "$BODY")" = ready ] ||
    fail "expected /running to list yolo26x as ready right after loading, got $CODE: $BODY"
}

test_ac10_yolo26x_ready_after_idle() {
  sleep "$IDLE_S"
  api /running
  [ "$CODE" = 200 ] || fail "after ${IDLE_S}s idle, /running answered $CODE: $BODY"
  [ "$(yolo_state "$BODY")" = ready ] ||
    fail "after ${IDLE_S}s idle, expected /running to list yolo26x as ready, yolo26x is $(yolo_state "$BODY"); /running returned: $BODY"
}

# --- runner ------------------------------------------------------------------
# `run` expects a pass; `xfail` expects a failure (strict: a pass is an XPASS
# and counts as a failure). Exit 0 iff every test met its expectation.
# --runxfail runs xfail tests as plain runs, to show why they fail.
# Each test runs in the background and the runner waits, so a signal reaches
# the cleanup trap at once instead of after a 15-minute sleep.

FAILED=0
RUNXFAIL=0
[ "${1:-}" = "--runxfail" ] && RUNXFAIL=1

# exec_test <name>: sets RC and MSG.
exec_test() {
  "$1" > "$TMP_ROOT/msg" 2>&1 &
  TEST_PID=$!
  wait "$TEST_PID"
  RC=$?
  TEST_PID=
  MSG=$(cat "$TMP_ROOT/msg")
}
run() {
  exec_test "$1"
  if [ "$RC" = 0 ]; then echo "PASS  $1"
  else echo "FAIL  $1: $MSG"; FAILED=1; fi
}
xfail() {
  if [ "$RUNXFAIL" = 1 ]; then run "$1"; return; fi
  exec_test "$1"
  if [ "$RC" = 0 ]; then echo "XPASS $1: expected to fail (strict xfail) but passed"; FAILED=1
  else echo "XFAIL $1: $MSG"; fi
}

preflight
build_config
start_llama_swap
echo "llama-swap $SWAP on 127.0.0.1:$PORT, idling ${IDLE_S}s after load"
run test_ac10_yolo26x_loads
if [ "$FAILED" = 0 ]; then
  run test_ac10_yolo26x_ready_after_idle
else
  echo "SKIP  test_ac10_yolo26x_ready_after_idle: yolo26x never loaded"
fi

exit "$FAILED"
