from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import db
import embedding_provider
import jobs_db
import main
import parse
from models import JobDescription, ParsedResume


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


def test_store_job_persists_skills_and_responsibilities(client):
    payload = {
        "job_id": "J-6",
        "description": "Backend engineer",
        "job_skills": ["python", "fastapi"],
        "job_responsibilities": ["build apis", "review code"],
    }
    response = client.post("/jobs", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["job_skills"] == ["python", "fastapi"]
    assert body["job_responsibilities"] == ["build apis", "review code"]

    stored = client.get("/jobs/J-6").json()
    assert stored["job_skills"] == ["python", "fastapi"]
    assert stored["job_responsibilities"] == ["build apis", "review code"]


def test_store_job_defaults_new_lists_to_empty(client):
    response = client.post("/jobs", json={"job_id": "J-7", "description": "x"})

    assert response.status_code == 201
    body = response.json()
    assert body["job_skills"] == []
    assert body["job_responsibilities"] == []


def test_store_job_upsert_replaces_skills_and_responsibilities(client):
    client.post(
        "/jobs",
        json={
            "job_id": "J-8",
            "description": "v1",
            "job_skills": ["python"],
            "job_responsibilities": ["write code"],
        },
    )
    response = client.post(
        "/jobs",
        json={
            "job_id": "J-8",
            "description": "v2",
            "job_skills": ["rust"],
            "job_responsibilities": ["design systems"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["job_skills"] == ["rust"]
    assert body["job_responsibilities"] == ["design systems"]


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


def test_update_job_changes_only_provided_fields(client):
    created = client.post(
        "/jobs",
        json={
            "job_id": "J-9",
            "description": "v1",
            "posted_date": "2026-08-01",
            "job_skills": ["python"],
            "job_responsibilities": ["write code"],
        },
    ).json()
    response = client.put("/jobs/J-9", json={"job_skills": ["go", "docker"]})

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "v1"
    assert body["posted_date"] == "2026-08-01"
    assert body["job_responsibilities"] == ["write code"]
    assert body["job_skills"] == ["go", "docker"]
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] >= created["updated_at"]


def test_update_job_can_clear_lists(client):
    client.post(
        "/jobs",
        json={"job_id": "J-10", "description": "x", "job_skills": ["python"]},
    )
    response = client.put("/jobs/J-10", json={"job_skills": []})

    assert response.status_code == 200
    assert response.json()["job_skills"] == []
    assert client.get("/jobs/J-10").json()["job_skills"] == []


def test_update_job_not_found(client):
    response = client.put("/jobs/does-not-exist", json={"description": "x"})

    assert response.status_code == 404


def test_update_job_requires_at_least_one_field(client):
    client.post("/jobs", json={"job_id": "J-11", "description": "x"})
    empty_body = client.put("/jobs/J-11", json={})
    null_fields = client.put("/jobs/J-11", json={"job_skills": None})

    assert empty_body.status_code == 422
    assert null_fields.status_code == 422


def test_update_job_validation_errors(client):
    client.post("/jobs", json={"job_id": "J-12", "description": "x"})
    empty_description = client.put("/jobs/J-12", json={"description": ""})
    bad_date = client.put("/jobs/J-12", json={"posted_date": "not-a-date"})

    assert empty_description.status_code == 422
    assert bad_date.status_code == 422


def test_delete_job_removes_record(client):
    client.post(
        "/jobs",
        json={"job_id": "J-13", "description": "x", "job_skills": ["python"]},
    )
    response = client.delete("/jobs/J-13")

    assert response.status_code == 204
    assert client.get("/jobs/J-13").status_code == 404
    assert client.get("/jobs").json() == []


def test_delete_job_not_found(client):
    response = client.delete("/jobs/does-not-exist")

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


class StubEmbeddingProvider:
    model = "stub-model"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.seen_inputs: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.seen_inputs.append(list(texts))
        return [self.vectors[text] for text in texts]


def _fake_parsed_resume(file_path: str) -> ParsedResume:
    return ParsedResume(
        file_path=file_path,
        name="Jane Doe",
        email="jane@example.com",
        skills=["Python", "Docker"],
        total_experience=3.0,
        resume_text="Jane Doe knows Python and Docker",
        raw={"experience": ["Built things at TechnoIdentity"]},
    )


def _install_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr(embedding_provider, "get_embedding_provider", lambda: provider)


@pytest.fixture()
def rank_env(client, tmp_path, monkeypatch):
    """Ready-to-rank client: fresh resumes db, stubbed parser, no embeddings yet."""
    db_path = tmp_path / "resumes.db"
    monkeypatch.setenv("RESUMES_DB_PATH", str(db_path))
    monkeypatch.setattr(parse, "parse_file", _fake_parsed_resume)
    return client, str(db_path)


def _rank(client, *, name="jane_doe.pdf", content=b"%PDF-1.4 fake resume", data=None):
    return client.post(
        "/resumes/rank",
        files={"resume_file": (name, content, "application/pdf")},
        data=data or {},
    )


def test_rank_resume_returns_similarity_scores(rank_env, monkeypatch):
    client, _ = rank_env
    provider = StubEmbeddingProvider(
        {
            "Python, Docker": [1.0, 0.0],
            "python\ndocker": [1.0, 0.0],
            "Built things at TechnoIdentity": [0.0, 1.0],
            "build apis": [0.0, 1.0],
        }
    )
    _install_provider(monkeypatch, provider)

    response = _rank(
        client,
        data={
            "job_skills": ["python", "docker"],
            "job_responsibilities": ["build apis"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resume_id"] == 1
    assert body["file_name"] == "jane_doe.pdf"
    assert body["file_hash"] is not None
    assert body["name"] == "Jane Doe"
    assert body["email"] == "jane@example.com"
    assert body["skills"] == ["Python", "Docker"]
    assert body["total_experience"] == 3.0
    assert body["model"] == "stub-model"
    assert body["candidate_skills"] == "Python, Docker"
    assert body["candidate_experience"] == "Built things at TechnoIdentity"
    assert body["skills_similarity"] == pytest.approx(1.0)
    assert body["experience_similarity"] == pytest.approx(1.0)
    assert body["average_similarity"] == pytest.approx(1.0)
    # all four chunks go to the embedding provider in a single batched call
    assert provider.seen_inputs == [
        [
            "Python, Docker",
            "python\ndocker",
            "Built things at TechnoIdentity",
            "build apis",
        ]
    ]


def test_rank_resume_scores_partial_overlap(rank_env, monkeypatch):
    client, _ = rank_env
    _install_provider(
        monkeypatch,
        StubEmbeddingProvider(
            {
                "Python, Docker": [1.0, 0.0],
                "cobol": [0.0, 1.0],
                "Built things at TechnoIdentity": [1.0, 0.0],
                "maintain mainframes": [0.0, 1.0],
            }
        ),
    )

    response = _rank(
        client,
        data={"job_skills": ["cobol"], "job_responsibilities": ["maintain mainframes"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["skills_similarity"] == pytest.approx(0.0)
    assert body["experience_similarity"] == pytest.approx(0.0)
    assert body["average_similarity"] == pytest.approx(0.0)


def test_rank_resume_stores_text_details_and_file(rank_env, monkeypatch):
    client, db_path = rank_env
    content = b"%PDF-1.4 fake resume bytes"
    _install_provider(
        monkeypatch,
        StubEmbeddingProvider(
            {
                "Python, Docker": [1.0, 0.0],
                "python": [1.0, 0.0],
                "Built things at TechnoIdentity": [0.0, 1.0],
                "build apis": [0.0, 1.0],
            }
        ),
    )

    response = _rank(
        client,
        name="jane.pdf",
        content=content,
        data={"job_skills": ["python"], "job_responsibilities": ["build apis"]},
    )
    resume_id = response.json()["resume_id"]

    conn = db.get_connection(db_path)
    try:
        record = db.get_resume(conn, resume_id)
        assert record["name"] == "Jane Doe"
        assert record["email"] == "jane@example.com"
        assert record["skills"] == ["Python", "Docker"]
        assert record["total_experience"] == 3.0
        assert record["resume_text"] == "Jane Doe knows Python and Docker"
        assert db.get_resume_file(conn, resume_id) == content
    finally:
        conn.close()


def test_rank_resume_reupload_same_content_updates_one_row(rank_env, monkeypatch):
    client, db_path = rank_env
    _install_provider(
        monkeypatch,
        StubEmbeddingProvider({"Python, Docker": [1.0, 0.0], "python": [1.0, 0.0]}),
    )

    first = _rank(
        client, name="v1.pdf", content=b"%PDF same", data={"job_skills": ["python"]}
    ).json()
    second = _rank(
        client, name="v2.pdf", content=b"%PDF same", data={"job_skills": ["python"]}
    ).json()

    assert second["resume_id"] == first["resume_id"]
    assert second["file_name"] == "v2.pdf"

    conn = db.get_connection(db_path)
    try:
        records = db.get_all_resumes(conn)
        assert len(records) == 1
    finally:
        conn.close()


def test_rank_resume_missing_file_part_unprocessable(rank_env):
    client, _ = rank_env

    response = client.post("/resumes/rank", data={"job_skills": ["python"]})

    assert response.status_code == 422


def test_rank_resume_unsupported_file_type(client, tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMES_DB_PATH", str(tmp_path / "resumes.db"))

    response = _rank(client, name="resume.txt", content=b"plain text")

    assert response.status_code == 415
    assert "only PDF and DOCX" in response.json()["detail"]


def test_rank_resume_empty_file_unprocessable(rank_env):
    client, _ = rank_env

    response = _rank(client, content=b"", data={"job_skills": ["python"]})

    assert response.status_code == 422
    assert "is empty" in response.json()["detail"]


def test_rank_resume_blank_job_fields_unprocessable(rank_env):
    client, _ = rank_env

    blank_entries = _rank(
        client, data={"job_skills": ["   "], "job_responsibilities": [""]}
    )
    missing_fields = _rank(client)

    assert blank_entries.status_code == 422
    assert "At least one non-empty" in blank_entries.json()["detail"]
    assert missing_fields.status_code == 422


def test_rank_resume_parse_failure_stores_record_and_reports(
    client, tmp_path, monkeypatch
):
    db_path = tmp_path / "resumes.db"
    monkeypatch.setenv("RESUMES_DB_PATH", str(db_path))
    monkeypatch.setattr(
        parse,
        "parse_file",
        lambda file_path: ParsedResume(file_path=file_path, error="boom: corrupt docx"),
    )
    _install_provider(monkeypatch, StubEmbeddingProvider({}))

    response = _rank(
        client,
        name="broken.pdf",
        content=b"%PDF corrupt",
        data={"job_skills": ["python"]},
    )

    assert response.status_code == 422
    assert "Resume parsing failed: boom: corrupt docx" == response.json()["detail"]

    conn = db.get_connection(str(db_path))
    try:
        records = db.get_all_resumes(conn)
        assert len(records) == 1
        assert records[0]["error"] == "boom: corrupt docx"
        assert db.get_resume_file(conn, records[0]["id"]) == b"%PDF corrupt"
    finally:
        conn.close()


def test_rank_resume_provider_not_configured(rank_env, monkeypatch):
    client, _ = rank_env

    def unconfigured():
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to .env or export it."
        )

    monkeypatch.setattr(embedding_provider, "get_embedding_provider", unconfigured)

    response = _rank(client, data={"job_skills": ["python"]})

    assert response.status_code == 503
    assert "Embedding provider is not configured" in response.json()["detail"]


def test_rank_resume_embedding_failure_bad_gateway(rank_env, monkeypatch):
    client, _ = rank_env

    class ExplodingProvider:
        model = "boom"

        def embed_texts(self, texts):
            raise RuntimeError("OpenRouter embeddings request failed (500)")

    _install_provider(monkeypatch, ExplodingProvider())

    response = _rank(client, data={"job_skills": ["python"]})

    assert response.status_code == 502
    assert "Similarity calculation failed" in response.json()["detail"]


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


def test_init_db_adds_new_columns_to_legacy_table(tmp_path):
    engine = jobs_db.get_engine(f"sqlite:///{tmp_path}/legacy.db")
    legacy_schema = """
        CREATE TABLE job_descriptions (
            job_id VARCHAR(255) PRIMARY KEY,
            description TEXT NOT NULL,
            posted_date DATE NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """
    with engine.begin() as conn:
        conn.execute(text(legacy_schema))
        conn.execute(
            text(
                "INSERT INTO job_descriptions (job_id, description, posted_date)"
                " VALUES ('LEGACY', 'old job', '2026-01-01')"
            )
        )

    jobs_db.init_db(engine)

    legacy = jobs_db.get_job(engine, "LEGACY")
    assert legacy is not None
    assert legacy.job_skills == []
    assert legacy.job_responsibilities == []

    stored = jobs_db.upsert_job(
        engine,
        JobDescription(job_id="NEW", description="new job", job_skills=["sql"]),
    )
    assert stored.job_skills == ["sql"]
    engine.dispose()
