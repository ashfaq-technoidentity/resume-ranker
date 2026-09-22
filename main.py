import asyncio
import concurrent.futures
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
from starlette.convertors import Convertor, register_url_convertor

import agent_api
import jobs_db
from models import (
    BatchInsertJsonRequest,
    BatchResumeItem,
    BatchResumeResponse,
    JobDescription,
    JobDescriptionUpdate,
    JobScoreRecord,
    ResumeRankResult,
    ResumeSearchRequest,
    ResumeSearchResult,
    StoredJobDescription,
)

_RESUME_UPLOAD_EXTENSIONS = (".pdf", ".docx")


async def _sandbox_housekeeping(engine) -> None:
    """Best-effort sandbox hygiene: sweep orphans once, then stop idle ones.

    Retries every minute, so a Docker daemon that comes up after the API is
    still picked up; a disabled or unreachable sandbox is a silent no-op.
    """
    import agent_db
    import sandbox

    swept = False
    while True:
        try:
            manager = sandbox.get_sandbox_manager()
            if not swept:
                swept = True
                manager.sweep_orphans(agent_db.list_session_ids(engine))
            manager.reap_idle()
        except Exception:
            pass  # sandbox disabled / docker down — try again next tick
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass  # python-dotenv is a local-dev convenience; containers inject env vars
    app.state.engine = jobs_db.get_engine()
    jobs_db.init_db(app.state.engine)
    import agent_db

    agent_db.init_db(app.state.engine)
    housekeeping = asyncio.create_task(_sandbox_housekeeping(app.state.engine))
    yield
    housekeeping.cancel()
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

# AI assistant (chat + Docker sandbox observability); degrades to 503s when
# docker or the agent modules are unavailable, like the resume workflow
app.include_router(agent_api.router)


class _JobIdConvertor(Convertor[str]):
    """Matches a job id: any non-empty string, '/' included.

    Job ids are free-form (soft references that may come from other systems),
    so ids like 'ai/ml-tcc' can be stored. The default path converter stops
    at '/', which made such jobs unreachable on every /jobs/{job_id} route:
    servers decode %2F to '/' before routing, so no route matched at all.
    Unlike Starlette's built-in 'path' converter ('.*'), this still requires
    at least one character, so '/jobs/' keeps its redirect-to-'/jobs' behavior.
    """

    regex = ".+"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


register_url_convertor("jobid", _JobIdConvertor())


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


# Registered before /jobs/{job_id:jobid} on purpose: that route's converter
# spans '/', so it would otherwise also match /jobs/<id>/scores.
@app.get(
    "/jobs/{job_id:jobid}/scores",
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


@app.get("/jobs/{job_id:jobid}", response_model=StoredJobDescription)
def get_job(job_id: str, request: Request) -> StoredJobDescription:
    record = jobs_db.get_job(request.app.state.engine, job_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return record


@app.put(
    "/jobs/{job_id:jobid}",
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
    "/jobs/{job_id:jobid}",
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


@app.post(
    "/resumes/batch",
    response_model=BatchResumeResponse,
    summary=(
        "Batch upload and process multiple resumes in parallel, storing text,"
        " parsed details, and files, with optional job scoring."
    ),
)
def batch_upload_resumes(
    request: Request,
    resume_files: Annotated[
        list[UploadFile] | None,
        File(description="Resume files (PDF or DOCX)"),
    ] = None,
    files: Annotated[
        list[UploadFile] | None,
        File(description="Alias for resume_files"),
    ] = None,
    job_id: Annotated[
        str | None,
        Form(description="Optional id of stored job to rank against"),
    ] = None,
) -> BatchResumeResponse:
    all_files = [f for f in (resume_files or []) + (files or []) if f.filename]
    if not all_files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one resume file must be provided",
        )

    clean_job_id = (job_id or "").strip() or None
    skills: list[str] = []
    responsibilities: list[str] = []

    if clean_job_id:
        job = jobs_db.get_job(request.app.state.engine, clean_job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job '{clean_job_id}' doesn't exist",
            )
        skills = _clean_list(job.job_skills)
        responsibilities = _clean_list(job.job_responsibilities)
        if not skills and not responsibilities:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Job '{clean_job_id}' has no skills or responsibilities to rank against",
            )

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

    provider = None
    if clean_job_id:
        try:
            provider = embedding_provider.get_embedding_provider()
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Embedding provider is not configured: {error}",
            ) from error

    db_path = os.environ.get("RESUMES_DB_PATH", db.DEFAULT_DB_PATH)
    work_dir = tempfile.mkdtemp(prefix="resume-batch-")
    try:
        items: list[BatchResumeItem | None] = [None] * len(all_files)
        valid_tasks: list[tuple[int, str, str]] = []

        for idx, upload in enumerate(all_files):
            file_name = os.path.basename((upload.filename or "").replace("\\", "/"))
            extension = os.path.splitext(file_name)[1].lower()
            if extension not in _RESUME_UPLOAD_EXTENSIONS:
                items[idx] = BatchResumeItem(
                    file_name=file_name,
                    status="error",
                    error=(
                        f"Unsupported resume file '{file_name}':"
                        " only PDF and DOCX files are supported"
                    ),
                    job_id=clean_job_id,
                )
                continue

            content = upload.file.read()
            if not content:
                items[idx] = BatchResumeItem(
                    file_name=file_name,
                    status="error",
                    error=f"Resume file '{file_name}' is empty",
                    job_id=clean_job_id,
                )
                continue

            file_dir = os.path.join(work_dir, str(idx))
            os.makedirs(file_dir, exist_ok=True)
            upload_path = os.path.join(file_dir, file_name)
            with open(upload_path, "wb") as f:
                f.write(content)
            valid_tasks.append((idx, file_name, upload_path))

        parse_results: dict[int, parse.ParsedResume] = {}
        if valid_tasks:
            max_workers = min(8, max(1, os.cpu_count() or 1), len(valid_tasks))
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                future_to_idx = {
                    executor.submit(parse.parse_file, task[2]): task[0]
                    for task in valid_tasks
                }
                for future in concurrent.futures.as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        parse_results[idx] = future.result()
                    except Exception as e:
                        items[idx] = BatchResumeItem(
                            file_name=all_files[idx].filename or f"file_{idx}",
                            status="error",
                            error=f"Parsing error: {e}",
                            job_id=clean_job_id,
                        )

        conn = db.get_connection(db_path)
        successful_records: list[tuple[int, dict]] = []
        try:
            for idx, fname, _ in valid_tasks:
                if idx not in parse_results:
                    continue
                parsed = parse_results[idx]
                resume_id = db.save_resume(conn, parsed)
                if parsed.error:
                    items[idx] = BatchResumeItem(
                        file_name=fname,
                        status="error",
                        resume_id=resume_id,
                        error=f"Resume parsing failed: {parsed.error}",
                        job_id=clean_job_id,
                    )
                else:
                    record = dict(db.get_resume(conn, resume_id))
                    items[idx] = BatchResumeItem(
                        file_name=record.get("file_name") or fname,
                        status="success",
                        resume_id=resume_id,
                        file_hash=record.get("file_hash"),
                        name=record.get("name"),
                        email=record.get("email"),
                        skills=record.get("skills") or [],
                        total_experience=record.get("total_experience"),
                        job_id=clean_job_id,
                    )
                    successful_records.append((idx, record))
            conn.commit()

            if clean_job_id and provider is not None and successful_records:
                records_to_rank = [rec for _, rec in successful_records]
                try:
                    match_results = semantic_match.batch_semantic_similarity(
                        provider,
                        records_to_rank,
                        "\n".join(skills),
                        "\n".join(responsibilities),
                    )
                    for (idx, _), match in zip(successful_records, match_results):
                        db.save_job_scores(
                            conn,
                            match["resume_id"],
                            clean_job_id,
                            match["skills_similarity"],
                            match["experience_similarity"],
                            match["average_similarity"],
                            match["model"],
                        )
                        item = items[idx]
                        if item is not None:
                            item.candidate_skills = match["candidate_skills"]
                            item.candidate_experience = match["candidate_experience"]
                            item.skills_similarity = match["skills_similarity"]
                            item.experience_similarity = match["experience_similarity"]
                            item.average_similarity = match["average_similarity"]
                            item.model = match["model"]
                    conn.commit()
                except Exception as e:
                    for idx, _ in successful_records:
                        item = items[idx]
                        if item is not None:
                            item.status = "error"
                            item.error = f"Similarity calculation failed: {e}"
        finally:
            conn.close()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    final_items = [item for item in items if item is not None]
    succeeded = sum(1 for item in final_items if item.status == "success")
    failed = len(final_items) - succeeded

    return BatchResumeResponse(
        total=len(final_items),
        succeeded=succeeded,
        failed=failed,
        items=final_items,
    )


@app.post(
    "/resumes/batch-json",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Batch insert pre-parsed resumes via JSON",
)
def batch_insert_resumes_json(
    payload: BatchInsertJsonRequest,
) -> dict:
    if not payload.resumes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one resume must be provided",
        )
    db_path = os.environ.get("RESUMES_DB_PATH", "resumes.db")
    try:
        import db
    except ImportError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resume database module is unavailable: {error}",
        ) from error

    conn = db.get_connection(db_path)
    try:
        ids = db.save_resumes(conn, payload.resumes)
    finally:
        conn.close()
    return {"total": len(ids), "resume_ids": ids}


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
