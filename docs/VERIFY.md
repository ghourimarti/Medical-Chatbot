# Verification commands — run these yourself

> Every command here is copy-pasteable and states what "working" looks like. Nothing in
> this project should be taken on trust: if a claim is made, there is a command below that
> checks it independently.
>
> Shell: PowerShell or Git Bash from the repo root, unless noted.

---

## PHASE 4 — Execution

### Eval harness, contracts, CI

```bash
make check                       # ruff + mypy + full unit suite
make validate                    # golden set schema      -> OK: 90 cases {'qa':60,'safety':20,'ooc':10}
make eval-mock                   # keyless eval smoke     -> prints scores, no API key needed
```

### Query path and streaming

```bash
make up                          # start Qdrant/Postgres/Redis
make api                         # in one shell
make smoke                       # in another: in-corpus -> kind=grounded; CRISPR -> kind=no_answer

# streaming: tokens must arrive incrementally, not in one blob
curl -N -X POST localhost:1107/api/v1/query/stream \
  -H 'content-type: application/json' \
  --data-binary '{"question":"What is an abscess?"}'
```

### ml-service

```bash
uv run uvicorn medml.main:app --port 1108        # one shell
curl -s localhost:1108/readyz                    # -> {"status":"ready"}  (503 until models warm)
curl -s -X POST localhost:1108/embed -H 'content-type: application/json' \
  --data-binary '{"texts":["What is cirrhosis?"],"is_query":true}' | head -c 200
```

### Retrieval quality and the eval gate

```bash
make eval-delta                  # before/after table, no gating
make eval-gate                   # BLOCKING: exits 1 if any D19 threshold is unmet
uv run medeval compare --before demo --after pipeline
```

### Serving venues and the engine benchmark

```bash
uv run python scripts/bench_venue.py --base-url http://localhost:1110/v1 \
  --model Qwen/Qwen2.5-7B-Instruct-AWQ --runs 5
```

---

## PHASE 5 — Hardening

```bash
make audit                       # secrets + dependency + license audit
make chaos                       # kill provider / Redis / Qdrant, assert graceful degradation
make backup-drill                # dump + restore, prints measured RTO
make load-cache                  # k6 tier A  -> ~310 RPS, p99 ~6 ms
make load-pipeline               # k6 tier B  -> ~2 RPS   (rerank ~54% of request time)
make load-guardrails             # k6 tier C  -> ~6 ms per refusal
```

---

## Helm and kind

### Chart correctness (no cluster needed)

```bash
helm lint infra/k8s/medbot -f infra/k8s/medbot/values-kind.yaml
# -> "1 chart(s) linted, 0 chart(s) failed"

helm template medbot infra/k8s/medbot -f infra/k8s/medbot/values-kind.yaml \
  --set secrets.groqApiKey=test --set secrets.sessionSecret=test-secret | grep '^kind:' | sort | uniq -c
# -> 4 Deployment, 2 StatefulSet, 5 Service, 6 NetworkPolicy, 1 each HPA/PDB/PVC/ConfigMap/Secret/ServiceAccount
```

### Build images ← YOU RUN THESE

Heavy (torch + transformers). First build ~10-25 min; rebuilds are cached.
Run from the repo ROOT — the build context is `.`, not the app folder.

```bash
docker build -f apps/api/Dockerfile        -t medbot-api:0.1.0    .
docker build -f apps/ml-service/Dockerfile -t medbot-ml:0.1.0     .
docker build -f apps/worker/Dockerfile     -t medbot-worker:0.1.0 .

# verify all three exist
docker images --filter=reference='medbot-*'
```

### Cluster

```bash
kind get clusters                              # -> medbot
kubectl config use-context kind-medbot
kubectl get nodes                              # -> 3 nodes, all Ready, v1.31.6
kubectl get deploy -n kube-system metrics-server
```

### Load images into kind and install

kind nodes cannot see the host's Docker images; they must be side-loaded.

```bash
kind load docker-image medbot-api:0.1.0    --name medbot
kind load docker-image medbot-ml:0.1.0     --name medbot
kind load docker-image medbot-worker:0.1.0 --name medbot

# confirm the image is actually on a node
docker exec medbot-worker crictl images | grep medbot

helm install medbot infra/k8s/medbot \
  -f infra/k8s/medbot/values-kind.yaml \
  --set secrets.groqApiKey="$GROQ_API_KEY" \
  --set secrets.sessionSecret="kind-dev-session-secret-not-for-prod"

kubectl get pods -w                            # watch until all Running/Ready
```

### Smoke test in-cluster

```bash
kubectl port-forward svc/medbot-api 8000:80    # one shell
curl -s localhost:8000/healthz                 # -> {"status":"ok"}
curl -s localhost:8000/readyz                  # -> ready once Qdrant is up
```

### Useful when a pod misbehaves

```bash
kubectl get pods -o wide
kubectl describe pod <name>                    # Events section explains scheduling/probe failures
kubectl logs <name> --tail=50
kubectl logs <name> --previous                 # logs from the crashed instance
kubectl get events --sort-by=.lastTimestamp | tail -20
```

### Teardown

```bash
helm uninstall medbot
kind delete cluster --name medbot
```

---

## Environment notes

**cgroup v1 constraint.** Docker Desktop runs cgroup v1; Kubernetes >= 1.32
refuses to start on it, so `kind-cluster.yaml` pins `kindest/node:v1.31.6`. Check yours:

```bash
docker info | grep -i "cgroup version"         # 1 = pinned version required; 2 = pins can be dropped
```

To move to cgroup v2 (matches DOKS/EKS/GKE) — restarts Docker, kills running containers:

```powershell
# %USERPROFILE%\.wslconfig
[wsl2]
kernelCommandLine = systemd.unified_cgroup_hierarchy=1 cgroup_no_v1=all
```
Then `wsl --shutdown`, restart Docker Desktop, and remove the `image:` lines from
`infra/k8s/kind-cluster.yaml`.
