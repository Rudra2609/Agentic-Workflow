# Sandbox image for running untrusted Python code and its tests (Sprint 8, plan D3). Built once, with the internet:
#   make sandbox-image        (= docker build -t hmap-sandbox-py:1 backend/src/hmap/agents/testing/sandbox)
# Every run then uses --network none, a read-only root filesystem, a non-root user and resource limits
# (sandbox/docker.py). Versions pinned so results do not change between builds.
FROM python:3.11.17-slim
RUN pip install --no-cache-dir pytest==9.1.1 coverage==7.11.0 ruff==0.16.9 mypy==1.18.2 bandit==1.9.4 \
                               hypothesis==6.169.0 \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox
COPY stages.py /opt/hmap/stages.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp MYPY_CACHE_DIR=/tmp/hmap/mypy
USER 10001
WORKDIR /work
LABEL hmap.sandbox.image="1"
