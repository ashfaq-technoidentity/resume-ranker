from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from sqlalchemy import text

import jobs_db
from models import JobDescription, StoredJobDescription


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


@app.get("/health")
def health(request: Request) -> dict:
    with request.app.state.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": request.app.state.engine.dialect.name}
