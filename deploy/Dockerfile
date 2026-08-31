# ── Stage 1: Build frontend (Vite → web/dist) ────────────────────────────────
FROM node:20-slim AS webbuilder
WORKDIR /web

# Cache dependencies
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Build (VITE_* di-build-time — override via --build-arg bila perlu)
COPY web/ ./
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_WS_BASE_URL=
ARG VITE_TRACE_ID_BASE_URL=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_WS_BASE_URL=$VITE_WS_BASE_URL \
    VITE_TRACE_ID_BASE_URL=$VITE_TRACE_ID_BASE_URL
RUN npm run build

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install curl for container health check & runtime utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml, README.md, and package directories for editable install
COPY pyproject.toml README.md ./
COPY api/ api/
COPY graph/ graph/
COPY state/ state/
COPY agents/ agents/
COPY config/ config/
COPY services/ services/
COPY main.py watchdog_worker.py ./
COPY prompts/ prompts/

# Install python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy remaining application source code
COPY . .

# Copy hasil build frontend dari stage 1 (FE-6: satu container, satu domain)
COPY --from=webbuilder /web/dist ./web/dist

# Create logs directory and assign permissions to a non-root user
RUN mkdir -p logs && \
    useradd -u 1000 -m appuser && \
    chown -R appuser:appuser /app

USER appuser

# Expose FastAPI server port
EXPOSE 8000

# Container healthcheck (API + SPA)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Start Uvicorn server — API + WebSocket + SSE + SPA
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
