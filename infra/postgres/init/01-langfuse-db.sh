#!/bin/sh
# Create the `langfuse` database next to the app's own.
#
# Langfuse stores prompt/completion CONTENT (D18 makes it the one sanctioned place for it),
# so it needs a real database — but it does not need a second Postgres server. A separate
# DATABASE keeps its tables out of the app's schema while sharing one container.
#
# ⚠ Postgres runs /docker-entrypoint-initdb.d ONLY on an empty data volume. Changing this
# file does nothing to an existing volume; you need `make downv` (which destroys local data).
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE langfuse'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
EOSQL
echo "init: ensured database 'langfuse' exists"
