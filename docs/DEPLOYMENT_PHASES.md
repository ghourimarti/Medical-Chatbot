# Deployment phases 6–9 — from laptop to real Kubernetes

> Extension to [TRANSFORMATION_PLAN.md](TRANSFORMATION_PLAN.md), agreed 2026-08.
> Supersedes the original single "PHASE 6 — Deployment" (P6.1–P6.6), which conflated a
> **$0 validation environment** with a **metered production one**. They answer different
> questions and therefore deserve separate phases with separate gates.

## The governing principle: vendor-portable core, thin vendor adapter

The same pattern already used for LLM serving (D12 `ModelPort`, D4b multi-venue) applies to
infrastructure: **isolate what varies, keep the rest identical everywhere.**

| Layer | Portable across every vendor? | Where vendor differences live |
|---|---|---|
| Application code (`apps/`, `packages/`) | ✅ 100% — zero changes | — |
| Helm charts: Deployment, Service, HPA, PDB, NetworkPolicy, ConfigMap, Secret | ✅ 100% | — |
| Ingress (ingress-nginx) + TLS (cert-manager) | ✅ 100% | — |
| Observability (Prometheus, Grafana, Loki) | ✅ 100% | — |
| **StorageClass name** | ❌ | `values-<vendor>.yaml` |
| **LoadBalancer annotations** | ❌ | `values-<vendor>.yaml` |
| **Container registry URL** | ❌ | `values-<vendor>.yaml` |
| **Cluster provisioning** | ❌ | `infra/terraform/<vendor>/` |
| **Managed data services** (or self-hosted in-cluster) | ❌ | `values-<vendor>.yaml` |

**Every managed Kubernetes below is CNCF-conformant**, which is precisely what makes this
work: `kubectl`, Helm, and the manifests behave identically. Switching vendors should be a
new `values-*.yaml` plus a new Terraform module — never an application change. **Phase 8
(AWS EKS) exists partly to prove that claim** by deploying the identical charts elsewhere.

## Vendor options — all production-grade

**Tier 1 — free control plane, developer-friendly, production-capable.** Best value; where
most startups and many scaleups run.

| Vendor | Control plane | ~Node cost/mo | Notes |
|---|---|---:|---|
| **DigitalOcean DOKS** | FREE | ~$24 (2vCPU/4GB) | Simplest real k8s, excellent docs, managed PG/Redis, registry |
| **Linode / Akamai LKE** | FREE | ~$24 | Cheap, stable, good global regions |
| **Vultr VKE** | FREE | ~$20 | Cheapest of this tier, many regions |
| **Civo** | FREE | ~$20 | k3s-based, ~90-second cluster creation |
| **Scaleway Kapsule** | FREE | ~€20 | EU/GDPR-friendly |
| **OVHcloud Managed K8s** | FREE | ~€15 | EU, very cheap |
| **Exoscale SKS** | FREE | ~€20 | EU, compliance-oriented |

**Tier 2 — hyperscalers.** Paid control plane; what enterprise job postings ask for.

| Vendor | Control plane | Notes |
|---|---|---|
| **AWS EKS** | ~$73/mo | Largest market share; **Phase 8 target** |
| **Google GKE** | ~$73/mo (Autopilot bills per-pod) | Best-regarded k8s UX; Google originated k8s |
| **Azure AKS** | FREE (standard tier) | Strong in Microsoft-shop enterprises |

**Tier 3 — self-managed on cheap VMs.** Maximum control and lowest cost; you own upgrades,
etcd backups, and HA. Genuinely production-grade when operated well.

| Vendor | Approach | ~Cost/mo |
|---|---|---:|
| **Hetzner + k3s** | 3 × CPX21 VMs | ~€15 total — the EU cost king |
| Any VPS + k3s/kubeadm | Same pattern | varies |

**Tier 4 — GPU-specialized** (for the vLLM venue, per D4b).

| Vendor | Notes |
|---|---|
| **CoreWeave** | Kubernetes-native GPU cloud; the enterprise GPU play |
| **RunPod / Lambda Labs / Vast.ai** | Per-hour GPU; D4b `runpod` venue |
| **Modal / Baseten** | Serverless GPU inference |

**Recommended first target: DigitalOcean DOKS** — free control plane (vs EKS's $73/mo before
a single pod runs) and an existing $200 credit. Realistic cluster: 3 × 2vCPU/4GB (~$72) +
LB (~$12) + managed Postgres (~$15) + registry (~$5) ≈ **$104/mo → ~2 months of runway**.
*(Verify current prices; they change.)*

**GPU note:** DO GPU droplets are expensive, but D4b already solves this — run the **app tier
on DOKS**, the **GPU venue on RunPod or the local RTX 3060**, with **Groq as the hosted
floor**. That is three genuinely independent failure domains, which is a *stronger*
architecture demonstration than putting everything in one cloud.

---

## Scale guidance — what infrastructure is actually correct

Derived from our own NFR arithmetic (10M MAU → 1.5M DAU → 4.5M queries/day → 52 RPS avg /
350 RPS peak) and cross-referenced with our **measured** P5.2 load test: the full pipeline
sustains **~2 RPS per instance**, with reranking consuming 54% of request time.

| Users (MAU) | Peak RPS | Instances @2 RPS | Correct infrastructure | ~Cost/mo |
|---|---:|---:|---|---:|
| 10k | ~0.35 | 1 | **No Kubernetes.** One VM + compose, or Cloud Run / App Runner / App Platform | $30–150 |
| 100k | ~3.5 | 2–3 | Managed containers, or a 3-node managed k8s for the primitives | $150–500 |
| 1M | ~35 | ~18 ⚠️ | **Managed Kubernetes justified** — HPA, node pools, multi-service | $1–3k |
| 10M+ | ~350 | ~175 🚨 | Managed k8s multi-AZ, CPU + GPU node pools, autoscaler, KEDA | $10–25k |

**The instance column is the finding.** 175 pods is economically absurd — which is exactly
why the S5.9 measurement matters: swapping to a 33M-param reranker was measured **8× faster**,
moving the pipeline toward ~10–15 RPS/instance and cutting the fleet by an order of magnitude.
**Fixing the bottleneck is worth more than scaling the fleet**, and we have the numbers to
prove it.

---

## PHASE 6 — Local & kind validation *(cost: $0)*

**Question answered: "are my manifests correct?"** kind runs the genuine Kubernetes control
plane in Docker — ~95% API fidelity, 0% capacity fidelity. It catches probe paths, image
refs, missing ConfigMap keys, RBAC denials, PVC binding, crash loops, and Helm template
errors — for free, before any metered cluster exists.

It will **not** catch: `type: LoadBalancer`, real StorageClasses, cloud IAM, ingress + TLS +
DNS, private registry pulls, node failure, or anything about capacity. Those are Phase 7.

| Step | Deliverable |
|---|---|
| P6.1 | Docker images for api / ml-service / worker — multi-stage, non-root, Trivy-clean |
| P6.1a | **Strip CUDA from CPU-only images — MEASURED, see below** |
| P6.2 | `docker compose` full-stack end-to-end smoke |
| P6.3 | kind cluster created; Helm chart installs green |
| P6.4 | Probes, HPA, ConfigMap/Secret wiring verified in-cluster |
| P6.5 | In-cluster failure drills: pod kill, rollout restart, node drain |
| P6.6 | `terraform plan` reviewed (no apply) |

**Gate to Phase 7:** full query path works in kind; `helm upgrade` is idempotent; no manifest
depends on anything kind cannot provide.

## PHASE 7 — Real managed Kubernetes *(metered; DOKS first)*

**Question answered: "does it actually run on real infrastructure, and what does it cost?"**

| Step | Deliverable |
|---|---|
| P7.1 | Vendor selection + cost model committed to the repo |
| P7.2 | Cluster provisioned **via Terraform** (never click-ops) |
| P7.3 | Container registry + image push pipeline |
| P7.4 | Data tier: managed Postgres + Redis (or in-cluster for portability) |
| P7.5 | Ingress-nginx + cert-manager + TLS + DNS |
| P7.6 | Secrets management (External Secrets or vendor secret store) |
| P7.7 | App tier deployed; GPU venue connected per D4b |
| P7.8 | Observability live: Prometheus, Grafana, alerts firing |
| P7.9 | **Load test against the real cluster** — HPA actually scaling |
| P7.10 | **Chaos drills against the real cluster** — node/pod failure |
| P7.11 | **Real cost measurement: $ per 1k queries** |
| P7.12 | Teardown runbook + `terraform destroy` verified |

**Gate to Phase 8:** real traffic served over TLS on a public domain, with measured cost and
a proven teardown.

## PHASE 8 — AWS EKS *(portability proof + AWS-depth gap)*

**Question answered: "is the architecture genuinely vendor-independent, and can I operate the
platform enterprises actually use?"**

The test of Phase 8 is blunt: **the Helm charts must deploy unchanged.** Only
`values-aws.yaml` and `infra/terraform/aws/` differ. If anything else needs editing, Phase 7
leaked vendor specifics and that is a finding worth writing up.

| Step | Deliverable |
|---|---|
| P8.1 | G-instance/EKS quota approved (Track D) |
| P8.2 | Terraform: VPC + EKS + managed node groups |
| P8.3 | IRSA (IAM Roles for Service Accounts) — least privilege |
| P8.4 | RDS with **PITR** (a P5.4 requirement) + ElastiCache + SQS |
| P8.5 | Same charts deployed via `values-aws.yaml` — **diff must be config-only** |
| P8.6 | GPU node group for the self-hosted vLLM venue |
| P8.7 | Cost comparison: DOKS vs EKS, measured |
| P8.8 | Portability findings written up |

## PHASE 9 — Portfolio

| Step | Deliverable |
|---|---|
| P9.1 | Architecture diagram |
| P9.2 | README rewrite |
| P9.3 | Before/after metrics story (the money chart) |
| P9.4 | Findings writeup (every measurement that refuted an assumption) |
| P9.5 | Demo video / screenshots |
| P9.6 | Interview talking points + consolidated senior-vs-junior table |


---

## Finding (S15.5): CPU-only images ship 3.4 GB of unusable CUDA runtime

Measured inside `medbot-ml:0.1.0` (total image **8.5 GB**):

| Package | Size | Reachable? |
|---|---:|---|
| `nvidia/*` (CUDA libs) | 2724 MB | ❌ never executed |
| `triton` (GPU kernel compiler) | 691 MB | ❌ never executed |
| `cuda` | 25 MB | ❌ never executed |
| `torch` (CUDA build) | 1127 MB | partially — CPU ops only |

**Cause.** `torch` is a transitive dependency of `sentence-transformers` and PyPI's default
wheel is the CUDA build. But every model in this repo is instantiated CPU-only:

```
apps/api/src/medapi/adapters/embedder.py:30   SentenceTransformer(..., device="cpu")
apps/api/src/medapi/adapters/reranker.py:41   CrossEncoder(..., device="cpu")
apps/ml-service/src/medml/backends.py:51      SentenceTransformer(..., device="cpu")
apps/ml-service/src/medml/backends.py:93      CrossEncoder(..., device="cpu")
```

GPU inference lives in the **separate vLLM venue** (D4b), never in these containers.

**Why it matters beyond disk.** Image size is paid on every pull:
* `kind load` of three images took long enough to background — the immediate symptom;
* registry storage and egress on DOKS/EKS;
* **pod cold-start on every HPA scale-up** — which directly undermines the autoscaling
  behaviour Phase 7 exists to demonstrate. An 8.8 GB image makes "scale up fast" a fiction.

**Fix** (repo root `pyproject.toml`), expected to cut each image roughly in half:

```toml
[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cpu" }
```

Deferred to **P6.1a** rather than applied mid-deployment: it changes `uv.lock` and requires
a full rebuild + re-load of all three images. Sequencing an optimization ahead of the
correctness proof it would invalidate is how you end up debugging two things at once.
