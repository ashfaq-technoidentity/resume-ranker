import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from sqlalchemy import text

import jobs_db
from models import (
    JobDescription,
    ResumeSearchRequest,
    ResumeSearchResult,
    StoredJobDescription,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = jobs_db.get_engine()
    jobs_db.init_db(app.state.engine)
    yield
    app.state.engine.dispose()


app = FastAPI(
    title="Resume Ranker API",
    description="Stores job descriptions used to rank parsed resumes.",
    lifespan=lifespan,
)


@app.post(
    "/jobs",
    response_model=StoredJobDescription,
    status_code=status.HTTP_201_CREATED,
    summary="Store a job description (upserts on job_id)",
)
def store_job(job: JobDescription, request: Request) -> StoredJobDescription:
    return jobs_db.upsert_job(request.app.state.engine, job)


@app.get("/jobs", response_model=list[StoredJobDescription])
def list_jobs(request: Request) -> list[StoredJobDescription]:
    return jobs_db.list_jobs(request.app.state.engine)


@app.get("/jobs/{job_id}", response_model=StoredJobDescription)
def get_job(job_id: str, request: Request) -> StoredJobDescription:
    record = jobs_db.get_job(request.app.state.engine, job_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return record


@app.post(
    "/resumes/search",
    response_model=list[ResumeSearchResult],
    summary="Search stored resumes by keywords, best matches first",
)
def search_resumes_by_keywords(
    search: ResumeSearchRequest,
) -> list[ResumeSearchResult]:
    # db/keyword_search are SQLite-only modules not shipped in the Docker
    # image, so they are imported lazily; the 503 below fires first there.
    db_path = os.environ.get("RESUMES_DB_PATH", "resumes.db")
    if not os.path.exists(db_path):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resume database not available at '{db_path}'",
        )
    import keyword_search

    if not keyword_search.normalize_keywords(search.keywords):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one non-empty keyword is required",
        )
    results = keyword_search.search_resumes(search.keywords, db_path=db_path)
    return [ResumeSearchResult(**result) for result in results]


@app.get("/health")
def health(request: Request) -> dict:
    with request.app.state.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": request.app.state.engine.dialect.name}
