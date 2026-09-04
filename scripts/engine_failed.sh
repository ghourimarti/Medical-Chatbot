#!/usr/bin/env bash
# Explain WHY an engine did not reach SERVING. Called only on the failure path.
#
# It exists because the first version of this message asserted "the container is still
# running - this is a timeout, not a crash" while the container had in fact been SIGKILLed.
# A diagnostic that guesses is worse than none: it sends you to watch the logs of a
# container that is not there.
set -uo pipefail

ARG="${1:?usage: engine_failed.sh <vllm|sglang|both> <timeout>}"
WAITED="${2:-?}"

# ENGINE=both starts two containers; either one can be the one that failed.
case "$ARG" in both) SERVICES="vllm sglang";; *) SERVICES="$ARG";; esac

for SVC in $SERVICES; do
CTR="p5-medical-chatbot-${SVC}-1"
echo ""
STATE=$(docker inspect "$CTR" --format '{{.State.Status}}' 2>/dev/null || echo "gone")
CODE=$(docker inspect "$CTR" --format '{{.State.ExitCode}}' 2>/dev/null || echo "?")
OOM=$(docker inspect "$CTR" --format '{{.State.OOMKilled}}' 2>/dev/null || echo "false")

case "$STATE" in
  running)
    echo "  ${SVC} is RUNNING but not serving yet (waited ${WAITED}s)."
    echo "  Loading weights legitimately takes minutes; a cold download takes longer."
    echo "    watch:  docker logs -f ${CTR}"
    echo "    retry:  make ${SVC}-up ENGINE_WAIT=3600"
    ;;
  exited|dead)
    if [ "$CODE" = "137" ] || [ "$OOM" = "true" ]; then
      TOTAL=$(docker run --rm busybox:1.37 free -m 2>/dev/null | awk '/^Mem:/{print $2}')
      AVAIL=$(docker run --rm busybox:1.37 free -m 2>/dev/null | awk '/^Mem:/{print $7}')
      echo "  ${SVC} was KILLED (exit 137 = SIGKILL). This is almost always the OOM killer,"
      echo "  and it is a MEMORY problem, not a timeout - waiting longer cannot fix it."
      echo ""
      echo "    Docker VM memory: ${TOTAL:-?} MiB total, ${AVAIL:-?} MiB available"
      echo ""
      echo "  Loading a 7B AWQ model reads ~5.5GB into CPU RAM before it reaches the GPU,"
      echo "  on top of whatever the rest of the stack is holding. On WSL2 the Docker VM"
      echo "  defaults to HALF the host RAM, which is the usual reason this does not fit."
      echo ""
      echo "  Pick one:"
      echo "    A. Free memory, then retry:"
      echo "         make down KIND=1        # stop the app + observability + kind nodes"
      echo "         make ${SVC}-up          # engine alone, with the VM to itself"
      echo "    B. Give the Docker VM more RAM (host has more to give):"
      echo "         edit %USERPROFILE%\.wslconfig ->  [wsl2]  memory=24GB"
      echo "         wsl --shutdown           # then restart Docker Desktop"
      echo "    C. Use the hosted chain for now:"
      echo "         make up ENGINE=none"
    else
      echo "  ${SVC} EXITED with code ${CODE} - it crashed rather than timed out."
      echo "    logs:   docker logs ${CTR} 2>&1 | tail -40"
    fi
    ;;
  *)
    echo "  ${SVC} container is ${STATE}; it may have been removed."
    echo "    retry:  make ${SVC}-up"
    ;;
esac
done

echo ""
echo "  Never re-run 'make up' while a weight DOWNLOAD is in flight: huggingface_hub does"
echo "  not resume across process restarts, so the partial is discarded (S3b blocker #3)."
echo ""
