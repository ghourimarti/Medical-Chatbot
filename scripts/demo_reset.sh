#!/usr/bin/env bash
# Reset the stack between demo takes WITHOUT destroying anything (docs/DEMO_SCRIPT.md 1g).
#
# WHY this exists rather than `make downv` or `make cache-flush`: both of those are
# destructive and neither is what a retake needs. A retake needs exactly three things
# undone — a warm answer cache (so a "cold" take is genuinely cold), a kill switch left
# on by the T6 take, and an /etc/hosts left blackholed by a chain-drill that was
# interrupted mid-run. Everything else — volumes, rate-limit counters, the vector index,
# conversation history — must survive, because rebuilding them costs 20+ minutes and the
# rate-limit counters are themselves demo material.
#
# The /etc/hosts restore is the important one. chain_drill.py always restores on its own
# exit path, but Ctrl-C during a take can outrun it, and the symptom (one venue silently
# unreachable) looks exactly like a real failover on camera.
set -uo pipefail

API_CTR="${API_CTR:-p5-medical-chatbot-api-1}"
REDIS_CTR="${REDIS_CTR:-p5-medical-chatbot-redis-1}"
HOSTS_BAK="/tmp/hosts.medbot.bak"   # written by scripts/chain_drill.py

fail=0
say() { printf '  %s\n' "$*"; }

# --- 1. Undo any interrupted chain-drill -------------------------------------------
if docker exec "$API_CTR" test -f "$HOSTS_BAK" 2>/dev/null; then
  if docker exec -u root "$API_CTR" sh -c "cp $HOSTS_BAK /etc/hosts" 2>/dev/null; then
    say "/etc/hosts restored from chain-drill backup"
  else
    say "WARN could not restore /etc/hosts - run 'make chain-drill' to reset it"; fail=1
  fi
else
  say "/etc/hosts clean (no chain-drill backup present)"
fi

# --- 2. Kill switch back to the normal state ---------------------------------------
NS=$(docker exec "$API_CTR" python -c \
  "from medcore.config import get_settings;print(get_settings().cache_namespace)" 2>/dev/null) || NS=""
if [ -z "$NS" ]; then
  say "ERROR could not read cache namespace - is the API container up?"; exit 1
fi
docker exec "$REDIS_CTR" redis-cli del "$NS:killswitch:llm_enabled" >/dev/null 2>&1
say "kill switch OFF (generation enabled)"

# --- 3. Clear cached ANSWERS only ---------------------------------------------------
# Same pattern as `make cache-clear`. Embedding cache is deliberately KEPT: it does not
# affect whether an answer take looks cold, and re-embedding the corpus queries wastes
# GPU time between takes.
KEYS=$(docker exec "$REDIS_CTR" redis-cli --scan --pattern "$NS:ans:*" 2>/dev/null)
COUNT=$(printf '%s' "$KEYS" | grep -c . || true)
if [ -n "$KEYS" ]; then
  printf '%s\n' "$KEYS" | xargs -r docker exec -i "$REDIS_CTR" redis-cli del >/dev/null 2>&1
fi
say "cleared ${COUNT:-0} cached answers (embeddings and rate limits kept)"

# --- 4. Report the state you are about to record ------------------------------------
echo
say "state for the next take:"
docker exec "$REDIS_CTR" redis-cli --scan --pattern "$NS:*" 2>/dev/null \
  | sed "s|$NS:||; s|:.*||" | sort | uniq -c | sed 's/^/    /'
echo
say "NOT touched: volumes, vector index, conversation history, rate-limit counters"
exit $fail
