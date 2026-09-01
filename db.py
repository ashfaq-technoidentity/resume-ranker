"""SQLite storage for parsed resumes.

Each row stores the parsed fields from :class:`models.ParsedResume` together
with the resume file itself (as a BLOB). Rows are keyed by the SHA-256 hash of
the file content, so re-parsing an unchanged file updates its row instead of
duplicating it.
"""

import hashlib
import json
import os
import sqlite3

from models import ParsedResume

DEFAULT_DB_PATH = "resumes.db"

_JSON_LIST_COLUMNS = (
    "skills",
    "degree",
    "designation",
    "company_names",
    "college_name",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    file_name TEXT,
    file_ext TEXT,
    file_size INTEGER,
    file_hash TEXT UNIQUE,
    file_blob BLOB,
    name TEXT,
    email TEXT,
    mobile_number TEXT,
    skills TEXT NOT NULL DEFAULT '[]',
    degree TEXT NOT NULL DEFAULT '[]',
    designation TEXT NOT NULL DEFAULT '[]',
    company_names TEXT NOT NULL DEFAULT '[]',
    college_name TEXT NOT NULL DEFAULT '[]',
    total_experience REAL,
    no_of_pages INTEGER,
    raw TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_INSERT_SQL = """
INSERT INTO resumes (
    file_path, file_name, file_ext, file_size, file_hash, file_blob,
    name, email, mobile_number, skills, degree, designation,
    company_names, college_name, total_experience, no_of_pages,
    raw, error
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(file_hash) DO UPDATE SET
    file_path = excluded.file_path,
    file_name = excluded.file_name,
    file_ext = excluded.file_ext,
    file_size = excluded.file_size,
    file_blob = excluded.file_blob,
    name = excluded.name,
    email = excluded.email,
    mobile_number = excluded.mobile_number,
    skills = excluded.skills,
    degree = excluded.degree,
    designation = excluded.designation,
    company_names = excluded.company_names,
    college_name = excluded.college_name,
    total_experience = excluded.total_experience,
    no_of_pages = excluded.no_of_pages,
    raw = excluded.raw,
    error = excluded.error,
    updated_at = datetime('now')
"""

_SELECT_COLUMNS = """
    id, file_path, file_name, file_ext, file_size, file_hash,
    name, email, mobile_number, skills, degree, designation,
    company_names, college_name, total_experience, no_of_pages,
    raw, error, created_at, updated_at
"""


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (and initialize, if needed) the database at ``db_path``."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _read_file(file_path: str) -> tuple[bytes | None, int | None, str | None]:
    try:
        with open(file_path, "rb") as f:
            blob = f.read()
    except OSError:
        return None, None, None
    return blob, len(blob), hashlib.sha256(blob).hexdigest()


def save_resume(conn: sqlite3.Connection, resume: ParsedResume) -> int:
    """Store one parsed resume and its file in the database.

    Returns the row id. Saving a file whose content is already stored updates
    the existing row (keyed by content hash) instead of adding a new one.
    """
    blob, file_size, file_hash = _read_file(resume.file_path)
    cur = conn.execute(
        _INSERT_SQL,
        (
            resume.file_path,
            os.path.basename(resume.file_path),
            os.path.splitext(resume.file_path)[1].lstrip(".").lower(),
            file_size,
            file_hash,
            blob,
            resume.name,
            resume.email,
            resume.mobile_number,
            json.dumps(resume.skills),
            json.dumps(resume.degree),
            json.dumps(resume.designation),
            json.dumps(resume.company_names),
            json.dumps(resume.college_name),
            resume.total_experience,
            resume.no_of_pages,
            json.dumps(resume.raw, default=str),
            resume.error,
        ),
    )
    if file_hash is None:
        return cur.lastrowid
    row = conn.execute(
        "SELECT id FROM resumes WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    return row["id"]


def save_resumes(conn: sqlite3.Connection, resumes: list[ParsedResume]) -> list[int]:
    """Store many parsed resumes in one transaction; returns their row ids."""
    ids = [save_resume(conn, resume) for resume in resumes]
    conn.commit()
    return ids


def _row_to_record(row: sqlite3.Row) -> dict:
    record = dict(row)
    for column in _JSON_LIST_COLUMNS:
        record[column] = json.loads(record[column])
    record["raw"] = json.loads(record["raw"])
    return record


def get_all_resumes(conn: sqlite3.Connection) -> list[dict]:
    """Return every stored resume (parsed fields + file metadata, no blob)."""
    rows = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM resumes ORDER BY id"
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def get_resume_file(conn: sqlite3.Connection, resume_id: int) -> bytes | None:
    """Return the stored resume file bytes for ``resume_id``, if any."""
    row = conn.execute(
        "SELECT file_blob FROM resumes WHERE id = ?", (resume_id,)
    ).fetchone()
    if row is None or row["file_blob"] is None:
        return None
    return bytes(row["file_blob"])
