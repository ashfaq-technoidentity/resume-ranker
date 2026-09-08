# syntax=docker/dockerfile:1

# ---- builder: venv with the API + resume-workflow dependencies ----
FROM python:3.12-slim-bookworm AS builder
WORKDIR /build
COPY requirements-api.txt requirements-parser.txt ./
# The spaCy model and NLTK corpora are what setup.sh fetches for local dev;
# the pinned model wheel is the fallback when `spacy download` can't match
# the installed spaCy version.
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements-api.txt -r requirements-parser.txt \
    && { /opt/venv/bin/python -m spacy download en_core_web_sm \
        || /opt/venv/bin/pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl; } \
    && /opt/venv/bin/python -m nltk.downloader -d /opt/nltk_data words stopwords

# ---- runtime: the full backend (jobs API + parse/rank/search/preview) ----
FROM python:3.12-slim-bookworm AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    NLTK_DATA=/opt/nltk_data \
    XDG_CACHE_HOME=/tmp/xdg-cache \
    RESUMES_DB_PATH=/data/resumes/resumes.db \
    RESUME_PREVIEW_CACHE_DIR=/data/previews
# LibreOffice (used by file_preview.py) converts stored DOCX resumes to PDF
# for browser previews; liberation/dejavu fonts keep the converted output
# readable. XDG_CACHE_HOME points fontconfig's cache at the writable /tmp
# (the container runs with a read-only root filesystem in compose).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer fonts-liberation fonts-dejavu-core
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /data/resumes /data/previews \
    && chown -R app:app /data
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/nltk_data /opt/nltk_data
COPY main.py jobs_db.py models.py db.py parse.py keyword_search.py \
    semantic_match.py embedding_provider.py file_preview.py ./
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["sh", "-c", "python -m jobs_db && exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}"]
