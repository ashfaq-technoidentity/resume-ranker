import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import jobs_db
from models import (
    JobDescription,
    JobDescriptionUpdate,
    JobScoreRecord,
    ResumeRankResult,
    ResumeSearchRequest,
    ResumeSearchResult,
    StoredJobDescription,
)

_RESUME_UPLOAD_EXTENSIONS = (".pdf", ".docx")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass  # python-dotenv is a local-dev convenience; containers inject env vars
    app.state.engine = jobs_db.get_engine()
    jobs_db.init_db(app.state.engine)
    yield
    app.state.engine.dispose()


app = FastAPI(
    title="Resume Ranker API",
    description=(
        "Stores job descriptions and ranks uploaded resumes against a job's"
        " skills and responsibilities (parse, store, semantic match)."
    ),
    lifespan=lifespan,
)

# The Vite dev server (frontend/) is on the default allowlist; override with
# CORS_ORIGINS (comma-separated origins) for other setups.
_DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.put(
    "/jobs/{job_id}",
    response_model=StoredJobDescription,
    summary="Update a stored job description (only provided fields change)",
)
def update_job(
    job_id: str, changes: JobDescriptionUpdate, request: Request
) -> StoredJobDescription:
    updates = changes.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No fields to update provided",
        )
    record = jobs_db.update_job(request.app.state.engine, job_id, updates)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return record


@app.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a stored job description",
)
def delete_job(job_id: str, request: Request) -> None:
    if not jobs_db.delete_job(request.app.state.engine, job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )


@app.post(
    "/resumes/search",
    response_model=list[ResumeSearchResult],
    summary="Search stored resumes by keywords, best matches first",
)
def search_resumes_by_keywords(
    search: ResumeSearchRequest,
) -> list[ResumeSearchResult]:
    # db/keyword_search are SQLite-only modules, imported lazily so an
    # install without them still serves the rest of the API (503 below).
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


def _clean_list(values: list[str] | None) -> list[str]:
    return [item.strip() for item in values or [] if item and item.strip()]


@app.post(
    "/resumes/rank",
    response_model=ResumeRankResult,
    summary=(
        "Main workflow: upload a resume, parse and store it (text, parsed"
        " details, and file), score it against the stored job, and store the"
        " scores"
    ),
)
def rank_resume(
    request: Request,
    resume_file: Annotated[UploadFile, File(description="Resume file (PDF or DOCX)")],
    job_id: Annotated[
        str,
        Form(
            min_length=1,
            max_length=255,
            description="Id of the stored job to rank against",
        ),
    ],
) -> ResumeRankResult:
    """Parse the uploaded resume, store it with its file in the resumes
    database, return cosine similarity scores comparing the candidate's
    skills and experience with the stored job's skills and responsibilities,
    and store those scores in ``resume_job_scores`` keyed by (resume, job)."""
    # file_name is only used as a basename inside a private temp dir, but be
    # strict anyway: no client-supplied path pieces may survive
    file_name = os.path.basename((resume_file.filename or "").replace("\\", "/"))
    extension = os.path.splitext(file_name)[1].lower()
    if extension not in _RESUME_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported resume file '{resume_file.filename or ''}':"
                f" only PDF and DOCX files are supported"
            ),
        )
    content = resume_file.file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Resume file '{file_name}' is empty",
        )
    job = jobs_db.get_job(request.app.state.engine, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' doesn't exist",
        )
    skills = _clean_list(job.job_skills)
    responsibilities = _clean_list(job.job_responsibilities)
    if not skills and not responsibilities:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Job '{job_id}' has no skills or responsibilities to rank against",
        )

    # parser/resume-storage/semantic-match modules are imported lazily so an
    # install without them still serves the rest of the API; the 503 below
    # fires first instead of crashing the app at import time.
    try:
        import db
        import embedding_provider
        import parse
        import semantic_match
    except ImportError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resume workflow modules are unavailable: {error}",
        ) from error

    try:
        provider = embedding_provider.get_embedding_provider()
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding provider is not configured: {error}",
        ) from error

    db_path = os.environ.get("RESUMES_DB_PATH", db.DEFAULT_DB_PATH)
    work_dir = tempfile.mkdtemp(prefix="resume-rank-")
    try:
        upload_path = os.path.join(work_dir, file_name)
        with open(upload_path, "wb") as f:
            f.write(content)
        parsed = parse.parse_file(upload_path)

        conn = db.get_connection(db_path)
        try:
            resume_id = db.save_resume(conn, parsed)
            # save_resume() itself does not commit (save_resumes() does for
            # batches), so persist here before the connection closes
            conn.commit()
            if parsed.error:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Resume parsing failed: {parsed.error}",
                )
            record = db.get_resume(conn, resume_id)
        finally:
            conn.close()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    try:
        match = semantic_match.semantic_similarity(
            provider,
            resume_id,
            "\n".join(skills),
            "\n".join(responsibilities),
            db_path=db_path,
        )
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Similarity calculation failed: {error}",
        ) from error

    conn = db.get_connection(db_path)
    try:
        db.save_job_scores(
            conn,
            resume_id,
            job_id,
            match["skills_similarity"],
            match["experience_similarity"],
            match["average_similarity"],
            match["model"],
        )
        conn.commit()
    finally:
        conn.close()

    return ResumeRankResult(
        resume_id=resume_id,
        job_id=job_id,
        file_name=record["file_name"],
        file_hash=record["file_hash"],
        name=record["name"],
        email=record["email"],
        skills=record["skills"],
        total_experience=record["total_experience"],
        model=match["model"],
        candidate_skills=match["candidate_skills"],
        candidate_experience=match["candidate_experience"],
        skills_similarity=match["skills_similarity"],
        experience_similarity=match["experience_similarity"],
        average_similarity=match["average_similarity"],
    )


@app.get(
    "/jobs/{job_id}/scores",
    response_model=list[JobScoreRecord],
    summary="List stored scores for a job, best average similarity first",
)
def list_job_scores(job_id: str) -> list[JobScoreRecord]:
    """Return every resume ranked against ``job_id``, best candidates first.

    ``job_id`` is a soft reference (the job may live in a different database
    in production), so an unknown job id returns an empty list rather than
    404.
    """
    # db is a SQLite-only module not shipped in the Docker image, so it is
    # imported lazily; the 503 below fires first there.
    db_path = os.environ.get("RESUMES_DB_PATH", "resumes.db")
    if not os.path.exists(db_path):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resume database not available at '{db_path}'",
        )
    import db

    conn = db.get_connection(db_path)
    try:
        records = db.list_job_scores(conn, job_id)
    finally:
        conn.close()
    return [JobScoreRecord(**record) for record in records]


@app.get(
    "/resumes/{resume_id}/file",
    summary="Preview a stored resume in the browser (DOCX is converted to PDF)",
)
def get_resume_file(resume_id: int) -> Response:
    """Serve the stored file of one resume for in-browser viewing: PDF files
    pass through, DOCX files are converted to PDF server-side (cached by
    content hash), and other file types download as attachments."""
    # db/file_preview are imported lazily so an install without them still
    # serves the rest of the API; the 503 below fires first there.
    db_path = os.environ.get("RESUMES_DB_PATH", "resumes.db")
    if not os.path.exists(db_path):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resume database not available at '{db_path}'",
        )
    try:
        import db
        import file_preview
    except ImportError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resume workflow modules are unavailable: {error}",
        ) from error

    conn = db.get_connection(db_path)
    try:
        record = db.get_resume(conn, resume_id)
        blob = db.get_resume_file(conn, resume_id) if record is not None else None
    finally:
        conn.close()
    if record is None or blob is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Resume '{resume_id}' or its stored file not found",
        )

    try:
        body, media_type, disposition = file_preview.build_preview(blob, record)
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resume preview unavailable: {error}",
        ) from error
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@app.get("/health")
def health(request: Request) -> dict:
    with request.app.state.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": request.app.state.engine.dialect.name}
