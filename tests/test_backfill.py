from pathlib import Path

from backfill_text import backfill
from db import get_connection, save_resume
from models import ParsedResume
from parse import _to_parsed_resume, parse_resume

SAMPLES_DIR = Path(__file__).parent.parent / "sample_resumes"
GOOD_RESUME = SAMPLES_DIR / "omkar_pathak.docx"


def _store_resume_without_text(tmp_path):
    """Store a parsed sample resume as if parsed before resume_text existed."""
    resume = _to_parsed_resume(parse_resume(str(GOOD_RESUME)))
    resume = resume.model_copy(update={"resume_text": None})
    db_path = str(tmp_path / "resumes.db")
    conn = get_connection(db_path)
    try:
        resume_id = save_resume(conn, resume)
        conn.commit()
    finally:
        conn.close()
    return resume_id, db_path


def test_backfill_extracts_text_from_stored_blobs(tmp_path):
    resume_id, db_path = _store_resume_without_text(tmp_path)

    filled, skipped = backfill(db_path)

    assert (filled, skipped) == (1, 0)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT resume_text FROM resumes WHERE id = ?", (resume_id,)
        ).fetchone()
        fts_count = conn.execute("SELECT count(*) FROM resumes_fts").fetchone()[0]
    finally:
        conn.close()
    assert "Omkar Pathak" in row["resume_text"]
    assert fts_count == 1


def test_backfill_is_idempotent(tmp_path):
    _, db_path = _store_resume_without_text(tmp_path)

    backfill(db_path)
    filled, skipped = backfill(db_path)

    assert (filled, skipped) == (0, 0)


def test_backfill_dry_run_does_not_write(tmp_path):
    resume_id, db_path = _store_resume_without_text(tmp_path)

    filled, skipped = backfill(db_path, dry_run=True)

    assert (filled, skipped) == (1, 0)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT resume_text FROM resumes WHERE id = ?", (resume_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row["resume_text"] is None


def test_backfill_skips_rows_without_blob(tmp_path):
    db_path = str(tmp_path / "resumes.db")
    conn = get_connection(db_path)
    try:
        save_resume(
            conn, ParsedResume(file_path=str(tmp_path / "missing.pdf"), error="boom")
        )
        conn.commit()
    finally:
        conn.close()

    filled, skipped = backfill(db_path)

    assert (filled, skipped) == (0, 0)
