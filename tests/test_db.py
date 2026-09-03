import hashlib
from pathlib import Path

from db import (
    get_all_resumes,
    get_connection,
    get_resume,
    get_resume_file,
    save_resume,
    save_resumes,
)
from models import ParsedResume
from parse import _to_parsed_resume, parse_resume

SAMPLES_DIR = Path(__file__).parent.parent / "sample_resumes"
GOOD_RESUME = SAMPLES_DIR / "omkar_pathak.docx"


def _write_resume_file(tmp_path, name="resume.pdf", content=b"%PDF-1.4 fake resume"):
    file_path = tmp_path / name
    file_path.write_bytes(content)
    return file_path, content


def _make_resume(file_path, **overrides):
    fields = dict(
        file_path=str(file_path),
        name="Jane Doe",
        email="jane@example.com",
        mobile_number="+1 555 0100",
        skills=["Python", "SQL"],
        degree=["B.Tech"],
        designation=["Software Engineer"],
        company_names=["Acme Corp"],
        college_name=["MIT"],
        total_experience=3.5,
        no_of_pages=1,
        raw={"name": "Jane Doe", "skills": ["Python", "SQL"]},
    )
    fields.update(overrides)
    return ParsedResume(**fields)


def test_save_and_fetch_roundtrip(tmp_path):
    file_path, content = _write_resume_file(tmp_path)

    conn = get_connection(str(tmp_path / "resumes.db"))
    try:
        resume_id = save_resume(conn, _make_resume(file_path))
        records = get_all_resumes(conn)
    finally:
        conn.close()

    assert len(records) == 1
    record = records[0]
    assert record["id"] == resume_id
    assert record["file_path"] == str(file_path)
    assert record["file_name"] == "resume.pdf"
    assert record["file_ext"] == "pdf"
    assert record["file_size"] == len(content)
    assert record["file_hash"] == hashlib.sha256(content).hexdigest()
    assert "file_blob" not in record
    assert record["name"] == "Jane Doe"
    assert record["email"] == "jane@example.com"
    assert record["mobile_number"] == "+1 555 0100"
    assert record["skills"] == ["Python", "SQL"]
    assert record["degree"] == ["B.Tech"]
    assert record["designation"] == ["Software Engineer"]
    assert record["company_names"] == ["Acme Corp"]
    assert record["college_name"] == ["MIT"]
    assert record["total_experience"] == 3.5
    assert record["no_of_pages"] == 1
    assert record["raw"] == {"name": "Jane Doe", "skills": ["Python", "SQL"]}
    assert record["error"] is None
    assert record["created_at"] is not None


def test_get_resume_file(tmp_path):
    file_path, content = _write_resume_file(tmp_path)

    conn = get_connection(str(tmp_path / "resumes.db"))
    try:
        resume_id = save_resume(conn, _make_resume(file_path))
        assert get_resume_file(conn, resume_id) == content
        assert get_resume_file(conn, resume_id + 100) is None
    finally:
        conn.close()


def test_get_resume(tmp_path):
    file_path, _ = _write_resume_file(tmp_path)

    conn = get_connection(str(tmp_path / "resumes.db"))
    try:
        resume_id = save_resume(conn, _make_resume(file_path))
        record = get_resume(conn, resume_id)
        missing = get_resume(conn, resume_id + 100)
    finally:
        conn.close()

    assert record is not None
    assert record["id"] == resume_id
    assert record["name"] == "Jane Doe"
    assert record["skills"] == ["Python", "SQL"]
    assert "file_blob" not in record
    assert missing is None


def test_upsert_same_file_updates_row(tmp_path):
    file_path, _ = _write_resume_file(tmp_path)

    conn = get_connection(str(tmp_path / "resumes.db"))
    try:
        first_id = save_resume(conn, _make_resume(file_path))
        save_resume(conn, _make_resume(file_path, name="Jane Updated"))
        records = get_all_resumes(conn)
    finally:
        conn.close()

    assert len(records) == 1
    assert records[0]["id"] == first_id
    assert records[0]["name"] == "Jane Updated"


def test_distinct_files_stored_separately(tmp_path):
    file_a, _ = _write_resume_file(tmp_path, name="a.pdf", content=b"resume a")
    file_b, _ = _write_resume_file(tmp_path, name="b.pdf", content=b"resume b")

    conn = get_connection(str(tmp_path / "resumes.db"))
    try:
        ids = save_resumes(conn, [_make_resume(file_a), _make_resume(file_b)])
        records = get_all_resumes(conn)
    finally:
        conn.close()

    assert len(records) == 2
    assert [record["id"] for record in records] == ids


def test_error_record_without_file(tmp_path):
    resume = ParsedResume(file_path=str(tmp_path / "missing.pdf"), error="boom")

    conn = get_connection(str(tmp_path / "resumes.db"))
    try:
        resume_id = save_resume(conn, resume)
        records = get_all_resumes(conn)
    finally:
        conn.close()

    assert len(records) == 1
    record = records[0]
    assert record["id"] == resume_id
    assert record["error"] == "boom"
    assert record["file_hash"] is None
    assert record["file_size"] is None
    assert record["skills"] == []
    assert record["raw"] == {}


def test_store_parsed_sample_resume(tmp_path):
    resume = _to_parsed_resume(parse_resume(str(GOOD_RESUME)))

    conn = get_connection(str(tmp_path / "resumes.db"))
    try:
        resume_id = save_resume(conn, resume)
        record = get_all_resumes(conn)[0]
        stored_file = get_resume_file(conn, resume_id)
    finally:
        conn.close()

    assert record["error"] is None
    assert "Omkar Pathak" in record["name"]
    assert record["email"] == "omkarpathak27@gmail.com"
    assert record["file_name"] == "omkar_pathak.docx"
    assert record["file_size"] == GOOD_RESUME.stat().st_size
    assert stored_file == GOOD_RESUME.read_bytes()
