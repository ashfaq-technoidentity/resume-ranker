"""Backfill resume_text for rows stored before the column existed.

For every resume row whose resume_text is NULL and whose file blob is stored,
the blob is written to a temporary file, its text is extracted with the same
functions the parser uses, and both the resumes row and the FTS index are
updated. Additive and idempotent: rows that already have text (or whose
extraction fails) are left untouched.

Usage:
    python backfill_text.py [--db resumes.db] [--dry-run]
"""

import argparse
import os
import tempfile

import db
from parse import extract_resume_text


def backfill(db_path: str, dry_run: bool = False) -> tuple[int, int]:
    """Fill in missing resume_text values from stored file blobs.

    Returns (filled, skipped): rows whose text was extracted and rows that
    could not be (no blob, unsupported extension, or extraction failure).
    """
    conn = db.get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, file_ext, file_blob FROM resumes "
            "WHERE resume_text IS NULL AND file_blob IS NOT NULL"
        ).fetchall()
        filled = skipped = 0
        for row in rows:
            text = _extract_text_from_blob(row["file_blob"], row["file_ext"] or "")
            if text is None:
                skipped += 1
                continue
            if dry_run:
                filled += 1
                continue
            db.update_resume_text(conn, row["id"], text)
            filled += 1
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return filled, skipped


def _extract_text_from_blob(blob: bytes, file_ext: str) -> str | None:
    suffix = ("." + file_ext.lstrip(".")).lower() if file_ext else ""
    if suffix not in (".pdf", ".docx", ".doc"):
        return None
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob)
        tmp_path = tmp.name
    try:
        return extract_resume_text(tmp_path)
    finally:
        os.unlink(tmp_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill resume_text from stored file blobs so keyword search works on old rows."
    )
    parser.add_argument(
        "--db",
        default=db.DEFAULT_DB_PATH,
        help=f"Path to the SQLite database file (default: {db.DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be backfilled without writing changes",
    )
    args = parser.parse_args()

    filled, skipped = backfill(args.db, dry_run=args.dry_run)
    prefix = "Would backfill" if args.dry_run else "Backfilled"
    print(f"{prefix} {filled} resume(s) in {args.db}")
    if skipped:
        print(f"Skipped {skipped} resume(s) with no extractable text")


if __name__ == "__main__":
    main()
