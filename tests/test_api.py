from datetime import date

import pytest
from fastapi.testclient import TestClient

import db
import jobs_db
import main
from models import ParsedResume


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture()
def resumes_db_path(tmp_path, monkeypatch):
    db_path = tmp_path / "resumes.db"
    resumes = []
    for index, (name, text) in enumerate(
        [("Alice", "Python and Docker"), ("Bob", "Java only")]
    ):
        resume_file = tmp_path / f"{index}.pdf"
        resume_file.write_bytes(f"%PDF fake {index}".encode())
        resumes.append(
            ParsedResume(file_path=str(resume_file), name=name, resume_text=text)
        )
    conn = db.get_connection(str(db_path))
    try:
        db.save_resumes(conn, resumes)
    finally:
        conn.close()
    monkeypatch.setenv("RESUMES_DB_PATH", str(db_path))
    return str(db_path)


def test_store_job_returns_stored_record(client):
    payload = {
        "job_id": "J-1",
        "description": "FastAPI backend engineer with PostgreSQL experience",
        "posted_date": "2026-08-01",
    }
    response = client.post("/jobs", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["job_id"] == "J-1"
    assert body["description"] == "FastAPI backend engineer with PostgreSQL experience"
    assert body["posted_date"] == "2026-08-01"
    assert body["created_at"] is not None
    assert body["updated_at"] is not None


def test_store_job_defaults_posted_date_to_today(client):
    response = client.post(
        "/jobs", json={"job_id": "J-2", "description": "Data engineer"}
    )

    assert response.status_code == 201
    assert response.json()["posted_date"] == date.today().isoformat()


def test_store_job_upserts_on_job_id(client):
    client.post(
        "/jobs",
        json={"job_id": "J-3", "description": "v1", "posted_date": "2026-08-01"},
    )
    response = client.post(
        "/jobs",
        json={"job_id": "J-3", "description": "v2", "posted_date": "2026-08-15"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["description"] == "v2"
    assert body["posted_date"] == "2026-08-15"

    jobs = client.get("/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["description"] == "v2"


def test_list_jobs_orders_by_most_recent_posted_date(client):
    client.post(
        "/jobs",
        json={"job_id": "OLD", "description": "old", "posted_date": "2026-01-01"},
    )
    client.post(
        "/jobs",
        json={"job_id": "NEW", "description": "new", "posted_date": "2026-08-01"},
    )

    jobs = client.get("/jobs").json()

    assert [job["job_id"] for job in jobs] == ["NEW", "OLD"]


def test_get_job_found(client):
    client.post("/jobs", json={"job_id": "J-4", "description": "Backend engineer"})
    response = client.get("/jobs/J-4")

    assert response.status_code == 200
    assert response.json()["job_id"] == "J-4"


def test_get_job_not_found(client):
    response = client.get("/jobs/does-not-exist")

    assert response.status_code == 404


def test_store_job_validation_errors(client):
    missing_description = client.post("/jobs", json={"job_id": "J-5"})
    empty_description = client.post("/jobs", json={"job_id": "J-5", "description": ""})
    empty_job_id = client.post("/jobs", json={"job_id": "", "description": "x"})
    bad_date = client.post(
        "/jobs",
        json={"job_id": "J-5", "description": "x", "posted_date": "not-a-date"},
    )

    assert missing_description.status_code == 422
    assert empty_description.status_code == 422
    assert empty_job_id.status_code == 422
    assert bad_date.status_code == 422


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "sqlite"}


def test_search_resumes_ranks_best_matches_first(client, resumes_db_path):
    response = client.post("/resumes/search", json={"keywords": ["python", "docker"]})

    assert response.status_code == 200
    body = response.json()
    assert [item["name"] for item in body] == ["Alice"]
    alice = body[0]
    assert alice["distinct_keywords"] == 2
    assert alice["total_matches"] == 2
    assert alice["matched_keywords"] == [
        {"keyword": "python", "count": 1},
        {"keyword": "docker", "count": 1},
    ]


def test_search_resumes_no_match_returns_empty_list(client, resumes_db_path):
    response = client.post("/resumes/search", json={"keywords": ["cobol"]})

    assert response.status_code == 200
    assert response.json() == []


def test_search_resumes_blank_keywords_unprocessable(client, resumes_db_path):
    response = client.post("/resumes/search", json={"keywords": ["   "]})

    assert response.status_code == 422


def test_search_resumes_empty_keyword_list_unprocessable(client):
    response = client.post("/resumes/search", json={"keywords": []})

    assert response.status_code == 422


def test_search_resumes_missing_database_unavailable(client, tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMES_DB_PATH", str(tmp_path / "missing.db"))

    response = client.post("/resumes/search", json={"keywords": ["python"]})

    assert response.status_code == 503
    assert "not available" in response.json()["detail"]


def test_get_engine_defaults_to_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    engine = jobs_db.get_engine()

    assert engine.url.drivername == "sqlite"
    assert engine.url.database == "resumes.db"
    engine.dispose()


def test_get_engine_normalizes_postgres_urls():
    for url in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"):
        engine = jobs_db.get_engine(url)

        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.database == "db"
        engine.dispose()
