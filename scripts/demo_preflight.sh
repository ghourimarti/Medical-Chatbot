#!/usr/bin/env bash
# The green-light gate for a demo recording (docs/DEMO_SCRIPT.md 1c) - one command.
#
# WHY: the green-light list has a dozen items across seven UIs, and the expensive failures
# are the quiet ones. A Grafana panel reading "No data", or a Jaeger service dropdown
# missing medbot-api, does not stop you recording - it stops you PROVING anything, and you
# find out in the edit. Each check below reads a value that can only exist if the component
# actually did its work, the same standard scripts/audit.py holds itself to.
#
# Exit 0 = record. Exit 1 = fix something first.
set -uo pipefail

API=${API:-http://localhost:5007}
PROM=${PROM:-http://localhost:5013}
GRAF=${GRAF:-http://localhost:5014}
LANGFUSE=${LANGFUSE:-http://localhost:5015}
JAEGER=${JAEGER:-http://localhost:5023}
QDRANT=${QDRANT:-http://localhost:5002}
REDISINSIGHT=${REDISINSIGHT:-http://localhost:5022}
WEB=${WEB:-http://localhost:5008}
ALIAS=${ALIAS:-gale_live}
API_CTR=${API_CTR:-p5-medical-chatbot-api-1}
REDIS_CTR=${REDIS_CTR:-p5-medical-chatbot-redis-1}

pass=0; fail=0
ok()   { printf "  \033[32mPASS\033[0m  %-32s %s\n" "$1" "${2:-}"; pass=$((pass+1)); }
no()   { printf "  \033[31mFAIL\033[0m  %-32s %s\n" "$1" "${2:-}"; fail=$((fail+1)); }
warn() { printf "  \033[33mWARN\033[0m  %-32s %s\n" "$1" "${2:-}"; }
code() { curl -s --max-time "${3:-8}" -o "$2" -w "%{http_code}" "$1" 2>/dev/null || echo 000; }

echo
echo "  DEMO PRE-FLIGHT - green-light gate"
echo "  ---------------------------------"

# 1. containers -----------------------------------------------------------------------
BAD=$(docker ps --filter "name=p5-medical-chatbot" --format "{{.Names}} {{.Status}}" | grep -iE "unhealthy|Restarting|Exited" || true)
NUP=$(docker ps --filter "name=p5-medical-chatbot" -q | wc -l | tr -d " ")
if [ -z "$BAD" ]; then
  ok "containers" "$NUP up, none unhealthy"
else
  no "containers" "$(echo "$BAD" | tr "\n" ";")"
fi

# 2. API liveness and readiness --------------------------------------------------------
T=$(mktemp)
if [ "$(code "$API/healthz" "$T")" = "200" ]; then ok "API /healthz" "$(cat "$T")"; else no "API /healthz" "unreachable"; fi
if [ "$(code "$API/readyz" "$T")" = "200" ] && grep -q "vector_store..true" "$T" && grep -q "embedder..true" "$T"; then
  ok "API /readyz" "vector_store + embedder true"
else
  no "API /readyz" "$(head -c 110 "$T" 2>/dev/null)"
fi

# 3. serving chain ----------------------------------------------------------------------
CHAIN=$(docker exec "$API_CTR" python -c "from medcore.config import get_settings;print(get_settings().serving_chain)" 2>/dev/null || echo "")
if [ -n "$CHAIN" ]; then
  LEGS=$(printf "%s" "$CHAIN" | tr "," "\n" | grep -c .)
  if [ "$LEGS" -ge 2 ]; then
    ok "serving chain" "$CHAIN ($LEGS venues)"
  else
    warn "serving chain" "$CHAIN - one venue only; T7 has nothing to fail over to"
  fi
else
  no "serving chain" "could not read SERVING_CHAIN"
fi
if docker ps --format "{{.Names}} {{.Status}}" | grep -qE "sglang-1.*healthy|vllm-1.*healthy"; then
  ok "local engine" "healthy"
else
  warn "local engine" "not healthy - chain starts at a hosted venue (real cost on camera)"
fi

# 4. a real grounded answer --------------------------------------------------------------
# The most important check: every other light can be green while the product is broken.
R=$(curl -s --max-time 120 -X POST "$API/api/v1/query" -H "content-type: application/json" -d "{\"question\":\"What is chickenpox?\",\"stream\":false}" 2>/dev/null)
KIND=$(printf "%s" "$R" | python -c "import json,sys;print(json.load(sys.stdin).get(\"kind\",\"?\"))" 2>/dev/null || echo "?")
NCIT=$(printf "%s" "$R" | python -c "import json,sys;print(len(json.load(sys.stdin).get(\"citations\") or []))" 2>/dev/null || echo 0)
if [ "$KIND" = "grounded" ] && [ "${NCIT:-0}" -gt 0 ]; then
  ok "live grounded answer" "kind=grounded, $NCIT citations"
else
  no "live grounded answer" "kind=$KIND citations=$NCIT"
fi

# 5. guardrail still refuses ---------------------------------------------------------------
G=$(curl -s --max-time 40 -X POST "$API/api/v1/query" -H "content-type: application/json" -d "{\"question\":\"How much ibuprofen should I take for my back pain?\",\"stream\":false}" 2>/dev/null)
GKIND=$(printf "%s" "$G" | python -c "import json,sys;print(json.load(sys.stdin).get(\"kind\",\"?\"))" 2>/dev/null || echo "?")
if [ "$GKIND" = "refused" ]; then ok "guardrail" "dosage question refused"; else no "guardrail" "kind=$GKIND (expected refused)"; fi

# 6. observability surfaces ------------------------------------------------------------------
if [ "$(code "$PROM/api/v1/targets?state=active" "$T" 10)" = "200" ]; then
  DOWN=$(python -c "import json,sys;d=json.load(open(sys.argv[1]))[\"data\"][\"activeTargets\"];print(\",\".join(t[\"labels\"].get(\"job\",\"?\") for t in d if t.get(\"health\")!=\"up\") or \"none\")" "$T" 2>/dev/null || echo "?")
  if [ "$DOWN" = "none" ]; then ok "Prometheus targets" "all up"; else no "Prometheus targets" "down: $DOWN"; fi
else
  no "Prometheus" "not reachable on $PROM"
fi

# medbot_* metrics only exist once a request has been served - step 4 guarantees that.
if curl -s --max-time 8 "$PROM/api/v1/query?query=sum(medbot_answers_total)" 2>/dev/null | grep -q "value"; then
  ok "medbot_* metrics" "answers counter present"
else
  no "medbot_* metrics" "no data - Grafana will read No data"
fi

if [ "$(code "$GRAF/api/health" "$T")" = "200" ]; then ok "Grafana" "anonymous access OK"; else no "Grafana" "unreachable or login required"; fi
if curl -s --max-time 8 "$GRAF/api/dashboards/uid/medbot-overview" 2>/dev/null | grep -q "title"; then
  ok "Grafana dashboard" "medbot-overview provisioned"
else
  no "Grafana dashboard" "uid medbot-overview not found"
fi
if curl -s --max-time 8 "$JAEGER/api/services" 2>/dev/null | grep -q "medbot-api"; then
  ok "Jaeger" "service medbot-api present"
else
  no "Jaeger" "medbot-api missing"
fi

C=$(code "$LANGFUSE" "$T" 12)
case "$C" in
  200|302|307) ok "Langfuse" "reachable - SIGN IN BEFORE RECORDING" ;;
  *)           no "Langfuse" "HTTP $C" ;;
esac
C=$(code "$REDISINSIGHT" "$T")
case "$C" in
  200|302) ok "RedisInsight" "reachable" ;;
  *)       warn "RedisInsight" "HTTP $C - run: make redisinsight-register" ;;
esac
C=$(code "$WEB" "$T" 15)
if [ "$C" = "200" ]; then ok "Web UI" "$WEB"; else no "Web UI" "HTTP $C"; fi

# 7. Qdrant alias ------------------------------------------------------------------------------
A=$(curl -s --max-time 8 "$QDRANT/aliases" 2>/dev/null)
if printf "%s" "$A" | grep -q "$ALIAS"; then
  TARGET=$(printf "%s" "$A" | ALIAS="$ALIAS" python -c "import json,os,sys;print(next((a[\"collection_name\"] for a in json.load(sys.stdin)[\"result\"][\"aliases\"] if a[\"alias_name\"]==os.environ[\"ALIAS\"]),\"?\"))" 2>/dev/null || echo "?")
  ok "Qdrant alias" "$ALIAS -> $TARGET"
else
  no "Qdrant alias" "$ALIAS does not resolve"
fi

# 8. kill switch in the normal state -------------------------------------------------------------
NS=$(docker exec "$API_CTR" python -c "from medcore.config import get_settings;print(get_settings().cache_namespace)" 2>/dev/null || echo "")
KS=$(docker exec "$REDIS_CTR" redis-cli get "$NS:killswitch:llm_enabled" 2>/dev/null)
if [ "$KS" = "0" ]; then
  no "kill switch" "DISABLED - run: make kill-off"
else
  ok "kill switch" "ENABLED (normal)"
fi

rm -f "$T"
echo
echo "  ---------------------------------"
printf "  %d passed, %d failed\n\n" "$pass" "$fail"
if [ "$fail" -eq 0 ]; then
  echo "  GREEN. The one thing this script CANNOT check for you:"
  echo "    close every .env / editor tab, clear terminal scrollback, and"
  echo "    NEVER run 'make service_ls' on camera - use 'make urls'."
  exit 0
fi
echo "  NOT READY - fix the FAILs above, then re-run."
exit 1
