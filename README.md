# Resume Ranker

Store job descriptions, rank uploaded resumes against them with semantic
similarity, search the resume pool by keyword, and — through the built-in
**AI Assistant** — ask natural-language questions about your candidates,
answered by an agent that writes and runs Python inside per-session Docker
sandboxes.

## Features

- **Jobs** — store job descriptions (skills, responsibilities, posted date) with upsert-on-id semantics.
- **Rank resume** — upload a PDF/DOCX; it's parsed, stored (text, details, file), and scored against a stored job's criteria using embeddings (cosine similarity over skills and experience chunks).
- **Search** — full-text (SQLite FTS5) keyword search over stored resume text, best matches first.
- **Score history** — stored rankings per job, best candidates first, with in-browser resume preview (DOCX is converted to PDF server-side).
- **AI Assistant** — a ChatGPT-style chat that executes code in a hardened Docker sandbox per session: the agent installs packages it needs (e.g. `pypdf`), reads your resume database (mounted read-only), and returns answers with clickable resume links. You can watch its steps live, browse its files, stream its docker logs, and reset its sandbox. See [docs/ai-assistant.md](docs/ai-assistant.md).

## Quickstart (local dev)

```bash
./setup.sh                       # python deps + spaCy model + NLTK corpora
cp .env.example .env              # then set OPENROUTER_API_KEY
uvicorn main:app --reload        # API on http://localhost:8000
```

The resume workflow (rank/search/preview) and the jobs API work with a plain
SQLite database (`resumes.db`, auto-created). For the AI Assistant, also
build its sandbox image once:

```bash
docker build --target sandbox -t resume-ranker-sandbox .
```

### Frontend

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

Lint and production build: `npm run lint`, `npm run build`.

### Docker (api + PostgreSQL)

```bash
docker compose up --build -d
```

Jobs live in PostgreSQL; resumes (SQLite), the preview cache, and the agent
tables live on named volumes. To enable the AI Assistant's sandboxes when
the api itself runs in compose, use the opt-in override (it mounts the Docker
socket — see the security notes in [docs/ai-assistant.md](docs/ai-assistant.md)):

```bash
echo "DOCKER_GID=$(getent group docker | cut -d: -f3)" >> .env
docker compose -f docker-compose.yml -f docker-compose.sandbox.yml \
    --profile sandbox up --build -d
```

## Configuration

Everything is env-driven (see [.env.example](.env.example) for the full list).

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required for ranking (embeddings) and the AI assistant (chat) |
| `DATABASE_URL` | `sqlite:///resumes.db` | SQLAlchemy URL for jobs/agent tables (`postgres://` URLs are rewritten to psycopg 3) |
| `RESUMES_DB_PATH` | `resumes.db` | SQLite resume database (files, text, scores) |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` | `openrouter` / `openai/text-embedding-3-small` | Ranking embeddings |
| `CORS_ORIGINS` | Vite dev origins | Allowed browser origins |
| `AGENT_MODEL` | `anthropic/claude-sonnet-4.5` | AI assistant brain (any OpenRouter chat model) |
| `AGENT_MAX_TOKENS` | `4096` | Per-turn output cap (keeps OpenRouter's credit check small) |
| `SANDBOX_IMAGE` | `resume-ranker-sandbox` | Image used for sandbox containers |
| `SANDBOX_EXEC_TIMEOUT` | `120` | Seconds before a runaway script is killed |
| `SANDBOX_MEM_LIMIT` / `SANDBOX_CPUS` / `SANDBOX_PIDS_LIMIT` | `1g` / `1.0` / `256` | Sandbox container resources |
| `SANDBOX_IDLE_TIMEOUT` | `1800` | Seconds of inactivity before a sandbox is stopped |
| `SANDBOX_ENABLED` | `1` | Set `0` to disable the assistant (endpoints return 503) |

## Testing

```bash
python -m pytest                                    # unit tests (no docker needed)
docker build --target sandbox -t resume-ranker-sandbox .
SANDBOX_INTEGRATION=1 python -m pytest tests/test_sandbox_integration.py -v
```

## Project layout

```
main.py              FastAPI app (jobs, rank, search, preview, health)
agent_api.py         /agent endpoints (sessions, chat SSE, sandbox observability)
agent.py             tool-calling agent loop + system prompt + event bus
agent_llm.py         OpenRouter chat client (tool calling)
agent_db.py          agent_sessions / agent_messages / agent_events tables
sandbox.py           SandboxManager (containers, exec, logs, files, housekeeping)
sandbox/             agent-run / agent-pip wrappers baked into the sandbox image
db.py, parse.py, keyword_search.py, semantic_match.py, embedding_provider.py,
file_preview.py      resume storage, parsing, FTS search, embeddings, previews
jobs_db.py, models.py
frontend/            React + Vite UI (Jobs, Rank, Search, History, AI Assistant)
tests/               unit tests + opt-in docker integration tests
```

See [AGENTS.md](AGENTS.md) for developer notes and
[docs/ai-assistant.md](docs/ai-assistant.md) for the AI Assistant reference.
