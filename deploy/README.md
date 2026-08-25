# Popov Agent — Kubernetes Deployment Guide

This guide walks you through building the Docker image and deploying
**Popov - Incident Response Agent** to a Kubernetes cluster, step by step,
in the exact order required.

Follow the steps **top to bottom** — later steps depend on earlier ones.

---

## Architecture Overview

One container image (`popov-agent`) is used for everything: it contains the
FastAPI backend, the built React frontend (served as SPA by Uvicorn), and can
run either as the API server or the watchdog worker (via command override).

Two deployment options are provided:

| Option | File(s) | Pods | Use when |
|---|---|---|---|
| **A** (recommended) | `deployment.yaml` + `watchdog-deployment.yaml` | 2 | Default. API and watchdog restart/scale independently |
| **B** | `single-pod.yaml` | 1 | Resource-constrained clusters. Both processes share one pod |

> ⚠️ **Pick exactly ONE option.** Applying both will duplicate Telegram
> polling and watchdog alerts.

Singleton constraints (do NOT increase replicas):

- The API runs a Telegram `getUpdates` long-polling loop — only one instance
  may poll a bot at a time.
- The watchdog polls observability targets with fingerprint-based anti-spam —
  more than one instance means N× polling and duplicated alerts/tickets.
- That is why the watchdog deployment uses `strategy: Recreate`.

MongoDB is **not** included in this folder — you must provide a reachable
MongoDB instance (managed service or your own deployment) before starting.

---

## Step 0 — Prerequisites

- A running Kubernetes cluster + `kubectl` configured against it
- Docker installed locally
- A Docker Hub account (or any OCI registry)
- A MongoDB instance reachable from the cluster (e.g. `mongodb://mongodb-service:27017`)
- LLM provider API keys (OpenAI / OpenRouter / Google)

Check connectivity first:

```bash
kubectl cluster-info
docker --version
```

---

## Step 1 — Configure the ConfigMap (non-secret settings)

Open `deploy/configmap.yaml` and review:

- `MONGODB_DB` — database name (default `popovagent_db`)
- `LLM_PROVIDER` / `LLM_MODEL` — active LLM provider (`openai` | `openrouter` | `google`)
- `PROMETHEUS_URL` / `TEMPO_URL` / `ALERTMANAGER_URL` — observability endpoints
- `OBSERVABILITY_INTERVAL_MIN` — watchdog poll interval (minutes)
- `TICKET_ALERT_DEDUP_HOURS` — window for linking repeated alerts to an open ticket

No changes needed if the defaults match your environment.

---

## Step 2 — Configure the Secret (credentials)

Open `deploy/secret.yaml` and replace every `CHANGE_ME_*` value:

```yaml
OPENAI_API_KEY / OPENROUTER_API_KEY / GOOGLE_API_KEY   # provider you use
MONGODB_URI        # e.g. mongodb://mongodb-service:27017
MYSQL_PASSWORD     # optional — only for MySQL log DB integrations
JWT_SECRET         # generate: openssl rand -hex 32
DATA_ENCRYPTION_KEY  # encrypts stored BYOK credentials
```

> ⚠️ Telegram bot tokens are **not** set here — they are configured
> per workspace in the UI (*Workspace Settings → Notifications*) and are
> encrypted at rest.

Do **not** commit real values. If you prefer, create the Secret imperatively:

```bash
kubectl create secret generic popov-agent-secret \
  --from-literal=OPENAI_API_KEY=sk-... \
  --from-literal=MONGODB_URI=mongodb://mongodb-service:27017 \
  --from-literal=JWT_SECRET=$(openssl rand -hex 32) \
  --from-literal=DATA_ENCRYPTION_KEY=$(openssl rand -hex 16)
```

---

## Step 3 — Build & Push the Docker Image

Run from the **repository root** (the Dockerfile path is `deploy/Dockerfile`):

```bash
docker login

# Frontend API base URL — keep `/api/v1` when serving SPA + API from one domain
docker build \
  --build-arg VITE_API_BASE_URL=/api/v1 \
  -t <YOUR_DOCKERHUB_USERNAME>/popov-agent:0.2.0.24 \
  -t <YOUR_DOCKERHUB_USERNAME>/popov-agent:latest \
  -f deploy/Dockerfile .

docker push <YOUR_DOCKERHUB_USERNAME>/popov-agent:0.2.0.24
docker push <YOUR_DOCKERHUB_USERNAME>/popov-agent:latest
```

Tips:

- Replace `<YOUR_DOCKERHUB_USERNAME>` everywhere (manifests reference it).
- Prefer version tags over `latest` in production so rollbacks are exact.
- The frontend i18n locale files (`web/public/locales/`) are included in the
  build automatically — nothing extra to configure.

---

## Step 4 — Registry Pull Secret

Only needed for a **private** registry:

```bash
kubectl create secret docker-registry dockerhub-secret \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=<YOUR_DOCKERHUB_USERNAME> \
  --docker-password=<DOCKER_HUB_TOKEN> \
  --docker-email=<YOUR_EMAIL>
```

Skip this step if your image is public (and remove `imagePullSecrets` from
the manifests).

---

## Step 5 — Deploy (choose ONE option)

### Option A — Two pods (recommended)

API/web and watchdog run as independent deployments:

```bash
kubectl apply -f deploy/service.yaml
kubectl apply -f deploy/deployment.yaml
kubectl apply -f deploy/watchdog-deployment.yaml
```

Keep the Service selector as-is: `app: popov-agent`.

### Option B — Single pod (resource-constrained)

Both processes share one pod as two containers:

```bash
kubectl apply -f deploy/service.yaml
# ⚠️ First edit deploy/service.yaml: change selector to `app: popov-agent-single`
kubectl apply -f deploy/single-pod.yaml
```

> ⚠️ Never apply Option A's deployments together with `single-pod.yaml`.
> If you previously deployed Option A, remove it first:
>
> ```bash
> kubectl delete -f deploy/deployment.yaml -f deploy/watchdog-deployment.yaml
> ```

---

## Step 6 — Verify the Deployment

Run these in order and confirm each result:

```bash
# 1. Pods ready? (watchdog has no probe — check it stays Running)
kubectl get pods -l 'app in (popov-agent, popov-watchdog, popov-agent-single)'

# 2. Rollout finished?
kubectl rollout status deployment/popov-agent            # Option A
kubectl rollout status deployment/popov-watchdog         # Option A
kubectl rollout status deployment/popov-agent-single     # Option B

# 3. Health endpoint responds?
kubectl port-forward svc/popov-agent-service 8000:8000
curl http://localhost:8000/api/v1/health

# 4. Open the app
kubectl port-forward svc/popov-agent-service 8080:8000
# → http://localhost:8080  (first registered user becomes admin)
```

Watch both process logs — both must be alive:

```bash
kubectl logs deployment/popov-agent          # Option A api / single-pod api container
kubectl logs deployment/popov-watchdog       # Option A watchdog
kubectl logs deployment/popov-agent-single -c watchdog   # Option B watchdog container
```

---

## Step 7 — Upgrading

```bash
# Build & push the new tag (Step 3), then:
kubectl set image deployment/popov-agent \
  popov-agent=<YOUR_DOCKERHUB_USERNAME>/popov-agent:<NEW_VERSION>

kubectl rollout status deployment/popov-agent
# Rollback if needed:
kubectl rollout undo deployment/popov-agent
```

For the watchdog remember: it loads code at startup — after every backend
change, restart it too (`kubectl rollout restart deployment/popov-watchdog`,
or just re-apply the option manifests).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Pod `CrashLoopBackOff`, logs show Mongo timeout | MongoDB unreachable | Check `MONGODB_URI` in the Secret; verify NetworkPolicy/DNS |
| Duplicate alerts / tickets | Two watchdog instances running | `kubectl get pods -l component=watchdog-worker` — must be exactly 1; delete extras |
| Image pull errors on private registry | Missing/wrong `dockerhub-secret` | Re-run Step 4; confirm secret name matches manifests |
| UI loads but no data | API base URL mismatch | Rebuild image with `--build-arg VITE_API_BASE_URL=/api/v1` |
| Login fails with 401 right after install | `JWT_SECRET` changed or missing | Set a stable `JWT_SECRET` in the Secret, then restart pods |
| Watchdog silent (no alerts) | Observability URLs wrong | Test endpoints via *Workspace Settings → Stacks → Test* button |
