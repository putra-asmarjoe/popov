# Panduan Deployment Kubernetes — Popov Agent

Dokumen ini berisi petunjuk langkah demi langkah untuk melakukan build Docker image `popov-agent`, mengunggah (push) ke **Private Docker Hub**, serta mendeploy aplikasi ke cluster **Kubernetes (K8s)**.

---

## 📂 Struktur File Deployment

Seluruh manifest dan konfigurasi deployment berada di folder `deploy/`:

- `deploy/Dockerfile` — Instruksi build container image berbasis `python:3.11-slim` (non-root user).
- `deploy/secret.yaml` — Tempat menyimpan data rahasia (API Keys LLM, Telegram Token, Kredensial DB).
- `deploy/configmap.yaml` — Tempat menyimpan konfigurasi non-sensitif (Model LLM, Provider, URL Observability).
- `deploy/deployment.yaml` — Kubernetes Deployment manifest (`replicas: 1`, Resource Limits: `100m`-`500m` CPU, `256Mi`-`512Mi` RAM).
- `deploy/service.yaml` — Kubernetes Service (`ClusterIP` port `8000`).

---

## 🛠️ Langkah 1: Build & Push Docker Image ke Private Docker Hub

Ganti `<USERNAME>` dengan username Docker Hub Anda.

### 1.1 Login ke Docker Hub
```bash
docker login
```
*Masukkan Username dan Password / Personal Access Token Docker Hub Anda.*

### 1.2 Build Image
Jalankan perintah build dari **root direktori project**:
```bash
docker build -t <USERNAME>/popov-agent:v1.0.0 -t <USERNAME>/popov-agent:latest -f deploy/Dockerfile .
```

### 1.3 Push Image ke Private Docker Hub
```bash
docker push <USERNAME>/popov-agent:v1.0.0
docker push <USERNAME>/popov-agent:latest
```

---

## 🔑 Langkah 2: Buat K8s ImagePullSecret untuk Private Docker Hub

Karena repository Docker Hub Anda bersifat **Private**, Kubernetes memerlukan kredensial untuk dapat melakukan pull image dari Docker Hub.

Jalankan perintah berikut pada terminal Anda yang terhubung ke cluster Kubernetes (`kubectl`):

```bash
kubectl create secret docker-registry dockerhub-secret \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=<USERNAME> \
  --docker-password=<DOCKER_HUB_TOKEN_OR_PASSWORD> \
  --docker-email=<YOUR_EMAIL> \
  --namespace=default
```

---

## ⚙️ Langkah 3: Konfigurasi Manifest Kubernetes

Sebelum mengaplikasikan manifest ke Kubernetes, sesuaikan nilai berikut:

### 3.1 Edit `deploy/secret.yaml`
Isi kredensial riil Anda pada field `stringData`:
- Telegram (Fix #39): TIDAK lagi lewat env/Secret — kelola bot per-workspace di
  Workspace Settings → tab "Notifications". Untuk bot lama, jalankan sekali:
  `python scripts/import_env_telegram.py --workspace-id <ObjectId>`
- `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `OPENROUTER_API_KEY`: Key LLM aktif Anda
- `MONGODB_URI`: URI koneksi MongoDB (contoh: `mongodb://mongodb-service:27017`)
- `MYSQL_PASSWORD`: Password database MySQL

### 3.2 Edit `deploy/deployment.yaml`
Ubah baris `image:` pada container spec agar sesuai dengan username Docker Hub Anda:
```yaml
spec:
  containers:
    - name: popov-agent
      image: <USERNAME>/popov-agent:latest
```

---

## 🚀 Langkah 4: Apply Manifest ke Kubernetes Cluster

Jalankan perintah berikut untuk mengaplikasikan seluruh manifest di direktori `deploy/`:

```bash
kubectl apply -f deploy/secret.yaml
kubectl apply -f deploy/configmap.yaml
kubectl apply -f deploy/deployment.yaml
kubectl apply -f deploy/service.yaml
```

Atau sekaligus:
```bash
kubectl apply -f deploy/
```

---

## 🔍 Langkah 5: Verifikasi Deployment & Monitoring

### 5.1 Cek Status Pod
```bash
kubectl get pods -l app=popov-agent
```
*Pastikan status pod menjadi `Running` dan `READY 1/1`.*

### 5.2 Cek Stream Log Application
```bash
kubectl logs -f -l app=popov-agent
```

### 5.3 Cek Health Check Endpoint via Port Forwarding
```bash
kubectl port-forward svc/popov-agent-service 8000:8000
```
Buka browser atau jalankan di terminal lain:
```bash
curl http://localhost:8000/api/v1/health
```
Output yang diharapkan: `{"status":"ok"}`

---

## 📊 Kebutuhan Resource (CPU & RAM Summary)

| Parameter | Request | Limit | Rationale |
|---|---|---|---|
| **CPU** | `100m` (0.1 Core) | `500m` (0.5 Core) | Idle polling ~20m-50m; Peak multi-agent LLM analysis ~100m-300m. |
| **Memory** | `256Mi` | `512Mi` | Baseline RAM Python FastAPI+LangGraph ~150MB; Peak fan-out & log batch ~300MB. |
| **Replicas** | `1` | `1` | Ditetapkan ke `1` karena **Telegram Bot Long-Polling** (`getUpdates`) mensyaratkan instance tunggal. |
