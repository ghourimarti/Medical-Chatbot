/**
 * SYSTEM load test (P5.2) — the API, not the serving engine.
 *
 * S14 measured the engine. This measures everything around it: FastAPI's async loop,
 * Redis cache, Postgres writes, session handling, guardrails, and rate limiting.
 *
 * TWO TIERS, built from what already exists rather than new stub infrastructure:
 *
 *   TIER=cache  Warm one query, then hammer it. Every request is a cache hit, so no
 *               embedding, retrieval, reranking, or generation runs. This is the
 *               "provider stubbed" tier — it measures the HTTP/async/Redis ceiling.
 *
 *   TIER=full   Unique questions, so every request misses cache and traverses the real
 *               pipeline. Saturates on CPU reranking (~800ms, measured in S6).
 *
 *   TIER=guard  Unsafe prompts only. These are refused BEFORE embedding, so this measures
 *               how cheaply the system rejects abuse — the thing that matters when the
 *               abuse is the load (D18/D20).
 *
 * Usage:
 *   k6 run -e TIER=cache -e PEAK_RATE=200 tests/load/system_load.js
 *   k6 run -e TIER=full  -e PEAK_RATE=10  tests/load/system_load.js
 *   k6 run -e TIER=guard -e PEAK_RATE=200 tests/load/system_load.js
 */
import http from 'k6/http';
import { check } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://localhost:1107';
const TIER = __ENV.TIER || 'cache';
const PEAK_RATE = parseInt(__ENV.PEAK_RATE || '50', 10);
const DURATION = __ENV.DURATION || '30s';

const kindGrounded = new Counter('answers_grounded');
const kindRefused = new Counter('answers_refused');
const kindDegraded = new Counter('answers_degraded');
const rateLimited = new Counter('rate_limited_429');
const cacheHits = new Rate('cache_hit_rate');
const serverLatency = new Trend('server_reported_total_ms');
// Split wall-clock latency by cache outcome. Mixing them makes the summary meaningless:
// a run that is 47% cache hits reports a median drawn from the hits and a server-side
// median drawn from the misses, so "wall < server" appears and neither number describes a
// real request. Same population, or no comparison.
const missLatency = new Trend('wall_ms_cache_miss');
const hitLatency = new Trend('wall_ms_cache_hit');
// wall - server_total: work the pipeline instrumentation does NOT attribute to any stage
// (guardrails, cache, history, serialization, framework). If this is large, the timing
// breakdown users see is lying by omission.
const unattributed = new Trend('unattributed_ms');

const CACHED_QUESTION = 'What is an abscess?';
// Real golden-set questions for TIER=full. Synthetic gibberish would retrieve nothing and
// produce short no-answers, understating both generation time and token cost — the
// measurement would look good precisely because the work never happened.
const REAL_QUESTIONS = JSON.parse(open('./questions.json'));
const UNSAFE = [
  'How many mg of ibuprofen should I take?',
  'I have chest pain and my left arm feels numb',
  'Should I stop taking my prescribed blood pressure medication?',
  'Based on my symptoms, do I have diabetes?',
];

export const options = {
  scenarios: {
    load: {
      executor: 'ramping-arrival-rate',
      startRate: 1,
      timeUnit: '1s',
      preAllocatedVUs: 50,
      maxVUs: 400,
      stages: [
        { target: Math.max(1, Math.round(PEAK_RATE * 0.2)), duration: '15s' },
        { target: Math.max(1, Math.round(PEAK_RATE * 0.5)), duration: '15s' },
        { target: PEAK_RATE, duration: DURATION },
      ],
    },
  },
  thresholds: {
    // Phase-1 NFRs expressed as gates. A load test that cannot fail is a demo.
    http_req_failed: ['rate<0.02'],
    'http_req_duration{expected_response:true}': ['p(95)<12000'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function question() {
  if (TIER === 'cache') return CACHED_QUESTION;
  if (TIER === 'guard') return UNSAFE[Math.floor(Math.random() * UNSAFE.length)];
  // 'full': real questions, drawn round-robin. Flush the response cache before the run so
  // the first pass through the set is all misses; the reported cache-hit rate makes any
  // subsequent repeats self-documenting rather than a hidden inflation of the result.
  return REAL_QUESTIONS[(__VU * 7919 + __ITER) % REAL_QUESTIONS.length];
}

export function setup() {
  // Warm the cache for TIER=cache. Without this the first requests all miss and the
  // early samples measure the full pipeline — skewing exactly the number we want clean.
  if (TIER === 'cache') {
    const r = http.post(
      `${BASE}/api/v1/query`,
      JSON.stringify({ question: CACHED_QUESTION, stream: false }),
      { headers: { 'Content-Type': 'application/json' }, timeout: '120s' },
    );
    return { warmed: r.status === 200 };
  }
  return { warmed: false };
}

export default function () {
  const res = http.post(
    `${BASE}/api/v1/query`,
    JSON.stringify({ question: question(), stream: false }),
    {
      headers: { 'Content-Type': 'application/json' },
      timeout: '120s',
      tags: { tier: TIER },
    },
  );

  if (res.status === 429) {
    rateLimited.add(1);
    return; // a throttled request is a correct outcome, not a failure
  }

  const ok = check(res, {
    'status 200': (r) => r.status === 200,
    'has answer kind': (r) => {
      try {
        return !!r.json('kind');
      } catch (e) {
        return false;
      }
    },
  });
  if (!ok) return;

  try {
    const kind = res.json('kind');
    if (kind === 'grounded') kindGrounded.add(1);
    else if (kind === 'refused') kindRefused.add(1);
    else if (kind === 'degraded') kindDegraded.add(1);
    const hit = res.json('cache_hit') === true;
    cacheHits.add(hit);
    if (hit) hitLatency.add(res.timings.duration);
    else missLatency.add(res.timings.duration);
    const total = res.json('timings.total_ms');
    if (total) {
      serverLatency.add(total);
      if (!hit) unattributed.add(res.timings.duration - total);
    }
  } catch (e) {
    // response shape already validated above
  }
}

export function handleSummary(data) {
  const m = data.metrics;
  const v = (n, s) => (m[n] && m[n].values ? m[n].values[s] : null);
  const f = (x, d = 0) => (x === null || x === undefined ? 'n/a' : x.toFixed(d));
  const count = (n) => (m[n] && m[n].values ? m[n].values.count : 0);

  const achievedRps = v('http_reqs', 'rate');
  const text = [
    ``,
    `=== SYSTEM LOAD: tier=${TIER} target_peak=${PEAK_RATE} RPS ===`,
    `achieved:    ${f(achievedRps, 1)} RPS over ${f(v('http_reqs', 'count'), 0)} requests`,
    `failed:      ${f((v('http_req_failed', 'rate') || 0) * 100, 2)}%   429s: ${count('rate_limited_429')}`,
    `latency:     med ${f(v('http_req_duration', 'med'))}ms  p95 ${f(v('http_req_duration', 'p(95)'))}ms  p99 ${f(v('http_req_duration', 'p(99)'))}ms`,
    `server-side: med ${f(v('server_reported_total_ms', 'med'))}ms  p95 ${f(v('server_reported_total_ms', 'p(95)'))}ms`,
    `wall (miss): med ${f(v('wall_ms_cache_miss', 'med'))}ms  p95 ${f(v('wall_ms_cache_miss', 'p(95)'))}ms   (hit med ${f(v('wall_ms_cache_hit', 'med'))}ms)`,
    `unattribtd:  med ${f(v('unattributed_ms', 'med'))}ms  p95 ${f(v('unattributed_ms', 'p(95)'))}ms  <- wall minus instrumented stages`,
    `answers:     grounded=${count('answers_grounded')} refused=${count('answers_refused')} degraded=${count('answers_degraded')}`,
    `cache hits:  ${f((v('cache_hit_rate', 'rate') || 0) * 100, 1)}%`,
    ``,
  ].join('\n');

  return {
    stdout: text,
    [`eval-reports/load-${TIER}.json`]: JSON.stringify(
      {
        tier: TIER,
        target_peak_rps: PEAK_RATE,
        achieved_rps: achievedRps,
        requests: v('http_reqs', 'count'),
        failed_rate: v('http_req_failed', 'rate'),
        rate_limited: count('rate_limited_429'),
        latency_ms: {
          med: v('http_req_duration', 'med'),
          p95: v('http_req_duration', 'p(95)'),
          p99: v('http_req_duration', 'p(99)'),
        },
        answers: {
          grounded: count('answers_grounded'),
          refused: count('answers_refused'),
          degraded: count('answers_degraded'),
        },
        cache_hit_rate: v('cache_hit_rate', 'rate'),
      },
      null,
      2,
    ),
  };
}
