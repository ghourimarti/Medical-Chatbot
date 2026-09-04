#!/usr/bin/env bash
# Check there is enough RAM to LOAD an engine before spending 20 minutes finding out there
# is not.
#
# WHY: `docker compose up --wait` reports a timeout when the engine never becomes healthy,
# and a timeout reads as "be patient". But an engine that gets SIGKILLed at minute 3 will
# never become healthy no matter how long the wait is. The failure is knowable up front:
# weight bytes on disk are a good lower bound on the host RAM the load needs, and the
# Docker VM's available memory is a number we can simply read.
set -uo pipefail

MODEL="${1:?usage: engine_preflight.sh <hf-repo-id> <dest-volume>}"
DEST_VOL="${2:?usage: engine_preflight.sh <hf-repo-id> <dest-volume>}"
CACHE_DIR="models--${MODEL//\//--}"
BUSYBOX="busybox:1.37"

SVC="${3:-}"
[ "$SVC" = "both" ] && SVC="vllm sglang"
[ "$SVC" = "none" ] && exit 0

# An engine that is ALREADY running has already paid its memory cost - the weights are
# resident. Re-checking "is there room to load it?" against the memory it is itself
# consuming is how a working stack gets refused by its own safety check. Idempotent
# `make up` on a live stack must be a no-op, not a failure.
for s in ${SVC:-vllm sglang}; do
  case "$s" in vllm|sglang) ;; *) continue ;; esac
  if [ "$(docker inspect -f "{{.State.Running}}" "p5-medical-chatbot-${s}-1" 2>/dev/null)" = "true" ]; then
    echo "  memory preflight: ${s} is already running - weights are resident, skipping"
    exit 0
  fi
done

AVAIL=$(docker run --rm "$BUSYBOX" free -m 2>/dev/null | awk '/^Mem:/{print $7}')
TOTAL=$(docker run --rm "$BUSYBOX" free -m 2>/dev/null | awk '/^Mem:/{print $2}')
[ -n "${AVAIL:-}" ] || exit 0   # cannot measure -> do not block the user on a guess

# Weights are read into CPU memory before they reach the GPU, plus runtime overhead for the
# server, CUDA context and KV allocator. 1.4x the checkpoint has matched observed peaks here.
WEIGHTS=$(docker run --rm -v "$DEST_VOL:/c" "$BUSYBOX" \
          du -sm "/c/hub/$CACHE_DIR" 2>/dev/null | cut -f1)
WEIGHTS="${WEIGHTS:-5200}"
NEED=$(( WEIGHTS * 14 / 10 + 1500 ))

printf '  memory preflight: %s MiB available of %s MiB, engine needs ~%s MiB\n' \
       "$AVAIL" "$TOTAL" "$NEED"

if [ "$AVAIL" -ge "$NEED" ]; then
  exit 0
fi

echo ""
echo "  NOT ENOUGH MEMORY to load the engine. Starting it now would end in exit 137"
echo "  (SIGKILL by the OOM killer) after several minutes of apparently normal startup."
echo ""
if [ ! -f "$USERPROFILE/.wslconfig" ] && [ ! -f "$HOME/.wslconfig" ]; then
  echo "  No .wslconfig found: WSL2 is capping the Docker VM at half your host RAM."
fi
echo "  Fix, in order of preference:"
echo "    1. Raise the VM ceiling (survives reboots, fixes this for good):"
echo "         edit %USERPROFILE%\.wslconfig  ->  [wsl2]  memory=22GB"
echo "         wsl --shutdown     # then reopen Docker Desktop"
echo "    2. Free memory now, engine only:"
echo "         make down KIND=1 && make up-engine"
echo "    3. Run hosted-only for this session:"
echo "         make up ENGINE=none"
echo ""
echo "  Override this check if you believe it is wrong:  make up SKIP_MEM_CHECK=1"
exit 1
