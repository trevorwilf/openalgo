# ------------------------------ Python Builder Stage ----------------------- #
FROM python:3.12-bullseye AS python-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml .
# create isolated virtual-env with uv, then add gunicorn and eventlet with compatible versions
RUN pip install --no-cache-dir uv && \
    uv venv .venv && \
    uv pip install --upgrade pip && \
    uv sync && \
    uv pip install "gunicorn>=25.0,<26" eventlet && \
    rm -rf /root/.cache

# ------------------------------ Frontend Builder Stage --------------------- #
FROM node:20-bullseye-slim AS frontend-builder
WORKDIR /app
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# --------------------------------------------------------------------------- #
# ------------------------------ Production Stage --------------------------- #
FROM python:3.12-slim-bullseye AS production
# 0 – install runtime dependencies. The container TZ is deliberately
#     UTC. Per-venue and per-region local times come from
#     market_regions/<region>/plugin.json venues and from
#     database/venue_schedule_repo.py. Operators who want a different
#     container TZ should set the TZ env var below explicitly (e.g.
#     -e TZ=Asia/Kolkata for legacy Indian deployments). chromium +
#     fonts-liberation are required by Kaleido 1.x (plotly static image
#     export) which drives a real headless Chromium via choreographer.
#     Without these, /chart in the Telegram bot silently fails inside
#     Docker.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    libopenblas0 \
    libgomp1 \
    libgfortran5 \
    chromium \
    fonts-liberation && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 0a – supercronic. Cron daemon designed for containers (single Go
#      binary, logs to stdout, handles SIGTERM cleanly). Used by the
#      bowaka-prefilter service in docker-compose.bowaka.yml to fire
#      run_bowaka_prefilter.sh at the scheduled times. Harmless for
#      the openalgo / bowaka-strategy services that don't invoke it.
#      Pinned to v0.2.29 (April 2024). Multi-arch via TARGETARCH so
#      this image still builds on arm64 hosts (e.g., Graviton, Apple
#      Silicon); falls back to amd64 if TARGETARCH isn't set.
ARG TARGETARCH
RUN set -eux; \
    arch="${TARGETARCH:-amd64}"; \
    case "$arch" in \
        amd64) supercronic_arch=amd64 ;; \
        arm64) supercronic_arch=arm64 ;; \
        *) echo "supercronic install: unsupported arch '$arch'" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/supercronic \
        "https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-${supercronic_arch}"; \
    chmod +x /usr/local/bin/supercronic

# 1 – user & workdir
RUN useradd --create-home appuser
WORKDIR /app
# 2 – copy the ready-made venv and source with correct ownership
COPY --from=python-builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser . .
# 3 - copy built frontend from frontend-builder
COPY --from=frontend-builder --chown=appuser:appuser /app/frontend/dist /app/frontend/dist
# 4 – create required directories with proper ownership and permissions
#     Also create empty .env file with write permissions for Railway deployment
RUN mkdir -p /app/log /app/log/strategies /app/db /app/tmp /app/tmp/numba_cache /app/tmp/matplotlib /app/strategies /app/strategies/scripts /app/strategies/examples /app/keys && \
    chown -R appuser:appuser /app/log /app/db /app/tmp /app/strategies /app/keys && \
    chmod -R 755 /app/strategies /app/log /app/tmp && \
    chmod 700 /app/keys && \
    touch /app/.env && chown appuser:appuser /app/.env && chmod 666 /app/.env
# 5 – entrypoint script and fix line endings
COPY --chown=appuser:appuser start.sh /app/start.sh
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh
# ---- RUNTIME ENVS --------------------------------------------------------- #
# Limit OpenBLAS/NumPy threads to prevent RLIMIT_NPROC exhaustion in Docker
# See: https://github.com/marketcalls/openalgo/issues/822
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    APP_MODE=standalone \
    TMPDIR=/app/tmp \
    NUMBA_CACHE_DIR=/app/tmp/numba_cache \
    LLVMLITE_TMPDIR=/app/tmp \
    MPLCONFIGDIR=/app/tmp/matplotlib \
    OPENBLAS_NUM_THREADS=2 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    NUMEXPR_NUM_THREADS=2 \
    NUMBA_NUM_THREADS=2 \
    BROWSER_PATH=/usr/bin/chromium \
    CHROME_BIN=/usr/bin/chromium
# --------------------------------------------------------------------------- #
USER appuser
EXPOSE 5000
CMD ["/app/start.sh"]
