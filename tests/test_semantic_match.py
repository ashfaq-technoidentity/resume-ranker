import json

import httpx
import pytest

from embedding_provider import OpenRouterEmbeddingProvider, get_embedding_provider
from semantic_match import (
    SAMPLE_JD,
    build_candidate_chunks,
    cosine_similarity,
    semantic_similarity,
    split_jd,
)


def test_cosine_similarity_identical_vectors():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_split_jd_separates_sections():
    skills, responsibilities = split_jd(SAMPLE_JD)

    assert "Python programming" in skills
    assert "PostgreSQL" in skills
    assert "machine-learning models" in responsibilities
    assert "Optimize model performance" not in skills
    assert "TensorFlow" not in responsibilities


def test_build_candidate_chunks():
    record = {
        "skills": ["Python", "Docker"],
        "raw": {"experience": ["TechnoIdentity", "AI/ML Engineer, Hyderabad"]},
    }

    skills, experience = build_candidate_chunks(record)

    assert skills == "Python, Docker"
    assert experience == "TechnoIdentity\nAI/ML Engineer, Hyderabad"


def test_build_candidate_chunks_without_experience():
    record = {"skills": ["Python"], "raw": {}}

    skills, experience = build_candidate_chunks(record)

    assert skills == "Python"
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
        self.seen_inputs: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.seen_inputs.append(texts)
        return [self.vectors[text] for text in texts]


def test_semantic_similarity_pairs_chunks_and_averages():
    provider = StubProvider(
        {
            "candidate skills": [1.0, 0.0],
            "candidate experience": [0.0, 1.0],
            "jd skills": [1.0, 0.0],
            "jd responsibilities": [0.0, 1.0],
        }
    )

    result = semantic_similarity(
        provider,
        ("candidate skills", "candidate experience"),
        ("jd skills", "jd responsibilities"),
    )

    assert result["skills_similarity"] == pytest.approx(1.0)
    assert result["experience_similarity"] == pytest.approx(1.0)
    assert result["average_similarity"] == pytest.approx(1.0)
    assert result["model"] == "stub-model"
    # all four chunks are embedded in a single batched call
    assert provider.seen_inputs == [
        [
            "candidate skills",
            "candidate experience",
            "jd skills",
            "jd responsibilities",
        ]
    ]


def test_semantic_similarity_mismatched_skills():
    provider = StubProvider(
        {
            "candidate skills": [1.0, 0.0],
            "candidate experience": [0.0, 1.0],
            "jd skills": [0.0, 1.0],
            "jd responsibilities": [0.0, 1.0],
        }
    )

    result = semantic_similarity(
        provider,
        ("candidate skills", "candidate experience"),
        ("jd skills", "jd responsibilities"),
    )

    assert result["skills_similarity"] == pytest.approx(0.0)
    assert result["experience_similarity"] == pytest.approx(1.0)
    assert result["average_similarity"] == pytest.approx(0.5)
