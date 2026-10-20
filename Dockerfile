ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}

# Override for a regional mirror, e.g. https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies are copied first so the pip layer survives source-only edits.
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY pragent ./pragent
COPY web ./web
COPY skills ./skills

# The service runs unprivileged; /app/data holds the SQLite fallback and volatile artifacts.
RUN groupadd --gid 10001 pragent \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin pragent \
    && mkdir -p /app/data \
    && chown -R pragent:pragent /app

USER pragent

ENV PRAGENT_HOST=0.0.0.0 \
    PRAGENT_PORT=8080 \
    PRAGENT_SKILLS_DIR=/app/skills \
    PRAGENT_DB_PATH=/app/data/pragent.db

EXPOSE 8080

# /health is unauthenticated and reports reviewer, queue backend and run mode.
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=5 \
    CMD ["python", "-c", "import os, sys, urllib.request; port = os.getenv('PRAGENT_PORT', '8080'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + port + '/health', timeout=4).status == 200 else 1)"]

CMD ["python", "-m", "pragent"]
