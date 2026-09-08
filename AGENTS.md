# Resume Ranker

## Commands
- Setup (all deps + NLP models): `./setup.sh`
- Run API (dev, SQLite): `uvicorn main:app --reload`
- Run full backend in Docker (api + PostgreSQL, every endpoint incl. rank/search/DOCX preview; needs `OPENROUTER_API_KEY` in `.env`): `docker compose up --build -d`
- Parse resumes: `python parse.py <folder>`
- Semantic match demo (needs `OPENROUTER_API_KEY` in `.env`): `python semantic_match.py [--candidate-id N]`
- Rank one resume (main workflow API, needs `OPENROUTER_API_KEY` in `.env`): `curl -F 'resume_file=@resume.pdf' -F 'job_id=J-1' localhost:8000/resumes/rank` (criteria come from the stored job; create it first via `POST /jobs`)
- Tests: `python -m pytest`
- Frontend UI (React + Vite in `frontend/`, needs the dev API running): `cd frontend && npm install && npm run dev` → http://localhost:5173 (lint: `npm run lint`; prod build: `npm run build`)

## Notes
- `DATABASE_URL` (a SQLAlchemy URL) selects the database; defaults to `sqlite:///resumes.db`. `postgres://` / `postgresql://` URLs are auto-rewritten to use psycopg 3.
- Deps are layered: `requirements-api.txt` (FastAPI/SQLAlchemy), `requirements-parser.txt` (parser + embeddings runtime deps; the Dockerfile installs api+parser), `requirements.txt` (local dev: api + parser + pytest).
- Locally, the `resumes` and `job_descriptions` tables both live in `resumes.db`.
- Embeddings go through `embedding_provider.py`: `EMBEDDING_PROVIDER` (default `openrouter`) + `EMBEDDING_MODEL` (default `openai/text-embedding-3-small`); swap providers by adding a class and registering it in `get_embedding_provider()`.
- `POST /resumes/rank` parses an uploaded resume, stores text/details/file in `RESUMES_DB_PATH` (keyed by file hash, re-uploads upsert), and returns skills/experience/average similarity.
- Scores from `/resumes/rank` are stored in `resume_job_scores` (in `RESUMES_DB_PATH`), keyed by `(resume_id, job_id)` — re-ranking upserts; `job_id` is a soft reference to `job_descriptions` since jobs may live in a different database.
- `GET /jobs/{job_id}/scores` lists stored rankings for a job (best average first, candidate details joined from `resumes`); unknown job ids return `[]` (soft reference).
- `GET /resumes/{resume_id}/file` serves a stored resume for in-browser preview (`file_preview.py`): PDFs inline, DOCX converted to PDF via LibreOffice headless (`soffice`; locally `sudo apt install libreoffice-writer`, bundled in the Docker image), other types download. Converted PDFs are cached in `RESUME_PREVIEW_CACHE_DIR` (local default `resume_previews/`, gitignored; `/data/previews` volume in Docker) keyed by file hash; module lazy-imported like `db` so pared-down installs still boot.
- The API sends CORS headers (default allowlist: the Vite dev origins; override with `CORS_ORIGINS`, comma-separated). The frontend's API base URL is `VITE_API_URL` (default `http://localhost:8000`, see `frontend/.env.example`).
- Docker (`docker compose up --build -d`): jobs live in PostgreSQL (`pgdata` volume), resumes in SQLite (`resumes` volume), converted-preview cache in `previews` volume. The image ships the parser stack (spaCy model + NLTK corpora) and LibreOffice; the api container runs non-root, read-only rootfs with a `/tmp` tmpfs, `cap_drop: ALL`, resource limits via `API_MEM_LIMIT`/`API_CPUS` (see `.env.example`).
