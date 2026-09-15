import pytest

from agent_llm import OpenRouterChatClient


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.requests: list[tuple[str, dict]] = []

    def post(self, url: str, headers: dict | None = None, json: dict | None = None):
        self.requests.append((url, json or {}))
        return self.response


def test_client_requires_api_key():
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterChatClient(api_key="")


def test_chat_returns_assistant_message():
    message = {"role": "assistant", "content": "hi", "tool_calls": []}
    http = FakeHttpClient(FakeResponse(200, {"choices": [{"message": message}]}))
    client = OpenRouterChatClient(
        api_key="key", model="test/model", client=http  # noqa: ARG002
    )

    result = client.chat([{"role": "user", "content": "q"}], tools=[])

    assert result == message
    url, body = http.requests[0]
    assert url.endswith("/chat/completions")
    assert body["model"] == "test/model"
    assert body["messages"] == [{"role": "user", "content": "q"}]
    assert body["tool_choice"] == "auto"


def test_chat_http_error_raises_runtime_error():
    http = FakeHttpClient(FakeResponse(401, text="unauthorized"))
    client = OpenRouterChatClient(api_key="key", client=http)

    with pytest.raises(RuntimeError, match="401"):
        client.chat([{"role": "user", "content": "q"}], tools=[])


def test_chat_empty_choices_raises_runtime_error():
    http = FakeHttpClient(FakeResponse(200, {"choices": []}))
    client = OpenRouterChatClient(api_key="key", client=http)

    with pytest.raises(RuntimeError, match="no choices"):
        client.chat([{"role": "user", "content": "q"}], tools=[])
