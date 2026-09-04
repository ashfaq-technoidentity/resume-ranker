"""Keyword search over stored resume text.

The resumes_fts FTS5 index shortlists candidates matching any keyword, then
each shortlisted resume is reranked in Python: the primary sort is the number
of distinct query keywords found, the secondary sort is the total occurrence
count. Keyword counting is case-insensitive and word-boundary aware, so
"python" does not match "pythonic". Resumes matching none of the keywords are
excluded.

If the FTS index is unusable (keywords the tokenizer rejects, e.g. "c++" or
"++") or stale (empty shortlist), the search falls back to scanning every
resume that has stored text.
"""

import json
import re
import sqlite3

import db

_RECORD_COLUMNS = "id, name, email, file_name, skills, total_experience, resume_text"
_ID_CHUNK_SIZE = 500


def normalize_keywords(keywords: list[str]) -> list[str]:
    """Lowercase, strip, dedupe (order-preserving), and drop empty keywords."""
    normalized: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        cleaned = keyword.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            normalized.append(cleaned)
    return normalized


def _fts_match_query(keywords: list[str]) -> str:
    """Build an FTS5 MATCH query: each keyword becomes a quoted phrase."""
    quoted = ['"%s"' % keyword.replace('"', '""') for keyword in keywords]
    return " OR ".join(quoted)


def _fts_shortlist(conn: sqlite3.Connection, keywords: list[str]) -> list[int] | None:
    """Return resume ids matching any keyword via FTS, or None to signal fallback."""
    try:
        rows = conn.execute(
            "SELECT rowid FROM resumes_fts WHERE resumes_fts MATCH ?",
            (_fts_match_query(keywords),),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    return [row["rowid"] for row in rows]


def _scan_shortlist(conn: sqlite3.Connection) -> list[int]:
    """Return ids of every resume that has stored text (fallback shortlist)."""
    rows = conn.execute(
        "SELECT id FROM resumes WHERE resume_text IS NOT NULL ORDER BY id"
    ).fetchall()
    return [row["id"] for row in rows]


def _count_occurrences(text: str, keyword: str) -> int:
    pattern = re.compile(
        r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])", re.IGNORECASE
    )
    return len(pattern.findall(text))


def _fetch_records(conn: sqlite3.Connection, resume_ids: list[int]) -> list[dict]:
    records = []
    for start in range(0, len(resume_ids), _ID_CHUNK_SIZE):
        chunk = resume_ids[start : start + _ID_CHUNK_SIZE]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT {_RECORD_COLUMNS} FROM resumes "
            f"WHERE id IN ({placeholders}) AND resume_text IS NOT NULL",
            chunk,
        ).fetchall()
        for row in rows:
            record = dict(row)
            record["skills"] = json.loads(record["skills"])
            records.append(record)
    return records


def _rank(records: list[dict], keywords: list[str]) -> list[dict]:
    """Count keyword hits per record and sort by distinct matches, then total."""
    ranked: list[dict] = []
    for record in records:
        counts = {
            keyword: _count_occurrences(record["resume_text"], keyword)
            for keyword in keywords
        }
        matched = [
            {"keyword": keyword, "count": count}
            for keyword, count in counts.items()
            if count > 0
        ]
        if not matched:
            continue
        ranked.append(
            {
                "id": record["id"],
                "name": record["name"],
                "email": record["email"],
                "file_name": record["file_name"],
                "skills": record["skills"],
                "total_experience": record["total_experience"],
                "distinct_keywords": len(matched),
                "total_matches": sum(item["count"] for item in matched),
                "matched_keywords": matched,
            }
        )
    ranked.sort(
        key=lambda item: (
            -item["distinct_keywords"],
            -item["total_matches"],
            item["id"],
        )
    )
    return ranked


def search_resumes(
    keywords: list[str], db_path: str = db.DEFAULT_DB_PATH
) -> list[dict]:
    """Return resumes matching ``keywords``, best matches first.

    Raises ValueError if no usable keyword remains after normalization.
    """
    normalized = normalize_keywords(keywords)
    if not normalized:
        raise ValueError("no non-empty keywords provided")

    conn = db.get_connection(db_path)
    try:
        shortlist = _fts_shortlist(conn, normalized)
        if shortlist is None or not shortlist:
            shortlist = _scan_shortlist(conn)
        records = _fetch_records(conn, shortlist)
    finally:
        conn.close()
    return _rank(records, normalized)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Keyword search over stored resume text, best matches first."
    )
    parser.add_argument("keywords", nargs="+", help="One or more keywords")
    parser.add_argument(
        "--db",
        default=db.DEFAULT_DB_PATH,
        help=f"Path to the SQLite database file (default: {db.DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    for result in search_resumes(args.keywords, db_path=args.db):
        matched = ", ".join(
            f"{item['keyword']}({item['count']})" for item in result["matched_keywords"]
        )
        print(
            f"id {result['id']}: {result['name'] or '(no name)'} — "
            f"{result['distinct_keywords']} keyword(s), "
            f"{result['total_matches']} match(es) [{matched}]"
        )
