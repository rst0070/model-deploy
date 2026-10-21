#!/usr/bin/env bash
# Acceptance tests for issue #11 (deploy values in sops + age) that need no GPU:
# AC-4, the plaintext half of AC-7, and AC-9. Run from the repo root:
#   tests/test_deploy.sh
# Needs sops on PATH and an age key for TEST_RECIPIENT in the caller's environment.
# docker and curl are always shimmed: no test reaches the daemon or the network.
# Never prints or stores the decrypted contents of the real deploy.sops.env.
set -u

REPO=$(cd "$(dirname "$0")/.." && pwd)
TEST_RECIPIENT=age1wrtuy3s8q0l7g57xgz290uxxl8geywyvnk79dke5d7n3j5x0z4nsq4cygn
TARGETS="up down gpu-free running logs"
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/test_deploy.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT

# --- harness -----------------------------------------------------------------

# Tests run in a subshell, so exit ends only the current test.
fail() { echo "$*"; exit 1; }

# A fresh copy of the working tree: tracked plus untracked-but-not-ignored
# files, skipping paths missing on disk. Never .git, never ignored files.
copy_repo() {
  local dst p
  dst=$(mktemp -d "$TMP_ROOT/repo.XXXXXX")
  (cd "$REPO" && git ls-files -co --exclude-standard -z) |
    while IFS= read -r -d '' p; do
      [ -e "$REPO/$p" ] || continue
      mkdir -p "$dst/$(dirname "$p")" && cp -p "$REPO/$p" "$dst/$p"
    done
  echo "$dst"
}

# Fake docker and curl: append argv to $SHIM_LOG and exit 1.
make_shims() {
  local cmd
  SHIMS=$(mktemp -d "$TMP_ROOT/shims.XXXXXX")
  SHIM_LOG="$SHIMS/calls.log"
  for cmd in docker curl; do
    printf '#!/bin/sh\necho "%s $*" >> "%s"\nexit 1\n' "$cmd" "$SHIM_LOG" > "$SHIMS/$cmd"
    chmod +x "$SHIMS/$cmd"
  done
}

# run_make <copy> <target> <base PATH> [env(1) args: -u NAME... then NAME=value...]
# The shim dir always goes first on PATH. Sets RC, OUT, ERR.
run_make() {
  local dir=$1 target=$2 base=$3
  shift 3
  : > "$SHIM_LOG"
  env "$@" PATH="$SHIMS:$base" make -C "$dir" "$target" \
    </dev/null >"$TMP_ROOT/out" 2>"$TMP_ROOT/err"
  RC=$?
  OUT=$(cat "$TMP_ROOT/out")
  ERR=$(cat "$TMP_ROOT/err")
}

one_line() { printf '%s' "$1" | tr '\n' ' ' | cut -c1-240; }

assert_exit_nonzero() {
  [ "$RC" -ne 0 ] || fail "$1: expected a non-zero exit, got 0"
}

assert_no_shim_calls() {
  [ ! -s "$SHIM_LOG" ] ||
    fail "$1: expected no docker/curl call before failing, saw: $(one_line "$(cat "$SHIM_LOG")")"
}

# assert_stderr_mentions <label> <word>... (case-insensitive)
assert_stderr_mentions() {
  local label=$1 w
  shift
  for w in "$@"; do
    printf '%s' "$ERR" | grep -qi -- "$w" ||
      fail "$label: expected stderr to mention '$w', got: $(one_line "$ERR")"
  done
}

# --- tests -------------------------------------------------------------------

# AC-4: no usable age key -> every target fails before docker/curl, naming the key.
test_ac4_no_age_key() {
  local copy home t
  copy=$(copy_repo)
  make_shims
  home=$(mktemp -d "$TMP_ROOT/home.XXXXXX")
  for t in $TARGETS; do
    run_make "$copy" "$t" "$PATH" \
      -u SOPS_AGE_KEY -u SOPS_AGE_KEY_CMD -u XDG_CONFIG_HOME -u SOPS_AGE_SSH_PRIVATE_KEY_FILE \
      SOPS_AGE_KEY_FILE=/nonexistent HOME="$home"
    assert_exit_nonzero "make $t (no age key)"
    assert_stderr_mentions "make $t (no age key)" age key
    assert_no_shim_calls "make $t (no age key)"
  done
}

# AC-4: sops not on PATH -> every target fails before docker/curl, naming sops.
test_ac4_no_sops() {
  local copy t base=/usr/bin:/bin
  copy=$(copy_repo)
  make_shims
  if (PATH="$SHIMS:$base"; command -v sops >/dev/null 2>&1); then
    fail "harness: sops is still found on PATH=$SHIMS:$base, cannot test the no-sops case"
  fi
  for t in $TARGETS; do
    run_make "$copy" "$t" "$base"
    assert_exit_nonzero "make $t (no sops)"
    assert_stderr_mentions "make $t (no sops)" sops
    assert_no_shim_calls "make $t (no sops)"
  done
}

# AC-7 (plaintext half): the committed file reads as the spec's table, and the
# caller's key decrypts it. Decrypted output goes straight to /dev/null.
test_ac7_plaintext_half() {
  local committed k cache
  committed=$(git -C "$REPO" show HEAD:deploy.sops.env 2>/dev/null) ||
    fail "git show HEAD:deploy.sops.env failed: deploy.sops.env is not committed at HEAD"
  printf '%s\n' "$committed" | grep -q '^HOST_CACHE_DIR=' ||
    fail "committed deploy.sops.env: expected a HOST_CACHE_DIR= line, not found"
  cache=$(printf '%s\n' "$committed" | sed -n 's/^HOST_CACHE_DIR=//p' | head -n 1)
  case $cache in
    '') fail "committed deploy.sops.env: expected a non-empty plaintext HOST_CACHE_DIR, got an empty value" ;;
    'ENC['*) fail "committed deploy.sops.env: expected HOST_CACHE_DIR in plaintext, got ENC[...]" ;;
  esac
  for k in LLAMA_SWAP_PORT LLAMA_SWAP_API_KEY HUGGING_FACE_HUB_TOKEN GHCR_TOKEN; do
    printf '%s\n' "$committed" | grep -q "^$k=ENC\[" ||
      fail "committed deploy.sops.env: expected $k=ENC[...], not found"
  done
  printf '%s\n' "$committed" | grep -qF "$TEST_RECIPIENT" ||
    fail "committed deploy.sops.env: expected the test recipient $TEST_RECIPIENT"
  (cd "$REPO" && sops -d deploy.sops.env >/dev/null 2>&1) ||
    fail "sops -d deploy.sops.env: expected exit 0 with the caller's key, got non-zero"
}

# AC-9: placeholders in deploy.sops.env -> make up refuses, names the keys,
# prints no value, calls no docker/curl. The fixture holds the spec's
# "Value in the PR" column (placeholders, not secrets), encrypted for the test recipient.
test_ac9_placeholders_refused() {
  local copy enc all k v
  copy=$(copy_repo)
  make_shims
  enc=$(mktemp -d "$TMP_ROOT/enc.XXXXXX")
  cat > "$enc/plain.env" <<'EOF'
HOST_CACHE_DIR=REPLACE_ME_HOST_CACHE_DIR
LLAMA_SWAP_PORT=8000
LLAMA_SWAP_API_KEY=REPLACE_ME_LLAMA_SWAP_API_KEY
HUGGING_FACE_HUB_TOKEN=REPLACE_ME_HUGGING_FACE_HUB_TOKEN
GHCR_TOKEN=REPLACE_ME_GHCR_TOKEN
EOF
  (cd "$enc" && sops encrypt --age "$TEST_RECIPIENT" --unencrypted-regex '^HOST_CACHE_DIR$' \
    --input-type dotenv --output-type dotenv plain.env) >"$copy/deploy.sops.env" 2>"$enc/err" ||
    fail "harness: could not encrypt the AC-9 fixture: $(one_line "$(cat "$enc/err")")"
  run_make "$copy" up "$PATH"
  assert_exit_nonzero "make up (placeholders)"
  for k in HOST_CACHE_DIR LLAMA_SWAP_API_KEY HUGGING_FACE_HUB_TOKEN GHCR_TOKEN; do
    printf '%s' "$ERR" | grep -q -- "$k" ||
      fail "make up (placeholders): expected stderr to name $k, got: $(one_line "$ERR")"
  done
  all="$OUT
$ERR"
  for k in HOST_CACHE_DIR LLAMA_SWAP_API_KEY HUGGING_FACE_HUB_TOKEN GHCR_TOKEN; do
    v=REPLACE_ME_$k
    case $all in
      *"$v"*) fail "make up (placeholders): output contains the value of $k; expected key names only" ;;
    esac
  done
  assert_no_shim_calls "make up (placeholders)"
}

# --- runner ------------------------------------------------------------------
# `run` expects a pass; `xfail` expects a failure (strict: a pass is an XPASS
# and counts as a failure). Exit 0 iff every test met its expectation.

FAILED=0
run() {
  local msg
  if msg=$("$1" 2>&1); then echo "PASS  $1"
  else echo "FAIL  $1: $msg"; FAILED=1; fi
}
xfail() {
  local msg
  if msg=$("$1" 2>&1); then echo "XPASS $1: expected to fail (strict xfail) but passed"; FAILED=1
  else echo "XFAIL $1: $msg"; fi
}

run test_ac4_no_age_key
run test_ac4_no_sops
run test_ac7_plaintext_half
run test_ac9_placeholders_refused

exit "$FAILED"
