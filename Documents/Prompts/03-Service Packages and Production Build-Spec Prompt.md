# Service Packages and Production Build-Spec Prompt

## Role
You are a principal AI engineer who has shipped enterprise-grade GenAI systems to millions of users in production. You know the difference between a portfolio project and a production system — and you can list, layer by layer, exactly what is required to turn the former into the latter. You are also commercially aware: you understand which packages of capability map to which client buying patterns on Upwork, Fiverr, and direct contracts.

Be concrete and opinionated. When there are trade-offs between tools, give a **default recommendation and one or two real alternatives** — not a long catalog. I am building a working spec, not a survey.

## Context From Prior Conversation

In the prior turns of this conversation, we established:
- My current skill level (based on the attached document of completed courses)
- The gap between where I am and the ability to ship enterprise-grade GenAI applications for millions of users
- A plan to close the gap by transforming 10–15 simple portfolio projects into production-grade applications using Claude Code as a coding assistant

This prompt builds on that. **Use the gap analysis and tech list from the prior turns as the input** — I'm now asking you to package that knowledge into client-facing service offerings *and* into actionable build-specs I can execute with Claude Code.

## What I Need From You

This task has **two parts**. Do both.

### Part A — Service Package Catalogue

List every distinct service package I will be able to credibly offer **after filling the gap**, given my capabilities. Start with the three I already have in mind, then add any additional ones you believe fall within my realistic capability envelope (do not pad the list — only include packages I could actually deliver well).

The three I already have:
1. **Production-grade RAG application** — frontend + backend + dev + deployment + Docker + Kubernetes + Terraform + CI/CD + version control; fully robust, scalable, complete architecture, capable of serving millions of users
2. **Production-grade Agentic AI application** — same scope as above
3. **Production-grade fine-tuned LLM application** — same scope as above

Suggest additional packages I am missing. Candidates worth considering: multi-modal applications (vision/voice/text), document intelligence pipelines, AI microservices added to existing client systems, voice/conversational AI, LLM evaluation and observability platforms, AI-powered analytics tools, vertical-specific GenAI products (legal/medical/financial — only if the technical work, not the domain expertise, is the bottleneck). Add only the ones that genuinely fit my profile.

For each package, give a **one-line definition** and **2–3 concrete client use cases** (not abstract — actual scenarios, e.g., "internal knowledge assistant for a 5,000-employee company over their Confluence + Google Drive + Slack history").

### Part B — Full Build-Spec Per Package

For **every** package listed in Part A, provide the complete build-spec using the structure below. Each package gets its own section. Do not skip any subsection. Do not collapse multiple packages into one shared spec — different packages have different bottlenecks.

For each tool/technology recommendation, give the **default choice + one or two alternatives** with a one-line note on when to swap.

#### Spec Structure (apply per package)

**1. Definition and target use cases**
Repeat the one-liner and use cases from Part A for context.

**2. Frontend layer**
- Framework, UI library / design system, state management, auth UI, streaming UX patterns specific to LLM responses (token streaming, cancellation, retry)

**3. Backend layer**
- Language and framework, async patterns, API style (REST/GraphQL/gRPC), background jobs and queueing, request/response schemas, rate limiting

**4. AI/ML core**
- LLM providers and model selection strategy (proprietary vs open-weight, hosted vs self-hosted)
- Orchestration framework (LangChain, LlamaIndex, LangGraph, custom — recommend with reasoning)
- Prompt management and versioning
- For RAG: chunking strategy, embedding model, retrieval pattern (dense / sparse / hybrid / reranking), context construction
- For Agentic: agent framework, tool/function calling, planning and memory, multi-agent patterns where relevant
- For Fine-tuning: data prep pipeline, fine-tuning method (LoRA / QLoRA / full fine-tune / instruction tuning / RLHF / DPO), training infrastructure, model serving

**5. Data layer**
- Vector database, primary database, cache, message queue, blob/object storage, search index if relevant

**6. Infrastructure and deployment**
- Containerization (Docker patterns specific to AI workloads — model weights, GPU images, layer caching)
- Orchestration (Kubernetes manifests/Helm, GPU node pools, autoscaling for inference)
- Infrastructure as code (Terraform module structure)
- Cloud provider services (AWS-first, given my background — but flag where Azure or GCP is genuinely better for a given package)
- Inference serving (vLLM, TGI, Triton, SageMaker, Bedrock, etc.) and when to pick each

**7. CI/CD and version control**
- Git workflow, repo structure (monorepo vs polyrepo), pipeline tool (GitHub Actions / GitLab CI / etc.), test stages, model and prompt versioning, deployment promotion strategy, rollback

**8. Observability**
- App-level (logs, metrics, traces — OpenTelemetry stack)
- LLM-specific (Langfuse / Arize / Helicone / LangSmith / etc. — recommend with reasoning), token usage tracking, latency breakdown, hallucination detection, eval-in-production

**9. Security and compliance**
- Auth (user and service), authz, secrets management, PII handling, prompt injection defenses, output filtering, data residency, audit logging, rate limiting and abuse prevention

**10. Scaling for millions of users**
- Specific patterns: caching layers (semantic cache, prompt cache, response cache), model routing and tiering (cheap-first, escalate on confidence), batch vs streaming inference, queue depth management, regional deployment, CDN strategy for static + cacheable AI responses
- Concrete bottleneck checklist: where this package will break first under load, and what the fix is

**11. Cost controls**
- Token-budget enforcement, model routing for cost, caching strategies, batching, monitoring + alerting on spend, kill switches

**12. Testing and evaluation strategy**
- Unit / integration / e2e tests at the code level
- LLM evaluation (offline eval set, online eval, A/B testing of prompts and models, regression detection)
- Load testing approach

**13. Reference project structure**
- A folder/file tree showing the recommended repo layout for this package, with a one-line note on each top-level folder

**14. Production hardening checklist**
- Concrete list of items that distinguish "demo on my machine" from "running in prod for paying customers" — items I should be able to tick off before claiming this package is delivery-ready

**15. Transformation roadmap — simple portfolio → production-grade**
This is the most important section. Give an **ordered, numbered list of steps** to take a basic working portfolio version of this package and transform it into the production-grade version specified above. Each step should be small enough to be a single Claude Code session (roughly half a day to a day of focused work). Order matters: dependencies first.

The roadmap is what I will actually execute step-by-step with Claude Code. Optimize for *executability*, not for explanation.

## Output Format

- Part A as a numbered list with use cases under each item
- Part B with one major section per package, using the 15-subsection structure above for each
- No filler, no recap, no closing pep talk
- Tables only where they genuinely help (e.g., comparing model serving options inside a package)
- Be opinionated. "It depends" is acceptable only when followed immediately by a default + the trigger that flips the recommendation

## Note on Length
This response will be long. That is fine and expected. Prioritize completeness over brevity — I am using this as a reference document, not reading it linearly. If you must compress, compress the prose around the recommendations, never the recommendations themselves.

## Attached Document
The course inventory is attached for reference, in case you need to recheck what I have already studied vs what is genuinely new ground.