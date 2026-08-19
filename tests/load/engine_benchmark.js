/**
 * Serving-engine benchmark under CONCURRENCY (S14, D12).
 *
 * WHY THIS EXISTS ALONGSIDE scripts/bench_venue.py:
 *   bench_venue.py measures SEQUENTIAL latency — what one request costs when nothing else
 *   is happening. That is not a benchmark of a serving engine. Continuous batching,
 *   KV-cache pressure, and admission queueing only appear when requests OVERLAP, and that
 *   is precisely where vLLM and SGLang differ. Measured sequentially they look identical.
 *
 * Works against ANY OpenAI-compatible endpoint (local vLLM, SGLang, RunPod, AWS, Groq),
 * so venues and engines are compared on identical load — the same protocol uniformity
 * that made D4b cheap to build.
 *
 * Usage:
 *   k6 run -e BASE_URL=http://localhost:1110/v1 -e MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ \
 *          -e LABEL=local-vllm tests/load/engine_benchmark.js
 *   k6 run -e BASE_URL=https://api.groq.com/openai/v1 -e MODEL=llama-3.1-8b-instant \
 *          -e API_KEY=$GROQ_API_KEY -e LABEL=groq tests/load/engine_benchmark.js
 */
import http from 'k6/http';
import { check } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:1110/v1';
const MODEL = __ENV.MODEL || 'Qwen/Qwen2.5-7B-Instruct-AWQ';
const API_KEY = __ENV.API_KEY || '';
const LABEL = __ENV.LABEL || 'unlabelled';
const MAX_TOKENS = parseInt(__ENV.MAX_TOKENS || '128', 10);

// Custom metrics. k6's built-in http_req_duration cannot express "tokens per second",
// which is the only unit in which serving engines are meaningfully comparable.
const completionTokens = new Counter('completion_tokens');
const tokensPerSecond = new Trend('tokens_per_second');
const promptTokens = new Counter('prompt_tokens');
const generationTime = new Trend('generation_time_ms');
const badResponses = new Rate('bad_responses');

/**
 * A prompt shaped like the real RAG workload: system instructions + two retrieved
 * passages + a question (~250 prompt tokens). Benchmarking with a 5-token prompt would
 * measure the HTTP stack, not the engine — prefill cost scales with prompt length, and
 * prefill is where batching pays off.
 */
const SYSTEM = 'You are a medical information assistant. Answer only from the CONTEXT, ' +
  'citing passage numbers in square brackets. Be concise.';
const CONTEXT =
  '[1] (Gale Encyclopedia of Medicine, p.78)\n' +
  'Abscess - A pus-filled area with definite borders. Bacterial infection of the CNS can ' +
  'result in abscesses and empyemas. Abscesses have fixed boundaries, but empyemas lack ' +
  'definable shape.\n\n' +
  '[2] (Gale Encyclopedia of Medicine, p.79)\n' +
  'A lumbar puncture and analysis of the cerebrospinal fluid can help diagnose an epidural ' +
  'abscess; however, the procedure can be dangerous in patients with raised intracranial ' +
  'pressure, and imaging is generally preferred as a first investigation.';

// Varying the question prevents any prefix/response cache from inflating results — a
// benchmark that measures the cache is not measuring the engine.
const QUESTIONS = [
  'What is an abscess and how does it differ from an empyema?',
  'How is an epidural abscess diagnosed?',
  'Why can a lumbar puncture be dangerous in some patients?',
  'What are the defining borders of an abscess?',
  'Which imaging is preferred as a first investigation?',
];

/**
 * PEAK_RATE must be tuned to the venue, because "what are we measuring?" differs:
 *
 *   self-hosted GPU -> find the SATURATION point. Ramp until latency degrades; that is
 *                      the engine's real capacity and the number that separates vLLM
 *                      from SGLang.
 *   hosted API      -> respect the CONTRACTED rate limit. Ramping past it measures the
 *                      provider's 429 handler, not its throughput. Measured in S14:
 *                      Groq's free tier failed 91% of requests at ~7 RPS — a quota wall,
 *                      not a performance wall (exactly the D4 procurement concern).
 */
const PEAK_RATE = parseInt(__ENV.PEAK_RATE || '20', 10);
const q = (n) => Math.max(1, Math.round(PEAK_RATE * n));

export const options = {
  scenarios: {
    // Ramping ARRIVAL RATE, not ramping VUs: an open model keeps sending requests even
    // when the engine slows down, which is how real traffic behaves. A closed model
    // (fixed VUs) would silently reduce load as latency rises and hide saturation
    // entirely — the classic load-testing mistake.
    ramp: {
      executor: 'ramping-arrival-rate',
      startRate: 1,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 100,
      stages: [
        { target: q(0.1), duration: '20s' },  // warm: CUDA graphs, first batches
        { target: q(0.25), duration: '30s' },
        { target: q(0.5), duration: '30s' },
        { target: q(1.0), duration: '30s' },  // peak
      ],
    },
  },
  thresholds: {
    // Encoding the Phase-1 NFRs as pass/fail, so the benchmark is a GATE rather than a
    // report nobody reads.
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<12000'],
    bad_responses: ['rate<0.01'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const question = QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)];
  const payload = JSON.stringify({
    model: MODEL,
    messages: [
      { role: 'system', content: SYSTEM },
      { role: 'user', content: `CONTEXT:\n${CONTEXT}\n\nQUESTION:\n${question}` },
    ],
    max_tokens: MAX_TOKENS,
    temperature: 0.2,
    stream: false,
  });

  const headers = {
    'Content-Type': 'application/json',
    // Providers behind Cloudflare (Groq among them) return 403 without a User-Agent —
    // measured in S3b.
    'User-Agent': 'medbot-k6/0.1',
  };
  if (API_KEY) headers.Authorization = `Bearer ${API_KEY}`;

  const started = Date.now();
  const res = http.post(`${BASE_URL}/chat/completions`, payload, {
    headers,
    timeout: '120s',
    tags: { venue: LABEL },
  });
  const elapsedMs = Date.now() - started;

  const ok = check(res, {
    'status 200': (r) => r.status === 200,
    'has content': (r) => {
      try {
        return (r.json('choices.0.message.content') || '').length > 0;
      } catch (e) {
        return false;
      }
    },
  });
  badResponses.add(!ok);
  if (!ok) return;

  try {
    const usage = res.json('usage') || {};
    const out = usage.completion_tokens || 0;
    const inn = usage.prompt_tokens || 0;
    completionTokens.add(out);
    promptTokens.add(inn);
    generationTime.add(elapsedMs);
    // Per-request throughput. Aggregated across concurrent VUs this is the number that
    // actually separates serving engines.
    if (elapsedMs > 0 && out > 0) tokensPerSecond.add((out / elapsedMs) * 1000);
  } catch (e) {
    badResponses.add(true);
  }
}

export function handleSummary(data) {
  const m = data.metrics;
  const get = (name, stat) => (m[name] && m[name].values ? m[name].values[stat] : null);
  const fmt = (v, d = 1) => (v === null || v === undefined ? 'n/a' : v.toFixed(d));

  const report = {
    label: LABEL,
    model: MODEL,
    base_url: BASE_URL,
    requests: get('http_reqs', 'count'),
    failed_rate: get('http_req_failed', 'rate'),
    latency_ms: {
      med: get('http_req_duration', 'med'),
      p95: get('http_req_duration', 'p(95)'),
      p99: get('http_req_duration', 'p(99)'),
    },
    tokens_per_second: {
      avg: get('tokens_per_second', 'avg'),
      med: get('tokens_per_second', 'med'),
      p95: get('tokens_per_second', 'p(95)'),
    },
    completion_tokens_total: get('completion_tokens', 'count'),
  };

  const text = [
    ``,
    `=== ENGINE BENCHMARK: ${LABEL} ===`,
    `model:    ${MODEL}`,
    `requests: ${fmt(report.requests, 0)}  failed: ${fmt((report.failed_rate || 0) * 100, 2)}%`,
    `latency:  med ${fmt(report.latency_ms.med, 0)}ms  p95 ${fmt(report.latency_ms.p95, 0)}ms  p99 ${fmt(report.latency_ms.p99, 0)}ms`,
    `tok/s:    avg ${fmt(report.tokens_per_second.avg)}  med ${fmt(report.tokens_per_second.med)}  p95 ${fmt(report.tokens_per_second.p95)}`,
    `tokens:   ${fmt(report.completion_tokens_total, 0)} generated`,
    ``,
  ].join('\n');

  return {
    stdout: text,
    [`eval-reports/bench-${LABEL}.json`]: JSON.stringify(report, null, 2),
  };
}
