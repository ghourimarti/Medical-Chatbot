#!/usr/bin/env bash
# Make sure the engine's model weights are ON DISK and COMPLETE, without asking anyone.
#
# WHY THIS EXISTS
# ---------------
# Stage 3 of engine startup (image -> container -> WEIGHTS -> load -> serve) is the only
# stage that can half-finish and stay that way. `huggingface_hub` does not resume across
# process restarts: a killed download leaves a `.{uuid}.incomplete` blob, and the next
# attempt writes a NEW one from byte zero. Repeat that a few times and you have gigabytes
# of dead partials, a model that still will not load, and an engine that silently never
# joins the failover chain.
#
# Every recovery step below used to be a docker command a human had to be told to run.
# That is the actual bug: `make up` should leave the stack up.
#
# WHAT IT DOES, in order, cheapest first:
#   1. Already complete?      -> do nothing (the common case; costs one `ls`)
#   2. Complete copy nearby?  -> copy it between volumes (seconds, no network)
#   3. Otherwise              -> download once, cleanly, after clearing dead partials
#
# Step 2 matters more than it looks: this project has accumulated several HF cache volumes
# across sessions (`vllm-hf-cache` from a hand-run container, the compose-managed one, one
# from an older project). The same 5.5GB often already exists a volume away.
set -euo pipefail

MODEL="${1:?usage: ensure_weights.sh <hf-repo-id> <dest-volume>}"
DEST_VOL="${2:?usage: ensure_weights.sh <hf-repo-id> <dest-volume>}"
HF_TOKEN="${HF_TOKEN:-}"

# HF cache dir naming: "Qwen/Qwen2.5-7B-Instruct-AWQ" -> "models--Qwen--Qwen2.5-7B-Instruct-AWQ"
CACHE_DIR="models--${MODEL//\//--}"
BUSYBOX="busybox:1.37"

say() { printf '  %s\n' "$*"; }

# A model is usable when its snapshot has real weight files and no partials are pending.
# Checking the SNAPSHOT rather than the blobs matters: blobs copied without their
# snapshot symlinks are invisible to the loader, which is a failure mode that looks
# exactly like "the download did not happen".
probe() {
  # Completeness is decided by model.safetensors.index.json, NOT by "are there any
  # .safetensors files". That distinction is the whole bug this function was written
  # wrong for once: a sharded model lists every shard in the index weight_map, and a
  # cache holding 1 of 2 shards has files, has no partials, and still cannot load.
  # SGLang says so plainly - "Missing 1 file(s) from index ...['model-00001-of-00002']" -
  # so checking anything less than the index is checking something the engine does not.
  docker run --rm -v "$1:/c" "$BUSYBOX" sh -c '
    D=/c/hub/'"$CACHE_DIR"'
    [ -d "$D" ] || { echo "MISSING 0 0"; exit 0; }
    inc=$(ls "$D"/blobs/ 2>/dev/null | grep -c incomplete || true)
    SNAP=$(ls -d "$D"/snapshots/*/ 2>/dev/null | head -1)
    [ -n "$SNAP" ] || { echo "MISSING 0 $inc"; exit 0; }
    IDX="$SNAP/model.safetensors.index.json"
    if [ -f "$IDX" ]; then
      # Every distinct filename in the weight_map must resolve to a non-empty file.
      want=$(tr -d " 
" < "$IDX" | tr "," "
" | grep -o "model-[0-9]*-of-[0-9]*\.safetensors" | sort -u)
      total=0; have=0
      for f in $want; do
        total=$((total+1))
        [ -s "$SNAP/$f" ] && have=$((have+1))
      done
    else
      # Unsharded model: a single model.safetensors is the whole thing.
      total=1
      have=0; [ -s "$SNAP/model.safetensors" ] && have=1
    fi
    if [ "$have" -eq "$total" ] && [ "$total" -gt 0 ] && [ "$inc" -eq 0 ]; then
      echo "COMPLETE $have/$total $inc"
    elif [ "$have" -gt 0 ]; then echo "PARTIAL $have/$total $inc"
    else echo "MISSING $have/$total $inc"; fi' 2>/dev/null || echo "MISSING 0/0 0"
}

read -r STATE OKF INCF <<<"$(probe "$DEST_VOL")"
say "weights: $MODEL"
say "  $DEST_VOL -> $STATE (shards ${OKF}, ${INCF} partial(s))"

if [ "$STATE" = "COMPLETE" ]; then
  say "  already complete - nothing to do"
  exit 0
fi

# ---- 2. salvage from a sibling volume -------------------------------------------------
CANDIDATES=$(docker volume ls --format '{{.Name}}' 2>/dev/null \
             | grep -iE 'hf|vllm|sglang|model' | grep -vx "$DEST_VOL" || true)
for src in $CANDIDATES; do
  read -r s_state s_ok _ <<<"$(probe "$src")"
  [ "$s_state" = "COMPLETE" ] || continue
  say "  found a COMPLETE copy in '$src' - copying (no download needed)"
  docker run --rm -v "$src:/src:ro" -v "$DEST_VOL:/dst" "$BUSYBOX" sh -c '
    set -e
    M='"$CACHE_DIR"'
    rm -rf "/dst/hub/$M"
    mkdir -p /dst/hub
    # -a preserves the snapshot symlinks; copying blobs alone would not load.
    cp -a "/src/hub/$M" /dst/hub/
    rm -f "/dst/hub/$M"/blobs/*.incomplete 2>/dev/null || true'
  read -r STATE OKF INCF <<<"$(probe "$DEST_VOL")"
  if [ "$STATE" = "COMPLETE" ]; then
    say "  salvaged from '$src' - $OKF weight file(s), 0 partials"
    exit 0
  fi
  say "  copy from '$src' did not complete it; continuing"
done

# ---- 3. download, once, cleanly -------------------------------------------------------
if [ "$INCF" -gt 0 ]; then
  say "  clearing $INCF dead partial(s) - they cannot be resumed, only re-downloaded"
  docker run --rm -v "$DEST_VOL:/c" "$BUSYBOX" \
    sh -c 'rm -f /c/hub/'"$CACHE_DIR"'/blobs/*.incomplete 2>/dev/null || true'
fi

[ -n "$HF_TOKEN" ] || say "  NOTE: no HF_TOKEN - anonymous pulls are throttled (~0.4MB/s)"
say "  downloading ~5.5GB in ONE uninterrupted run. Do not interrupt or re-run make up."

# Runs in an image that is already present, so this never adds a pull of its own.
IMG=$(docker images --format '{{.Repository}}:{{.Tag}}' \
      | grep -E '^(lmsysorg/sglang|vllm/vllm-openai):' | head -1)
IMG="${IMG:-python:3.13-slim}"

FETCH_CTR="medbot-weight-fetch"

# A FIXED name is the whole point. Anonymous `docker run` containers survive the CLI that
# started them, so every interrupted `make up` left a live downloader behind and the next
# run started a rival. Three were once found pulling the same repo into the same volume -
# which is exactly how a cache ends up with one shard of two and unresumable partials.
if [ "$(docker inspect -f '{{.State.Running}}' "$FETCH_CTR" 2>/dev/null)" = "true" ]; then
  say "  a download is ALREADY in flight ($FETCH_CTR) - waiting for it, not racing it"
else
  docker rm -f "$FETCH_CTR" >/dev/null 2>&1 || true
  # Detached, so a Ctrl-C here leaves an ADOPTABLE container rather than an invisible one.
  # The model arrives as a positional arg ($1 inside the container) to dodge quote nesting.
  docker run -d --name "$FETCH_CTR" --entrypoint sh -e HF_TOKEN="$HF_TOKEN" -v "$DEST_VOL:/root/.cache/huggingface" "$IMG" -c 'pip install -q huggingface_hub >/dev/null 2>&1 || true; exec python3 -c "
import sys
from huggingface_hub import snapshot_download
snapshot_download(sys.argv[1], max_workers=8)
" "$1"' _ "$MODEL" >/dev/null
fi

# huggingface_hub suppresses its progress bar without a TTY, so a 5.5GB pull would look
# identical to a hang for twenty minutes. Report bytes-on-disk instead - it is the number
# that actually tells you whether anything is moving.
while [ "$(docker inspect -f '{{.State.Running}}' "$FETCH_CTR" 2>/dev/null)" = "true" ]; do
  sz=$(docker run --rm -v "$DEST_VOL:/c" "$BUSYBOX" du -sh "/c/hub/$CACHE_DIR" 2>/dev/null | cut -f1)
  say "  downloading... ${sz:-0} on disk"
  sleep 30
done
RC=$(docker wait "$FETCH_CTR" 2>/dev/null || echo 1)
if [ "$RC" != "0" ]; then
  say "  download container exited $RC:"
  docker logs --tail 15 "$FETCH_CTR" 2>&1 | sed "s/^/    /" || true
fi
docker rm -f "$FETCH_CTR" >/dev/null 2>&1 || true

read -r STATE OKF INCF <<<"$(probe "$DEST_VOL")"
if [ "$STATE" != "COMPLETE" ]; then
  say "  STILL NOT COMPLETE after downloading ($STATE, $INCF partial(s))."
  say "  Re-run 'make weights-ensure' - it resumes from whatever landed."
  exit 1
fi
say "  weights ready - $OKF weight file(s), 0 partials"
