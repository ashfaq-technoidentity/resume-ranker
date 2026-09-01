# Resume Ranker

## Commands
- Setup (all deps + NLP models): `./setup.sh`
- Run API (dev, SQLite): `uvicorn main:app --reload`
- Run API (prod, PostgreSQL): `docker compose up --build`
- Parse resumes: `python parse.py <folder>`
- Tests: `python -m pytest`

## Notes
- `DATABASE_URL` (a SQLAlchemy URL) selects the database; defaults to `sqlite:///resumes.db`. `postgres://` / `postgresql://` URLs are auto-rewritten to use psycopg 3.
- API/prod deps live in `requirements-api.txt` (used by the Dockerfile); `requirements.txt` adds parser and test deps for local dev.
- Locally, the `resumes` and `job_descriptions` tables both live in `resumes.db`.
