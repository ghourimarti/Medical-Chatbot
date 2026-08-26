#!/bin/sh
# Register every Redis instance in RedisInsight so nobody adds connections by hand (T7).
#
# WHY A SEEDER AND NOT RI_REDIS_* ENV VARS: those pre-add exactly ONE database. This stack
# already has an app cache and will gain a Langfuse cache the moment it moves to Langfuse
# v3 (which uses Redis + ClickHouse; v2, running here, is Postgres-only). A loop over a
# list handles both cases and is idempotent, so `make up` twice does not create duplicates.
set -eu

RI_URL="${RI_URL:-http://redisinsight:5540}"

# name|host|port  — add a line per instance.
DATABASES="${REDISINSIGHT_DATABASES:-medbot-cache|redis|6379}"

echo "redisinsight-seed: waiting for ${RI_URL}"
i=0
until wget -q -O /dev/null "${RI_URL}/api/health" 2>/dev/null || [ "$i" -ge 60 ]; do
  i=$((i + 1)); sleep 2
done
if [ "$i" -ge 60 ]; then
  echo "redisinsight-seed: RedisInsight never became ready; skipping (UI still works)" >&2
  exit 0   # a seeding failure must not take the observability tier down with it
fi

existing="$(wget -q -O - "${RI_URL}/api/databases" 2>/dev/null || echo '[]')"

echo "$DATABASES" | tr ',' '\n' | while IFS='|' read -r name host port; do
  [ -z "${name:-}" ] && continue
  case "$existing" in
    *"\"name\":\"${name}\""*)
      echo "redisinsight-seed: '${name}' already registered — leaving it alone"
      continue
      ;;
  esac
  echo "redisinsight-seed: adding '${name}' -> ${host}:${port}"
  # name/host/port ONLY. connectionType is a RESPONSE field, not a request one, and
  # sending it makes RedisInsight reject the payload with a bare 400 naming no field --
  # which is exactly how this failed the first time. It infers STANDALONE itself.
  wget -q -O /dev/null --header='Content-Type: application/json' \
    --post-data="{\"name\":\"${name}\",\"host\":\"${host}\",\"port\":${port}}" \
    "${RI_URL}/api/databases" \
    && echo "redisinsight-seed: '${name}' added" \
    || echo "redisinsight-seed: '${name}' FAILED to add (UI still works; add it manually)" >&2
done

echo "redisinsight-seed: done"
