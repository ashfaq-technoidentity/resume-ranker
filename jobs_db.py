"""Job description storage.

Backed by SQLAlchemy Core so the same code runs on SQLite (default, zero
config) and PostgreSQL (via DATABASE_URL, used by the Docker deployment).
"""

import os
from datetime import date

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Engine,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    inspect,
    select,
    text,
    update,
)

from models import JobDescription, StoredJobDescription

DEFAULT_DATABASE_URL = "sqlite:///resumes.db"

metadata = MetaData()

job_descriptions = Table(
    "job_descriptions",
    metadata,
    Column("job_id", String(255), primary_key=True),
    Column("description", Text, nullable=False),
    Column("posted_date", Date, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
    Column("job_skills", JSON, nullable=False),
    Column("job_responsibilities", JSON, nullable=False),
)


def _normalize_url(url: str) -> str:
    """Point bare postgres URLs at psycopg 3 (SQLAlchemy's default is psycopg2)."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_engine(database_url: str | None = None) -> Engine:
    """Create an engine from an explicit URL, DATABASE_URL, or the SQLite default."""
    url = _normalize_url(
        database_url or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    )
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    """create_all() never alters existing tables, so append newer columns by hand."""
    inspector = inspect(engine)
    if not inspector.has_table(job_descriptions.name):
        return
    existing = {
        column["name"] for column in inspector.get_columns(job_descriptions.name)
    }
    missing = [
        column for column in job_descriptions.columns if column.name not in existing
    ]
    if not missing:
        return
    with engine.begin() as conn:
        for column in missing:
            column_type = column.type.compile(engine.dialect)
            conn.execute(
                text(
                    f"ALTER TABLE {job_descriptions.name} "
                    f"ADD COLUMN {column.name} {column_type}"
                )
            )


def upsert_job(engine: Engine, job: JobDescription) -> StoredJobDescription:
    """Insert the job description, or update the row if job_id already exists."""
    posted_date = job.posted_date or date.today()
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = (
        insert(job_descriptions)
        .values(
            job_id=job.job_id,
            description=job.description,
            posted_date=posted_date,
            job_skills=job.job_skills,
            job_responsibilities=job.job_responsibilities,
        )
        .on_conflict_do_update(
            index_elements=[job_descriptions.c.job_id],
            set_={
                "description": job.description,
                "posted_date": posted_date,
                "job_skills": job.job_skills,
                "job_responsibilities": job.job_responsibilities,
                "updated_at": func.now(),
            },
        )
    )
    with engine.begin() as conn:
        conn.execute(stmt)
        row = (
            conn.execute(
                select(job_descriptions).where(job_descriptions.c.job_id == job.job_id)
            )
            .mappings()
            .one()
        )
    return StoredJobDescription(**row)


def get_job(engine: Engine, job_id: str) -> StoredJobDescription | None:
    stmt = select(job_descriptions).where(job_descriptions.c.job_id == job_id)
    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()
    return StoredJobDescription(**row) if row else None


def list_jobs(engine: Engine) -> list[StoredJobDescription]:
    stmt = select(job_descriptions).order_by(
        job_descriptions.c.posted_date.desc(), job_descriptions.c.job_id
    )
    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return [StoredJobDescription(**row) for row in rows]


def update_job(
    engine: Engine, job_id: str, changes: dict[str, object]
) -> StoredJobDescription | None:
    """Update the given columns of a job; None when job_id is unknown."""
    stmt = (
        update(job_descriptions)
        .where(job_descriptions.c.job_id == job_id)
        .values({**changes, "updated_at": func.now()})
    )
    with engine.begin() as conn:
        conn.execute(stmt)
        row = (
            conn.execute(
                select(job_descriptions).where(job_descriptions.c.job_id == job_id)
            )
            .mappings()
            .first()
        )
    return StoredJobDescription(**row) if row else None


def delete_job(engine: Engine, job_id: str) -> bool:
    """Remove a job description; True when a row was actually deleted."""
    stmt = delete(job_descriptions).where(job_descriptions.c.job_id == job_id)
    with engine.begin() as conn:
        deleted = conn.execute(stmt).rowcount
    return deleted > 0


if __name__ == "__main__":
    engine = get_engine()
    init_db(engine)
    print(f"Job descriptions table ready in {engine.url}")
