# Sandbox image for running untrusted Python code and its tests (Member 8, prototype for Sprint 8 item 8.1).
# Built once (with network); every run then uses --network none, a read-only root filesystem, a non-root user and
# resource limits (see run_sandbox.py).
FROM python:3.11.17-slim
RUN pip install --no-cache-dir pytest==9.1.1 ruff==0.16.9 bandit==1.9.4 \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox
COPY stages.py /opt/hmap/stages.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
USER 10001
WORKDIR /work
