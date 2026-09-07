# Resume Ranker UI

React + Vite frontend for the Resume Ranker FastAPI backend (in the repo
root). Covers the full API: job description CRUD, the resume ranking
workflow (upload PDF/DOCX, get similarity scores), keyword search over
stored resumes, and per-job score history.

## Run (dev)

1. Start the API from the repo root: `uvicorn main:app --reload`
2. Here: `npm install` (first time), then `npm run dev`
3. Open http://localhost:5173

The dev server talks to the API at `VITE_API_URL`
(default `http://localhost:8000`, see `.env.example`). The API's CORS
allowlist already includes the Vite dev origin.

Note: the rank and search screens need the local dev API (the slim Docker
image returns 503 for those endpoints).

## Other commands

- `npm run build` — type-check and build to `dist/`
- `npm run lint` — oxlint
- `npm run preview` — serve the production build
