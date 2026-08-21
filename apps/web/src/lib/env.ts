import "server-only";

/**
 * SERVER-ONLY configuration. The `server-only` import makes a browser import a BUILD
 * error, not a convention: if the API's address ever reached the client bundle, the
 * browser could dial it directly and we would be back to needing CORS — the exact
 * problem D23 chose the BFF proxy to eliminate.
 *
 * Note there is deliberately NO `NEXT_PUBLIC_` variant of this value.
 */
export const API_BASE_URL = (process.env.API_BASE_URL ?? "http://localhost:5007").replace(
  /\/+$/,
  "",
);

/** Upstream cap. Generation can legitimately take tens of seconds; a short default
 *  timeout would abort healthy long answers and look like a backend failure. */
export const UPSTREAM_TIMEOUT_MS = Number(process.env.UPSTREAM_TIMEOUT_MS ?? 120_000);
