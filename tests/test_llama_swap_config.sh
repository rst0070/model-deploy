#!/usr/bin/env bash
# Config-contract tests for rst0070/rtsp-dashboard#61's AC-10 (yolo26x stays
# loaded while llama-swap runs). AC-10 itself needs the GPU host (QA step 1:
# `make up`, 15 idle minutes, `GET /running`); these pin the llama-swap config
# that produces it. Run from the repo root:
#   tests/test_llama_swap_config.sh              # xfail tests expected to fail
#   tests/test_llama_swap_config.sh --runxfail   # run every test as a plain run
# Needs yq (mikefarah v4) and git. BASE_REF (default origin/main) is the config
# that "nothing else changes" compares against.
set -u

REPO=$(cd "$(dirname "$0")/.." && pwd)
CONFIG="$REPO/llama-swap/config.yaml"
BASE_REF=${BASE_REF:-origin/main}
EXPECTED_IMAGE=ghcr.io/rst0070/model-deploy-yolo:0.2.0
QWEN27B=qwen3.8-27b-gsq-iq3s-gguf
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/test_llama_swap_config.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT

# --- harness -----------------------------------------------------------------

# Tests run in a subshell, so exit ends only the current test.
fail() { echo "$*"; exit 1; }

# Missing tools or an unknown BASE_REF are not test results: stop before any
# test runs, so a strict xfail can never pass for the wrong reason.
preflight() {
  command -v yq >/dev/null || { echo "preflight: yq not on PATH" >&2; exit 2; }
  yq --version 2>&1 | grep -q 'mikefarah' ||
    { echo "preflight: yq is not mikefarah yq v4" >&2; exit 2; }
  [ -f "$CONFIG" ] || { echo "preflight: $CONFIG missing" >&2; exit 2; }
  git -C "$REPO" cat-file -e "$BASE_REF:llama-swap/config.yaml" 2>/dev/null ||
    { echo "preflight: $BASE_REF:llama-swap/config.yaml not found (fetch, or set BASE_REF)" >&2; exit 2; }
}

# normalize <file>: the config as sorted JSON, with yolo26x's ttl removed, its
# image tag replaced by a placeholder, and the qwen3.8-27b entry dropped.
# Comments do not survive.
normalize() {
  yq -o=json '
    del(.models."qwen3.8-27b-gsq-iq3s-gguf")
    | del(.models.yolo26x.ttl)
    | .models.yolo26x.cmd |= sub("model-deploy-yolo:[^\s]+"; "model-deploy-yolo:TAG")
    | sort_keys(..)
  ' "$1"
}

# --- tests -------------------------------------------------------------------

test_ac10_yolo26x_never_idles_out() {
  local ttl
  ttl=$(yq '.models.yolo26x.ttl' "$CONFIG") || fail "yq could not read $CONFIG"
  [ "$ttl" = "0" ] || fail "expected models.yolo26x.ttl to be 0, got $ttl"
}

test_ac10_yolo26x_pins_engine_0_2_0() {
  local cmd image others
  cmd=$(yq '.models.yolo26x.cmd' "$CONFIG") || fail "yq could not read $CONFIG"
  image=$(printf '%s' "$cmd" | grep -o 'ghcr.io/rst0070/model-deploy-yolo:[^[:space:]]*')
  # A whole word of the command, so a longer tag such as 0.2.0-rc1 does not count.
  printf '%s' "$cmd" | tr -s '[:space:]' '\n' | grep -qxF -- "$EXPECTED_IMAGE" ||
    fail "expected models.yolo26x.cmd to run $EXPECTED_IMAGE, got ${image:-no yolo image}"
  others=$(grep -o 'model-deploy-yolo:[^[:space:]"]*' "$CONFIG" |
    grep -vxF 'model-deploy-yolo:0.2.0' | sort -u | tr '\n' ' ')
  [ -z "$others" ] ||
    fail "expected no model-deploy-yolo tag other than 0.2.0 in config.yaml, found: $others"
}

test_ac10_nothing_else_changes() {
  normalize "$CONFIG" > "$TMP_ROOT/head.json" || fail "yq could not normalize $CONFIG"
  git -C "$REPO" show "$BASE_REF:llama-swap/config.yaml" > "$TMP_ROOT/base.yaml" ||
    fail "git show $BASE_REF:llama-swap/config.yaml failed"
  normalize "$TMP_ROOT/base.yaml" > "$TMP_ROOT/base.json" || fail "yq could not normalize the $BASE_REF config"
  diff -u "$TMP_ROOT/base.json" "$TMP_ROOT/head.json" > "$TMP_ROOT/diff" ||
    fail "config.yaml differs from $BASE_REF beyond yolo26x ttl, image tag and the $QWEN27B entry:
$(cat "$TMP_ROOT/diff")"
}

test_qwen27b_entry_has_ttl_600() {
  local ttl
  ttl=$(yq ".models.\"$QWEN27B\".ttl" "$CONFIG") || fail "yq could not read $CONFIG"
  [ "$ttl" = "600" ] || fail "expected models.$QWEN27B.ttl to be 600, got $ttl"
}

test_qwen27b_uses_llamacpp_run() {
  local cmd
  cmd=$(yq ".models.\"$QWEN27B\".cmd" "$CONFIG") || fail "yq could not read $CONFIG"
  printf '%s' "$cmd" | tr -s '[:space:]' '\n' | grep -qxF -- '${llamacpp-run}' ||
    fail "expected models.$QWEN27B.cmd to use \${llamacpp-run}, got: $cmd"
}

test_qwen27b_cmd_selects_plain_iq3s_text_only() {
  local cmd
  cmd=$(yq ".models.\"$QWEN27B\".cmd" "$CONFIG") || fail "yq could not read $CONFIG"
  printf '%s' "$cmd" | tr -s '[:space:]' '\n' | grep -qxF -- 'ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF:IQ3_S' ||
    fail "expected -hf ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF:IQ3_S, got: $cmd"
  printf '%s' "$cmd" | tr -s '[:space:]' '\n' | grep -qxF -- '--no-mmproj' ||
    fail "expected --no-mmproj in models.$QWEN27B.cmd, got: $cmd"
  ! printf '%s' "$cmd" | grep -qi -- 'mtp' ||
    fail "models.$QWEN27B.cmd must not use the -mtp file or tag, got: $cmd"
}

test_qwen27b_runs_alone_in_no_routing_set() {
  local routing
  # Absence only means something once the model exists.
  [ "$(yq ".models | has(\"$QWEN27B\")" "$CONFIG")" = true ] ||
    fail "expected models.$QWEN27B to exist"
  routing=$(yq '.routing.router.settings.matrix | [.vars, .sets] | .. | select(tag == "!!str")' "$CONFIG") ||
    fail "yq could not read $CONFIG"
  ! printf '%s' "$routing" | grep -qF -- "$QWEN27B" ||
    fail "$QWEN27B must be in no matrix var or set, found it in: $routing"
  [ "$(yq ".routing.router.settings.matrix.vars | to_entries | map(select(.value == \"$QWEN27B\")) | length" "$CONFIG")" = 0 ] ||
    fail "$QWEN27B must not be a value of matrix.vars"
}

# --- runner ------------------------------------------------------------------
# `run` expects a pass; `xfail` expects a failure (strict: a pass is an XPASS
# and counts as a failure). Exit 0 iff every test met its expectation.
# --runxfail runs xfail tests as plain runs, to show why they fail.

FAILED=0
RUNXFAIL=0
[ "${1:-}" = "--runxfail" ] && RUNXFAIL=1

run() {
  local msg
  if msg=$("$1" 2>&1); then echo "PASS  $1"
  else echo "FAIL  $1: $msg"; FAILED=1; fi
}
xfail() {
  local msg
  if [ "$RUNXFAIL" = 1 ]; then run "$1"; return; fi
  if msg=$("$1" 2>&1); then echo "XPASS $1: expected to fail (strict xfail) but passed"; FAILED=1
  else echo "XFAIL $1: $msg"; fi
}

preflight
run test_ac10_yolo26x_never_idles_out
run test_ac10_yolo26x_pins_engine_0_2_0
run test_ac10_nothing_else_changes
run test_qwen27b_entry_has_ttl_600
run test_qwen27b_uses_llamacpp_run
run test_qwen27b_cmd_selects_plain_iq3s_text_only
run test_qwen27b_runs_alone_in_no_routing_set

exit "$FAILED"
