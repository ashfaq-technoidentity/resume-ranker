import pytest

import db
from keyword_search import normalize_keywords, search_resumes
from models import ParsedResume


def _make_db(tmp_path, specs):
    """Save one resume per (name, text) spec; returns the db path."""
    resumes = []
    for index, (name, text, skills) in enumerate(specs):
        resume_file = tmp_path / f"{index}.pdf"
        resume_file.write_bytes(f"%PDF fake {index}".encode())
        resumes.append(
            ParsedResume(
                file_path=str(resume_file),
                name=name,
                skills=skills or [],
                resume_text=text,
            )
        )
    db_path = str(tmp_path / "resumes.db")
    conn = db.get_connection(db_path)
    try:
        db.save_resumes(conn, resumes)
    finally:
        conn.close()
    return db_path


def test_normalize_keywords_strips_lowercases_and_dedupes():
    assert normalize_keywords(["  Python ", "Docker", "python", ""]) == [
        "python",
        "docker",
    ]


def test_normalize_keywords_empty_input():
    assert normalize_keywords(["", "   "]) == []


def test_search_ranks_by_distinct_keywords_then_occurrences(tmp_path):
    db_path = _make_db(
        tmp_path,
        [
            ("Alice", "python python", []),
            ("Bob", "python docker java", []),
            ("Carol", "docker java java", []),
            ("Dana", "python docker java java java", []),
            ("Eve", "cobol fortran", []),
        ],
    )

    results = search_resumes(["python", "docker", "java"], db_path=db_path)

    assert [result["name"] for result in results] == ["Dana", "Bob", "Carol", "Alice"]
    assert results[0]["distinct_keywords"] == 3
    assert results[0]["total_matches"] == 5
    assert results[1]["total_matches"] == 3
    assert results[3]["distinct_keywords"] == 1
    assert results[3]["total_matches"] == 2


def test_search_excludes_resumes_without_matches(tmp_path):
    db_path = _make_db(tmp_path, [("Alice", "python dev", []), ("Eve", "cobol", [])])

    results = search_resumes(["python"], db_path=db_path)

    assert [result["name"] for result in results] == ["Alice"]


def test_search_is_case_insensitive(tmp_path):
    db_path = _make_db(tmp_path, [("Alice", "PYTHON Docker", [])])

    results = search_resumes(["python"], db_path=db_path)
    assert results[0]["matched_keywords"] == [{"keyword": "python", "count": 1}]

    results = search_resumes(["DOCKER"], db_path=db_path)
    assert results[0]["matched_keywords"] == [{"keyword": "docker", "count": 1}]


def test_search_respects_word_boundaries(tmp_path):
    db_path = _make_db(tmp_path, [("Alice", "pythonic dockerize", [])])

    assert search_resumes(["python", "docker"], db_path=db_path) == []


def test_search_supports_multi_word_keywords(tmp_path):
    db_path = _make_db(
        tmp_path,
        [
            ("Alice", "deep machine learning systems", []),
            ("Bob", "machine maintenance and learning", []),
        ],
    )

    results = search_resumes(["machine learning"], db_path=db_path)

    assert [result["name"] for result in results] == ["Alice"]
    assert results[0]["matched_keywords"] == [
        {"keyword": "machine learning", "count": 1}
    ]


def test_search_handles_punctuation_keywords(tmp_path):
    db_path = _make_db(tmp_path, [("Alice", "c++ and python", []), ("Bob", "java", [])])

    results = search_resumes(["c++"], db_path=db_path)

    assert [result["name"] for result in results] == ["Alice"]
    assert results[0]["matched_keywords"] == [{"keyword": "c++", "count": 1}]


def test_search_returns_record_fields(tmp_path):
    db_path = _make_db(tmp_path, [("Alice", "python", ["Python", "Docker"])])

    results = search_resumes(["python"], db_path=db_path)

    assert results[0]["skills"] == ["Python", "Docker"]
    assert results[0]["email"] is None
    assert results[0]["file_name"] == "0.pdf"


def test_search_falls_back_when_fts_index_is_stale(tmp_path):
    db_path = _make_db(tmp_path, [("Alice", "python", []), ("Bob", "java", [])])
    conn = db.get_connection(db_path)
    try:
        conn.execute("DELETE FROM resumes_fts")
        conn.commit()
    finally:
        conn.close()

    results = search_resumes(["python"], db_path=db_path)

    assert [result["name"] for result in results] == ["Alice"]


def test_search_raises_on_no_usable_keywords(tmp_path):
    db_path = _make_db(tmp_path, [("Alice", "python", [])])

    with pytest.raises(ValueError, match="no non-empty keywords"):
        search_resumes(["   "], db_path=db_path)
