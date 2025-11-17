#
# Multi-stage Dockerfile
# - Builder stage creates a dedicated virtualenv at /opt/venv
# - Final runtime is non-root and uses the prebuilt venv
#

ARG PYTHON_VERSION=3.12-slim

# ---- Builder ----
FROM python:${PYTHON_VERSION} AS builder

ENV VENV_PATH=/opt/venv
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtualenv
RUN python -m venv ${VENV_PATH}
ENV PATH="${VENV_PATH}/bin:${PATH}"

# Leverage layer caching by copying only lock/requirements first
COPY requirements.txt /app/requirements.txt
COPY requirements-dev.txt /app/requirements-dev.txt
RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt

# ---- Runtime ----
FROM python:${PYTHON_VERSION} AS runtime

ENV VENV_PATH=/opt/venv
ENV PATH="${VENV_PATH}/bin:${PATH}" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user
RUN addgroup --system app && adduser --system --ingroup app appuser

# Minimal OS packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy prebuilt virtualenv from builder
COPY --from=builder ${VENV_PATH} ${VENV_PATH}

# Copy application source
COPY . /app

# Ensure permissions for non-root
RUN chown -R appuser:app /app

USER appuser

# Entrypoint script (handles migrations + start)
# Use sh to execute script, which doesn't require execute permissions
ENTRYPOINT ["sh", "scripts/docker/entrypoint.sh"]
