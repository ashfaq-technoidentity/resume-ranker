import json

import httpx
import pytest

import db
from embedding_provider import OpenRouterEmbeddingProvider, get_embedding_provider
from models import ParsedResume
from semantic_match import (
    build_candidate_chunks,
    cosine_similarity,
    semantic_similarity,
)


def test_cosine_similarity_identical_vectors():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_build_candidate_chunks():
    record = {
        "skills": ["Python", "Docker"],
        "raw": {"experience": ["TechnoIdentity", "AI/ML Engineer, Hyderabad"]},
    }

    skills, experience = build_candidate_chunks(record)

    assert skills == "Python, Docker"
    assert experience == "TechnoIdentity\nAI/ML Engineer, Hyderabad"


def test_build_candidate_chunks_falls_back_to_other_fields():
    record = {
        "skills": ["Python"],
        "designation": ["Software Engineer"],
        "company_names": ["DataWorks Inc"],
        "total_experience": 3.0,
        "raw": {},
    }

    skills, experience = build_candidate_chunks(record)

    assert skills == "Python"
    assert experience == (
        "Software Engineer\nDataWorks Inc\n3.0 years of total experience"
    )


def test_build_candidate_chunks_without_any_data():
    record = {
        "skills": [],
        "designation": [],
        "company_names": [],
        "total_experience": 0.0,
        "raw": {},
    }

    skills, experience = build_candidate_chunks(record)

    assert skills == ""
    assert experience == ""


def _openrouter_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openrouter_provider_returns_embeddings_in_input_order():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "openai/text-embedding-3-small"
        assert body["input"] == ["first", "second"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.4, 0.5], "index": 1},
                    {"embedding": [0.1, 0.2], "index": 0},
                ],
                "model": body["model"],
            },
        )

    provider = OpenRouterEmbeddingProvider(
        api_key="test-key",
        client=_openrouter_client(handler),
    )

    assert provider.embed_texts(["first", "second"]) == [[0.1, 0.2], [0.4, 0.5]]


def test_openrouter_provider_empty_input_skips_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    provider = OpenRouterEmbeddingProvider(
        api_key="test-key",
        client=_openrouter_client(handler),
    )

    assert provider.embed_texts([]) == []


def test_openrouter_provider_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid key"}})

    provider = OpenRouterEmbeddingProvider(
        api_key="test-key",
        client=_openrouter_client(handler),
    )

    with pytest.raises(RuntimeError, match="401.*Invalid key"):
        provider.embed_texts(["text"])


def test_openrouter_provider_rejects_empty_strings():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    provider = OpenRouterEmbeddingProvider(
        api_key="test-key",
        client=_openrouter_client(handler),
    )

    with pytest.raises(RuntimeError, match=r"empty string.*\[1\]"):
        provider.embed_texts(["valid text", ""])


def test_openrouter_provider_requires_api_key():
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterEmbeddingProvider(api_key="")


def test_get_embedding_provider_defaults_to_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)

    provider = get_embedding_provider()

    assert isinstance(provider, OpenRouterEmbeddingProvider)
    assert provider.model == "openai/text-embedding-3-small"


def test_get_embedding_provider_unknown_name(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "nonexistent")

    with pytest.raises(RuntimeError, match="Unknown embedding provider"):
        get_embedding_provider()


class StubProvider:
    model = "stub-model"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.seen_inputs: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.seen_inputs.append(texts)
        return [self.vectors[text] for text in texts]


def _store_resume(tmp_path, **overrides):
    """Save one resume into a fresh database; returns (resume_id, db_path)."""
    fields = {
        "file_path": str(tmp_path / "resume.pdf"),
        "name": "Jane Doe",
        "skills": ["Python"],
        "raw": {"experience": ["Built things"]},
    }
    fields.update(overrides)
    db_path = str(tmp_path / "resumes.db")
    conn = db.get_connection(db_path)
    try:
        resume_id = db.save_resumes(conn, [ParsedResume(**fields)])[0]
    finally:
        conn.close()
    return resume_id, db_path


def test_semantic_similarity_pairs_chunks_and_averages(tmp_path):
    resume_id, db_path = _store_resume(tmp_path)
    provider = StubProvider(
        {
            "Python": [1.0, 0.0],
            "Built things": [0.0, 1.0],
            "jd skills": [1.0, 0.0],
            "jd responsibilities": [0.0, 1.0],
        }
    )

    result = semantic_similarity(
        provider, resume_id, "jd skills", "jd responsibilities", db_path=db_path
    )

    assert result["skills_similarity"] == pytest.approx(1.0)
    assert result["experience_similarity"] == pytest.approx(1.0)
    assert result["average_similarity"] == pytest.approx(1.0)
    assert result["model"] == "stub-model"
    assert result["candidate_name"] == "Jane Doe"
    # all four chunks are embedded in a single batched call
    assert provider.seen_inputs == [
        ["Python", "jd skills", "Built things", "jd responsibilities"]
    ]


def test_semantic_similarity_mismatched_skills(tmp_path):
    resume_id, db_path = _store_resume(tmp_path)
    provider = StubProvider(
        {
            "Python": [1.0, 0.0],
            "Built things": [0.0, 1.0],
            "jd skills": [0.0, 1.0],
            "jd responsibilities": [0.0, 1.0],
        }
    )

    result = semantic_similarity(
        provider, resume_id, "jd skills", "jd responsibilities", db_path=db_path
    )

    assert result["skills_similarity"] == pytest.approx(0.0)
    assert result["experience_similarity"] == pytest.approx(1.0)
    assert result["average_similarity"] == pytest.approx(0.5)


def test_semantic_similarity_marks_empty_chunk_pair_as_zero(tmp_path):
    resume_id, db_path = _store_resume(tmp_path, raw={})
    provider = StubProvider({"Python": [1.0, 0.0], "jd skills": [1.0, 0.0]})

    result = semantic_similarity(
        provider, resume_id, "jd skills", "jd responsibilities", db_path=db_path
    )

    assert result["skills_similarity"] == pytest.approx(1.0)
    assert result["experience_similarity"] == 0.0
    assert result["average_similarity"] == pytest.approx(0.5)
    # only texts of comparable pairs are sent, in a single batched call
    assert provider.seen_inputs == [["Python", "jd skills"]]


def test_semantic_similarity_all_chunks_empty_scores_zero(tmp_path):
    resume_id, db_path = _store_resume(tmp_path, skills=[], raw={})
    provider = StubProvider({})

    result = semantic_similarity(
        provider, resume_id, "jd skills", "jd responsibilities", db_path=db_path
    )

    assert result["skills_similarity"] == 0.0
    assert result["experience_similarity"] == 0.0
    assert result["average_similarity"] == 0.0
    assert provider.seen_inputs == [[]]


def test_semantic_similarity_unknown_candidate_raises(tmp_path):
    _, db_path = _store_resume(tmp_path)
    provider = StubProvider({})

    with pytest.raises(RuntimeError, match="not found"):
        semantic_similarity(
            provider, 999, "jd skills", "jd responsibilities", db_path=db_path
        )
