from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import db
import embedding_provider
import file_preview
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
    for index, (name, resume_text) in enumerate(
        [("Alice", "Python and Docker"), ("Bob", "Java only")]
    ):
        resume_file = tmp_path / f"{index}.pdf"
        resume_file.write_bytes(f"%PDF fake {index}".encode())
        resumes.append(
            ParsedResume(file_path=str(resume_file), name=name, resume_text=resume_text)
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
    assert (
        response.json()["posted_date"] == datetime.now(timezone.utc).date().isoformat()
    )


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


def test_job_with_slash_in_id_is_addressable(client):
    client.post("/jobs", json={"job_id": "ai/ml-tcc", "description": "AI/ML role"})

    # uvicorn and the test client both unquote %2F to '/' before routing,
    # so both spellings must resolve to the same stored job
    encoded = client.get("/jobs/ai%2Fml-tcc")
    literal = client.get("/jobs/ai/ml-tcc")

    assert encoded.status_code == 200
    assert encoded.json()["job_id"] == "ai/ml-tcc"
    assert literal.status_code == 200
    assert literal.json()["job_id"] == "ai/ml-tcc"


def test_update_and_delete_job_with_slash_in_id(client):
    client.post("/jobs", json={"job_id": "ai/ml-tcc", "description": "v1"})
    updated = client.put("/jobs/ai%2Fml-tcc", json={"description": "v2"})
    fetched = client.get("/jobs/ai/ml-tcc")
    deleted = client.delete("/jobs/ai%2Fml-tcc")

    assert updated.status_code == 200
    assert updated.json()["description"] == "v2"
    assert fetched.json()["description"] == "v2"
    assert deleted.status_code == 204
    assert client.get("/jobs/ai/ml-tcc").status_code == 404


def test_job_scores_with_slash_in_job_id(client, resumes_db_path):
    conn = db.get_connection(resumes_db_path)
    try:
        db.save_job_scores(conn, 1, "ai/ml-tcc", 0.5, 0.5, 0.5, "m1")
        conn.commit()
    finally:
        conn.close()

    response = client.get("/jobs/ai%2Fml-tcc/scores")

    assert response.status_code == 200
    assert [item["resume_id"] for item in response.json()] == [1]


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
    """Ready-to-rank client: stored job, fresh resumes db, stubbed parser."""
    db_path = tmp_path / "resumes.db"
    monkeypatch.setenv("RESUMES_DB_PATH", str(db_path))
    monkeypatch.setattr(parse, "parse_file", _fake_parsed_resume)
    client.post(
        "/jobs",
        json={
            "job_id": "J-1",
            "description": "Platform engineer role",
            "job_skills": ["python", "docker"],
            "job_responsibilities": ["build apis"],
        },
    )
    return client, str(db_path)


def _rank(
    client,
    *,
    name="jane_doe.pdf",
    content=b"%PDF-1.4 fake resume",
    job_id="J-1",
):
    payload = {"job_id": job_id}
    return client.post(
        "/resumes/rank",
        files={"resume_file": (name, content, "application/pdf")},
        data={key: value for key, value in payload.items() if value is not None},
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

    response = _rank(client)

    assert response.status_code == 200
    body = response.json()
    assert body["resume_id"] == 1
    assert body["job_id"] == "J-1"
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
    # JD chunks come from the stored job; all four chunks go to the embedding
    # provider in a single batched call
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
    client.post(
        "/jobs",
        json={
            "job_id": "J-2",
            "description": "Legacy systems role",
            "job_skills": ["cobol"],
            "job_responsibilities": ["maintain mainframes"],
        },
    )
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

    response = _rank(client, job_id="J-2")

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
                "python\ndocker": [1.0, 0.0],
                "Built things at TechnoIdentity": [0.0, 1.0],
                "build apis": [0.0, 1.0],
            }
        ),
    )

    response = _rank(client, name="jane.pdf", content=content)
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
        StubEmbeddingProvider(
            {
                "Python, Docker": [1.0, 0.0],
                "python\ndocker": [1.0, 0.0],
                "Built things at TechnoIdentity": [0.0, 1.0],
                "build apis": [0.0, 1.0],
            }
        ),
    )

    first = _rank(client, name="v1.pdf", content=b"%PDF same").json()
    second = _rank(client, name="v2.pdf", content=b"%PDF same").json()

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

    response = client.post("/resumes/rank", data={"job_id": "J-1"})

    assert response.status_code == 422


def test_rank_resume_unsupported_file_type(client, tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMES_DB_PATH", str(tmp_path / "resumes.db"))

    response = _rank(client, name="resume.txt", content=b"plain text")

    assert response.status_code == 415
    assert "only PDF and DOCX" in response.json()["detail"]


def test_rank_resume_empty_file_unprocessable(rank_env):
    client, _ = rank_env

    response = _rank(client, content=b"")

    assert response.status_code == 422
    assert "is empty" in response.json()["detail"]


def test_rank_resume_job_without_criteria_unprocessable(rank_env, monkeypatch):
    client, _ = rank_env
    client.post(
        "/jobs",
        json={
            "job_id": "J-EMPTY",
            "description": "role with no structured criteria",
            "job_skills": [],
            "job_responsibilities": [],
        },
    )
    _install_provider(monkeypatch, StubEmbeddingProvider({}))

    response = _rank(client, job_id="J-EMPTY")

    assert response.status_code == 422
    assert "has no skills or responsibilities" in response.json()["detail"]


def test_rank_resume_parse_failure_stores_record_and_reports(
    client, tmp_path, monkeypatch
):
    db_path = tmp_path / "resumes.db"
    monkeypatch.setenv("RESUMES_DB_PATH", str(db_path))
    client.post(
        "/jobs",
        json={"job_id": "J-1", "description": "x", "job_skills": ["python"]},
    )
    monkeypatch.setattr(
        parse,
        "parse_file",
        lambda file_path: ParsedResume(file_path=file_path, error="boom: corrupt docx"),
    )
    _install_provider(monkeypatch, StubEmbeddingProvider({}))

    response = _rank(client, name="broken.pdf", content=b"%PDF corrupt")

    assert response.status_code == 422
    assert "Resume parsing failed: boom: corrupt docx" == response.json()["detail"]

    conn = db.get_connection(str(db_path))
    try:
        records = db.get_all_resumes(conn)
        assert len(records) == 1
        assert records[0]["error"] == "boom: corrupt docx"
        assert db.get_resume_file(conn, records[0]["id"]) == b"%PDF corrupt"
        # no scores are stored when parsing failed
        assert db.get_job_scores(conn, records[0]["id"], "J-1") is None
    finally:
        conn.close()


def test_rank_resume_provider_not_configured(rank_env, monkeypatch):
    client, _ = rank_env

    def unconfigured():
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to .env or export it."
        )

    monkeypatch.setattr(embedding_provider, "get_embedding_provider", unconfigured)

    response = _rank(client)

    assert response.status_code == 503
    assert "Embedding provider is not configured" in response.json()["detail"]


def test_rank_resume_embedding_failure_bad_gateway(rank_env, monkeypatch):
    client, _ = rank_env

    class ExplodingProvider:
        model = "boom"

        def embed_texts(self, texts):
            raise RuntimeError("OpenRouter embeddings request failed (500)")

    _install_provider(monkeypatch, ExplodingProvider())

    response = _rank(client)

    assert response.status_code == 502
    assert "Similarity calculation failed" in response.json()["detail"]


def test_batch_upload_resumes_without_job_stores_all(rank_env, monkeypatch):
    client, db_path = rank_env
    files = [
        ("resume_files", ("alice.pdf", b"%PDF alice resume", "application/pdf")),
        (
            "resume_files",
            (
                "bob.docx",
                b"%PDF bob resume",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
    ]
    response = client.post("/resumes/batch", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["succeeded"] == 2
    assert data["failed"] == 0
    assert len(data["items"]) == 2

    conn = db.get_connection(db_path)
    try:
        records = db.get_all_resumes(conn)
        assert len(records) == 2
    finally:
        conn.close()

    for item in data["items"]:
        assert item["status"] == "success"
        assert item["resume_id"] is not None
        assert item["job_id"] is None
        assert item["skills_similarity"] is None


def test_batch_upload_resumes_with_job_scores_all(rank_env, monkeypatch):
    client, db_path = rank_env
    provider = StubEmbeddingProvider(
        {
            "Python, Docker": [1.0, 0.0],
            "python\ndocker": [1.0, 0.0],
            "Built things at TechnoIdentity": [0.0, 1.0],
            "build apis": [0.0, 1.0],
        }
    )
    _install_provider(monkeypatch, provider)

    files = [
        ("resume_files", ("alice.pdf", b"%PDF alice resume", "application/pdf")),
        ("resume_files", ("bob.pdf", b"%PDF bob resume", "application/pdf")),
    ]
    response = client.post("/resumes/batch", files=files, data={"job_id": "J-1"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["succeeded"] == 2
    assert data["failed"] == 0

    for item in data["items"]:
        assert item["status"] == "success"
        assert item["job_id"] == "J-1"
        assert item["skills_similarity"] == pytest.approx(1.0)
        assert item["experience_similarity"] == pytest.approx(1.0)
        assert item["average_similarity"] == pytest.approx(1.0)

    conn = db.get_connection(db_path)
    try:
        for item in data["items"]:
            scores = db.get_job_scores(conn, item["resume_id"], "J-1")
            assert scores is not None
            assert scores["average_similarity"] == pytest.approx(1.0)
    finally:
        conn.close()


def test_batch_upload_resumes_partial_failures(rank_env, monkeypatch):
    client, _ = rank_env

    def parse_with_one_broken(file_path: str) -> ParsedResume:
        if "corrupt" in file_path:
            return ParsedResume(
                file_path=file_path,
                error="boom: corrupt docx",
                raw={},
            )
        return _fake_parsed_resume(file_path)

    monkeypatch.setattr(parse, "parse_file", parse_with_one_broken)

    files = [
        ("resume_files", ("valid.pdf", b"%PDF valid", "application/pdf")),
        ("resume_files", ("unsupported.txt", b"plain text", "text/plain")),
        ("resume_files", ("empty.pdf", b"", "application/pdf")),
        (
            "resume_files",
            (
                "corrupt.docx",
                b"%PDF corrupt",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
    ]
    response = client.post("/resumes/batch", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 4
    assert data["succeeded"] == 1
    assert data["failed"] == 3

    items = {item["file_name"]: item for item in data["items"]}
    assert items["valid.pdf"]["status"] == "success"
    assert items["valid.pdf"]["resume_id"] is not None

    assert items["unsupported.txt"]["status"] == "error"
    assert "Unsupported resume file" in items["unsupported.txt"]["error"]

    assert items["empty.pdf"]["status"] == "error"
    assert "empty" in items["empty.pdf"]["error"]

    assert items["corrupt.docx"]["status"] == "error"
    assert "boom: corrupt docx" in items["corrupt.docx"]["error"]


def test_batch_upload_empty_files_unprocessable(rank_env):
    client, _ = rank_env
    response = client.post("/resumes/batch")
    assert response.status_code == 422


def test_batch_upload_nonexistent_job_404(rank_env):
    client, _ = rank_env
    files = [("resume_files", ("valid.pdf", b"%PDF valid", "application/pdf"))]
    response = client.post(
        "/resumes/batch", files=files, data={"job_id": "J-DOES-NOT-EXIST"}
    )
    assert response.status_code == 404


def test_batch_insert_json(rank_env):
    client, db_path = rank_env
    payload = {
        "resumes": [
            {
                "file_path": "path1.pdf",
                "name": "Candidate One",
                "skills": ["Python", "FastAPI"],
                "resume_text": "Candidate One Python FastAPI",
            },
            {
                "file_path": "path2.pdf",
                "name": "Candidate Two",
                "skills": ["React", "TypeScript"],
                "resume_text": "Candidate Two React TypeScript",
            },
        ]
    }
    response = client.post("/resumes/batch-json", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["total"] == 2
    assert len(data["resume_ids"]) == 2

    conn = db.get_connection(db_path)
    try:
        r1 = db.get_resume(conn, data["resume_ids"][0])
        assert r1["name"] == "Candidate One"
        r2 = db.get_resume(conn, data["resume_ids"][1])
        assert r2["name"] == "Candidate Two"
    finally:
        conn.close()


def test_batch_insert_json_empty_unprocessable(rank_env):
    client, _ = rank_env
    response = client.post("/resumes/batch-json", json={"resumes": []})
    assert response.status_code == 422


def test_batch_upload_with_real_files(client, tmp_path, monkeypatch):
    db_path = tmp_path / "resumes.db"
    monkeypatch.setenv("RESUMES_DB_PATH", str(db_path))
    pdf_path = "sample_resumes/ashfaq-resume-Aug-2026_tailored_20260825_090723.pdf"
    docx_path = "sample_resumes/omkar_pathak.docx"
    with open(pdf_path, "rb") as f1, open(docx_path, "rb") as f2:
        files = [
            ("resume_files", ("ashfaq.pdf", f1.read(), "application/pdf")),
            (
                "resume_files",
                (
                    "omkar.docx",
                    f2.read(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            ),
        ]
    response = client.post("/resumes/batch", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["succeeded"] == 2
    assert data["failed"] == 0
    for item in data["items"]:
        assert item["status"] == "success"
        assert item["resume_id"] is not None
        assert len(item["skills"]) > 0


def test_rank_resume_stores_scores_in_resume_job_scores(rank_env, monkeypatch):
    client, db_path = rank_env
    _install_provider(
        monkeypatch,
        StubEmbeddingProvider(
            {
                "Python, Docker": [1.0, 0.0],
                "python\ndocker": [0.0, 1.0],
                "Built things at TechnoIdentity": [0.0, 1.0],
                "build apis": [1.0, 0.0],
            }
        ),
    )

    body = _rank(client).json()

    conn = db.get_connection(db_path)
    try:
        scores = db.get_job_scores(conn, body["resume_id"], "J-1")
    finally:
        conn.close()

    assert scores is not None
    assert scores["resume_id"] == body["resume_id"]
    assert scores["job_id"] == "J-1"
    assert scores["skills_similarity"] == pytest.approx(body["skills_similarity"])
    assert scores["experience_similarity"] == pytest.approx(
        body["experience_similarity"]
    )
    assert scores["average_similarity"] == pytest.approx(body["average_similarity"])
    assert scores["model"] == body["model"]
    assert scores["created_at"] is not None


def test_rank_resume_rerank_updates_stored_scores(rank_env, monkeypatch):
    client, db_path = rank_env
    _install_provider(
        monkeypatch,
        StubEmbeddingProvider(
            {
                "Python, Docker": [1.0, 0.0],
                "python\ndocker": [1.0, 0.0],
                "cobol": [0.0, 1.0],
                "Built things at TechnoIdentity": [0.0, 1.0],
                "build apis": [0.0, 1.0],
                "maintain mainframes": [1.0, 0.0],
            }
        ),
    )

    first = _rank(client).json()
    # the job's criteria change; the same resume+job pair is ranked again
    client.put(
        "/jobs/J-1",
        json={"job_skills": ["cobol"], "job_responsibilities": ["maintain mainframes"]},
    )
    second = _rank(client).json()

    conn = db.get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM resume_job_scores").fetchall()
        scores = db.get_job_scores(conn, second["resume_id"], "J-1")
    finally:
        conn.close()

    assert second["resume_id"] == first["resume_id"]
    assert first["skills_similarity"] == pytest.approx(1.0)
    assert second["skills_similarity"] == pytest.approx(0.0)
    assert len(rows) == 1  # same resume + job upserts, not a second row
    assert scores["skills_similarity"] == pytest.approx(second["skills_similarity"])
    assert scores["experience_similarity"] == pytest.approx(
        second["experience_similarity"]
    )
    assert scores["average_similarity"] == pytest.approx(second["average_similarity"])


def test_rank_resume_unknown_job_not_found(rank_env):
    client, _ = rank_env

    response = _rank(client, job_id="NOPE")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job 'NOPE' doesn't exist"


def test_rank_resume_missing_job_id_unprocessable(rank_env):
    client, _ = rank_env

    response = _rank(client, job_id=None)

    assert response.status_code == 422


def test_job_scores_lists_best_matches_first(client, resumes_db_path):
    conn = db.get_connection(resumes_db_path)
    try:
        db.save_job_scores(conn, 1, "J-1", 0.2, 0.2, 0.2, "m1")
        db.save_job_scores(conn, 2, "J-1", 0.9, 0.7, 0.8, "m2")
        db.save_job_scores(conn, 1, "J-2", 1.0, 1.0, 1.0, "m1")
        conn.commit()
    finally:
        conn.close()

    response = client.get("/jobs/J-1/scores")

    assert response.status_code == 200
    body = response.json()
    assert [item["resume_id"] for item in body] == [2, 1]
    top = body[0]
    assert top["job_id"] == "J-1"
    assert top["name"] == "Bob"
    assert top["email"] is None
    assert top["file_name"] == "1.pdf"
    assert top["skills"] == []
    assert top["total_experience"] is None
    assert top["skills_similarity"] == pytest.approx(0.9)
    assert top["experience_similarity"] == pytest.approx(0.7)
    assert top["average_similarity"] == pytest.approx(0.8)
    assert top["model"] == "m2"
    assert top["updated_at"]


def test_job_scores_unknown_job_returns_empty_list(client, resumes_db_path):
    response = client.get("/jobs/NOPE/scores")

    assert response.status_code == 200
    assert response.json() == []


def test_job_scores_missing_database_unavailable(client, tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMES_DB_PATH", str(tmp_path / "missing.db"))

    response = client.get("/jobs/J-1/scores")

    assert response.status_code == 503
    assert "not available" in response.json()["detail"]


def test_ranked_resume_appears_in_job_scores(rank_env, monkeypatch):
    client, _ = rank_env
    _install_provider(
        monkeypatch,
        StubEmbeddingProvider(
            {
                "Python, Docker": [1.0, 0.0],
                "python\ndocker": [1.0, 0.0],
                "Built things at TechnoIdentity": [0.0, 1.0],
                "build apis": [0.0, 1.0],
            }
        ),
    )
    ranked = _rank(client).json()

    response = client.get("/jobs/J-1/scores")

    assert response.status_code == 200
    scores = response.json()
    assert len(scores) == 1
    assert scores[0]["resume_id"] == ranked["resume_id"]
    assert scores[0]["name"] == "Jane Doe"
    assert scores[0]["file_name"] == "jane_doe.pdf"
    assert scores[0]["skills"] == ["Python", "Docker"]
    assert scores[0]["model"] == "stub-model"
    assert scores[0]["average_similarity"] == pytest.approx(
        ranked["average_similarity"]
    )


def _store_resume_row(resumes_db_path, tmp_path, file_name, content):
    """Save one more resume row directly; return (resume_id, record)."""
    resume_file = tmp_path / file_name
    resume_file.write_bytes(content)
    conn = db.get_connection(resumes_db_path)
    try:
        resume_id = db.save_resume(
            conn, ParsedResume(file_path=str(resume_file), resume_text="stored text")
        )
        conn.commit()
        record = db.get_resume(conn, resume_id)
    finally:
        conn.close()
    return resume_id, record


def test_resume_file_pdf_served_inline(client, resumes_db_path):
    response = client.get("/resumes/1/file")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == 'inline; filename="0.pdf"'
    assert response.content == b"%PDF fake 0"


def test_resume_file_docx_converted_to_pdf(
    client, resumes_db_path, tmp_path, monkeypatch
):
    monkeypatch.setenv("RESUME_PREVIEW_CACHE_DIR", str(tmp_path / "previews"))
    resume_id, _ = _store_resume_row(
        resumes_db_path, tmp_path, "carol.docx", b"PK fake docx"
    )
    monkeypatch.setattr(
        file_preview, "convert_docx_to_pdf", lambda blob, cache_path: b"%PDF converted"
    )

    response = client.get(f"/resumes/{resume_id}/file")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == 'inline; filename="carol.pdf"'
    assert response.content == b"%PDF converted"


def test_resume_file_docx_uses_cached_pdf(
    client, resumes_db_path, tmp_path, monkeypatch
):
    monkeypatch.setenv("RESUME_PREVIEW_CACHE_DIR", str(tmp_path / "previews"))
    resume_id, record = _store_resume_row(
        resumes_db_path, tmp_path, "cached.docx", b"PK cached docx"
    )
    cache_dir = tmp_path / "previews"
    cache_dir.mkdir()
    (cache_dir / f"{record['file_hash']}.pdf").write_bytes(b"%PDF cached")

    def must_not_convert(blob, cache_path):
        raise AssertionError("cached previews must not re-convert")

    monkeypatch.setattr(file_preview, "convert_docx_to_pdf", must_not_convert)

    response = client.get(f"/resumes/{resume_id}/file")

    assert response.status_code == 200
    assert response.content == b"%PDF cached"
    assert response.headers["content-disposition"] == 'inline; filename="cached.pdf"'


def test_resume_file_docx_conversion_failure_unavailable(
    client, resumes_db_path, tmp_path, monkeypatch
):
    monkeypatch.setenv("RESUME_PREVIEW_CACHE_DIR", str(tmp_path / "previews"))
    resume_id, _ = _store_resume_row(
        resumes_db_path, tmp_path, "broken.docx", b"PK broken docx"
    )

    def failing(blob, cache_path):
        raise RuntimeError("LibreOffice (soffice) is not installed")

    monkeypatch.setattr(file_preview, "convert_docx_to_pdf", failing)

    response = client.get(f"/resumes/{resume_id}/file")

    assert response.status_code == 503
    assert "Resume preview unavailable" in response.json()["detail"]
    assert "LibreOffice" in response.json()["detail"]


def test_resume_file_other_type_downloads_as_attachment(
    client, resumes_db_path, tmp_path
):
    resume_id, _ = _store_resume_row(
        resumes_db_path, tmp_path, "notes.txt", b"plain notes"
    )

    response = client.get(f"/resumes/{resume_id}/file")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert response.headers["content-disposition"] == 'attachment; filename="notes.txt"'
    assert response.content == b"plain notes"


def test_resume_file_unknown_resume_not_found(client, resumes_db_path):
    response = client.get("/resumes/999/file")

    assert response.status_code == 404


def test_resume_file_missing_database_unavailable(client, tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMES_DB_PATH", str(tmp_path / "missing.db"))

    response = client.get("/resumes/1/file")

    assert response.status_code == 503
    assert "not available" in response.json()["detail"]


def test_convert_docx_to_pdf_requires_libreoffice(tmp_path, monkeypatch):
    monkeypatch.setattr(file_preview.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="LibreOffice"):
        file_preview.convert_docx_to_pdf(b"PK docx", str(tmp_path / "cache.pdf"))


def test_cors_preflight_allowed_from_vite_dev_server(client):
    response = client.options(
        "/jobs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


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
