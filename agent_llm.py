"""Chat-completions client for the AI assistant's agent loop.

The agent brain runs through OpenRouter (same key as the embedding
provider) using the OpenAI-compatible chat-completions API with tool
calling. The active model is selected via ``AGENT_MODEL`` (default:
anthropic/claude-sonnet-4.5).
"""

import os

import httpx

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_AGENT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_MAX_TOKENS = 4096


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


class OpenRouterChatClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_AGENT_MODEL,
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
        self.max_tokens = _env_int("AGENT_MAX_TOKENS", DEFAULT_MAX_TOKENS)
        self._client = client or httpx.Client(timeout=120.0)

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """One agent turn: returns the raw assistant message dict.

        The message contains ``content`` (text, may be empty when the model
        only calls tools) and possibly ``tool_calls`` (a list of
        ``{id, type, function: {name, arguments}}`` dicts where ``arguments``
        is a JSON string).
        """
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                # explicit cap: OpenRouter sizes its credit check on
                # max_tokens (which would otherwise default to the model's
                # full output window)
                "max_tokens": self.max_tokens,
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenRouter chat request failed ({response.status_code}): "
                f"{response.text}"
            )
        choices = response.json().get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter chat response contained no choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("OpenRouter chat response contained no message")
        return message


def get_chat_client() -> OpenRouterChatClient:
    return OpenRouterChatClient(
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        model=os.environ.get("AGENT_MODEL", DEFAULT_AGENT_MODEL),
    )
