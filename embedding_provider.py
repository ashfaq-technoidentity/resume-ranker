"""Embedding provider abstraction.

Text is turned into vectors through a provider so the backend can be swapped
(e.g. OpenRouter today, a local model tomorrow) without touching matching code.
The active provider is selected via ``EMBEDDING_PROVIDER`` (default: openrouter).
"""

import os
from typing import Protocol

import httpx

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_PROVIDER = "openrouter"
DEFAULT_MODEL = "openai/text-embedding-3-small"


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, in input order."""
        ...


class OpenRouterEmbeddingProvider:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = OPENROUTER_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add it to .env or export it."
            )
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=60.0)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "input": texts},
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenRouter embeddings request failed "
                f"({response.status_code}): {response.text}"
            )
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        embeddings = [item["embedding"] for item in data]
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"OpenRouter returned {len(embeddings)} embeddings "
                f"for {len(texts)} inputs"
            )
        return embeddings


def get_embedding_provider() -> EmbeddingProvider:
    provider_name = os.environ.get("EMBEDDING_PROVIDER", DEFAULT_PROVIDER).lower()
    if provider_name == "openrouter":
        return OpenRouterEmbeddingProvider(
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            model=os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL),
        )
    raise RuntimeError(f"Unknown embedding provider: {provider_name}")
