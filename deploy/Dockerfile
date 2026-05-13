# syntax=docker/dockerfile:1.7

# ---------- Stage 1: build ----------
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv==0.4.30

WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --frozen --no-dev

RUN /opt/venv/bin/python -m spacy download en_core_web_lg

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && curl -sSL -o /usr/local/bin/cosign https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64 \
 && chmod +x /usr/local/bin/cosign \
 && curl -sSL https://github.com/oras-project/oras/releases/latest/download/oras_linux_amd64.tar.gz | tar -xz -C /usr/local/bin oras \
 && chmod +x /usr/local/bin/oras \
 && apt-get purge -y --auto-remove curl \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd -r ag && useradd -r -g ag -u 10001 -m -d /home/ag ag

COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY --from=builder /src/src /app/src
COPY litellm_config.yaml /etc/gateway/litellm_config.yaml

USER ag
ENV PYTHONPATH=/app/src
EXPOSE 8000
ENTRYPOINT ["python", "-m", "ag_gateway"]
