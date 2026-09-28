# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# MedAgent container image.
#
#   docker build -t medagent .                          # lean: deterministic fallbacks only
#   docker build -t medagent --build-arg EXTRAS=nlp .   # + scispaCy NER and NegEx (~120 MB model)
#   docker build -t medagent --build-arg EXTRAS=ml .    # + MedCPT and BioELECTRA-PICO (torch, large)
#
#   docker run --env-file .env -p 8000:8000 medagent
#
# The server listens on $PORT (Render, Railway, Fly and Cloud Run all set it), defaulting to 8000.
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12

# --- build stage: install the package and its dependencies into a venv ------
FROM python:${PYTHON_VERSION}-slim AS builder

ARG EXTRAS=""

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Compilers only for the optional ML extras (e.g. scispaCy's nmslib has no wheel for every platform).
RUN if [ -n "$EXTRAS" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends build-essential git \
      && rm -rf /var/lib/apt/lists/*; \
    fi

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /src
COPY pyproject.toml README.md ./
COPY medagent ./medagent

# CPU-only torch keeps the "ml" image a few GB smaller than the default CUDA build.
RUN pip install --upgrade pip \
    && if [ -n "$EXTRAS" ]; then \
         pip install --extra-index-url https://download.pytorch.org/whl/cpu ".[${EXTRAS}]"; \
       else \
         pip install .; \
       fi

# --- runtime stage -----------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    MEDAGENT_DATA_DIR=/app/data \
    HF_HOME=/app/.cache/huggingface

RUN useradd --create-home --uid 1000 medagent \
    && mkdir -p /app/data /app/.cache \
    && chown -R medagent:medagent /app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
USER medagent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"

# sh -c so $PORT is expanded at run time; exec so uvicorn receives SIGTERM directly.
CMD ["sh", "-c", "exec uvicorn medagent.server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
