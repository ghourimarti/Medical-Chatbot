# Vendor selection and cost model

**Decision: DigitalOcean DOKS first, AWS EKS second.** Committed, with the exit criteria
that would reverse it stated below.

This is the decision the deploy workflows were waiting on. They are written but
deliberately unexercised, because their apply step would otherwise be a guess at
DOKS-vs-EKS auth, registry and secret handling — a guess Phase 7 would then rewrite.

> **On the prices.** Every figure is a **list price to verify at purchase time**, not a
> quote. Cloud pricing moves, and regional rates differ. What is robust to that drift is the
> *shape* of the difference — two EKS line items have no DOKS equivalent at all — so the
> conclusion survives even if every unit price below is stale.

---

## Sizing — from the chart's actual requests, not a guess

Taken from `infra/k8s/medbot/values.yaml`. Requests are what the scheduler reserves, so they
are what you actually buy.

| Component | Replicas | CPU request | Memory request | Storage |
|---|---:|---:|---:|---:|
| api | 2 | 500m | 1.0 Gi | — |
| ml-service | 1 | 1000m | 2.0 Gi | — |
| worker | 1 | 500m | 1.0 Gi | — |
| qdrant | 1 | 250m | 0.5 Gi | 10 Gi |
| postgres | 1 | 100m | 0.25 Gi | 5 Gi |
| redis | 1 | 100m | 0.125 Gi | — |
| **application total** | | **2.45 vCPU** | **4.9 Gi** | **15 Gi** |
| platform overhead | | ~0.5–1 vCPU | ~1–2 Gi | — |
| **at rest** | | **~3.5 vCPU** | **~7 Gi** | |
| **at HPA max** (api 10, ml 4) | | **~7.5 vCPU** | **~15 Gi** | |

Two replicas of `api` is not padding: a PodDisruptionBudget can never be satisfied with one.

**Node plan: 3 × 2 vCPU / 4 GB.** Three nodes rather than two so a drain has somewhere to
drain *to* — proven necessary in the kind drills, where a two-node cluster could not
reschedule a PDB-protected pod. Bursting to HPA max needs a fourth node or a larger class,
which is a Phase-7 measurement, not a guess to bake in now.

## Monthly cost

### DigitalOcean DOKS

| Line item | Spec | $/mo |
|---|---|---:|
| Control plane | — | **$0** |
| Worker nodes | 3 × (2 vCPU / 4 GB) | ~72 |
| Managed Postgres | smallest (1 vCPU / 1 GB) | ~15 |
| Managed Valkey/Redis | smallest | ~15 |
| Load balancer | 1 | ~12 |
| Container registry | Basic (images total 6.59 GB) | ~5 |
| Block storage | 15 Gi | ~2 |
| **Total** | | **≈ $121** |

### AWS EKS — same shape

| Line item | Spec | $/mo |
|---|---|---:|
| **Control plane** | $0.10/hr | **~73** |
| Worker nodes | 3 × t3.medium | ~90 |
| RDS PostgreSQL | db.t4g.micro | ~15 |
| ElastiCache | cache.t4g.micro | ~12 |
| Load balancer | 1 NLB | ~20 |
| **NAT gateway** | 1 AZ, before data charges | **~32** |
| ECR | 6.59 GB | ~1 |
| EBS gp3 | 15 Gi | ~2 |
| **Total** | | **≈ $245** |

### The structural difference

**~$105/mo of the ~$124 gap is two line items that simply do not exist on DOKS:**

1. **EKS control plane — ~$73/mo.** DOKS gives the control plane away.
2. **NAT gateway — ~$32/mo** *before* per-GB data processing. Private worker nodes need it
   to pull images and reach provider APIs. It is the single most commonly forgotten line in
   an EKS estimate, and it is charged hourly whether or not anything flows through it.

Both are fixed monthly costs, independent of load. At this scale AWS charges roughly **2×**
for the same workload, and most of the premium buys nothing this project needs. That is not
an argument that EKS is bad — it is an argument that EKS's value (IRSA, deep service
integration, org-scale IAM) is not what a single-service portfolio deployment is buying.

## Cost per 1,000 queries — and why the number is misleading

Measured throughput: **310 RPS** on the cache tier, **~2 RPS** through the full pipeline on
a cache miss (`docs/LOAD_TEST.md`).

| Scenario | Queries/month | Infra $/1k queries |
|---|---:|---:|
| Portfolio reality (~100/day) | 3,000 | **~$40** |
| Light real use (10/min, 12h/day) | 216,000 | **~$0.56** |
| Saturated at 2 RPS | 5,184,000 | **~$0.02** |

**At portfolio scale, cost per query is an idle-capacity number, not a throughput number.**
Three nodes cost the same whether they serve 100 queries or 100,000. Quoting "$0.02 per 1k
queries" for this deployment would be true only of a machine that is busy, and this one will
not be. The honest figure for a demo cluster is the top row.

Two consequences:

- **The $200 DigitalOcean credit (Track D.4) covers roughly 7–8 weeks** of the DOKS build at
  ~$121/mo. The same credit against an EKS-shaped bill would last ~3.5 weeks. Phase 7 should
  therefore be run against a **teardown runbook that works**, not left standing.
- **LLM inference cost is separate and dominates at real volume.** Infra is a floor you pay
  for existing; tokens are the marginal cost. The per-request budget accounting in
  `budget.py` covers the token side; this document covers only the floor.

## Why DOKS first — beyond price

| | |
|---|---|
| **Free control plane** | The whole EKS premium is fixed cost, paid before a single request |
| **Fewer moving parts** | No VPC/NAT/IRSA setup standing between "cluster" and "deployed" |
| **The portability claim gets tested properly** | Building on DOKS *first* and moving to EKS second is a real test. Building on AWS first and porting to DOKS would let AWS assumptions leak in unnoticed, then quietly get fixed |
| **Managed PG and Redis included** | Same data-tier shape as the AWS plan, so P8 compares like with like |

**EKS is not dropped — it is Phase 8, and it is the point.** Deploying the *same chart* to a
second vendor is what converts "vendor-portable" from a claim into a measurement. If the
diff is anything more than `values-aws.yaml` plus `infra/terraform/aws/`, the claim failed
and that failure is the finding worth writing up.

## What would reverse this decision

Stated in advance so it is a criterion rather than a rationalisation:

1. **The GPU venue needs to sit in-cluster.** DO's GPU droplets are limited; if self-hosted
   vLLM must run beside the app rather than as an external venue, AWS G-instances (or
   RunPod) win on availability. D4b's external-venue design is what keeps this from binding.
2. **IRSA-style workload identity becomes a requirement**, e.g. for an audit that demands
   per-pod cloud credentials rather than a mounted secret.
3. **An employer or client is an AWS shop.** Then EKS depth is the deliverable and the cost
   argument is irrelevant.
4. **Measured DOKS reliability disappoints** once it is running — a real finding beats a
   projected saving.

## Open before provisioning

- [ ] Track **D.4** — DigitalOcean account, apply the $200 credit
- [ ] `infra/terraform/do/` — currently only `infra/terraform/aws/` exists
- [ ] `values-do.yaml` — StorageClass name, LB annotations, registry URL
- [ ] Registry decision — DOCR vs GHCR (GHCR is vendor-neutral and would keep P8 honest)
- [ ] Fill the `TODO(P7)` markers in the deploy workflow, one per environment

Until D.4 lands, the correct status for every managed-cluster item is **blocked**, and the deploy workflows
stay written-but-unexercised rather than being marked done.
