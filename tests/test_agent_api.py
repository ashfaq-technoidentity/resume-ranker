import json

import pytest
from fastapi.testclient import TestClient

import agent
import agent_llm
import main
import sandbox as sandbox_module
from sandbox import SandboxManager

# ---- fakes ---------------------------------------------------------------


class FakeExecution:
    def __init__(self, output: str = "", exit_code: int = 0):
        self._output = output
        self._exit_code = exit_code
        self.exit_code = None

    def chunks(self):
        for line in self._output.splitlines(keepends=True):
            yield line
        self.exit_code = self._exit_code


class FakeManager:
    def __init__(self):
        self.executions: list[tuple] = []
        self.removed: list[str] = []
        self.resetted: list[str] = []
        self.next_output = ("ok\n", 0)
        self.files: list[dict] = []
        self.file_content: dict | None = None
        self.logs_text = "docker-log-line\n"

    def ensure_sandbox(self, session_id):
        return type("C", (), {"id": f"cid-{session_id}"})()

    def next_script_name(self, session_id):
        return "runs/001.py"

    def run_code(self, session_id, script_name, code):
        self.executions.append(("run_python", session_id, script_name, code))
        return FakeExecution(*self.next_output)

    def install_packages(self, session_id, packages):
        self.executions.append(("install_packages", session_id, packages))
        return FakeExecution(*self.next_output)

    def status(self, session_id):
        return {
            "container_id": f"cid-{session_id}",
            "name": f"resume-ranker-sandbox-{session_id}",
            "image": "resume-ranker-sandbox",
            "status": "running",
            "running": True,
            "started_at": "2026-01-01T00:00:00Z",
            "workspace_volume": f"resume-ranker-ws-{session_id}",
            "mem_usage": "12.3 MiB",
            "cpu_percent": 1.5,
        }

    def get_logs(self, session_id, tail=200):
        return self.logs_text

    def stream_logs(self, session_id, tail=100):
        yield self.logs_text

    def list_files(self, session_id, path="/workspace"):
        SandboxManager._safe_workspace_path(path)
        return self.files

    def read_file(self, session_id, path):
        SandboxManager._safe_workspace_path(path)
        return self.file_content

    def reset_sandbox(self, session_id):
        self.resetted.append(session_id)
        return self.ensure_sandbox(session_id)

    def remove_sandbox(self, session_id):
        self.removed.append(session_id)

    def sweep_orphans(self, known):
        return []

    def reap_idle(self):
        return []


class ScriptedChatClient:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def chat(self, messages, tools):
        # snapshot: the agent loop keeps mutating its message list
        self.calls.append(([dict(message) for message in messages], tools))
        if not self.turns:
            raise RuntimeError("no scripted turns left")
        return self.turns.pop(0)


TOOL_TURN = {
    "content": "Let me check the resumes.",
    "tool_calls": [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "run_python",
                "arguments": json.dumps({"code": "print('hi')"}),
            },
        }
    ],
}

FINAL_TURN = {"content": "Found [Alice](resume://1)", "tool_calls": None}


@pytest.fixture()
def fake_manager(monkeypatch):
    manager = FakeManager()
    monkeypatch.setattr(sandbox_module, "get_sandbox_manager", lambda: manager)
    return manager


@pytest.fixture()
def scripted_client(monkeypatch):
    client = ScriptedChatClient([])

    def install(turns):
        client.turns = list(turns)
        return client

    client.install = install
    monkeypatch.setattr(agent_llm, "get_chat_client", lambda: client)
    return client


@pytest.fixture()
def client(tmp_path, monkeypatch, fake_manager, scripted_client):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    with TestClient(main.app) as test_client:
        yield test_client


def _create_session(client) -> dict:
    response = client.post("/agent/sessions")
    assert response.status_code == 201
    return response.json()


def _stream_chat(client, session_id: str, content: str) -> list[dict]:
    events = []
    with client.stream(
        "POST", f"/agent/sessions/{session_id}/chat", json={"content": content}
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


# ---- sessions ------------------------------------------------------------


def test_create_session_returns_running_record(client, fake_manager):
    session = _create_session(client)

    assert session["sandbox_status"] == "running"
    assert session["title"] == "New chat"
    assert session["sandbox_container_id"].startswith("cid-")


def test_list_and_get_sessions(client):
    first = _create_session(client)
    second = _create_session(client)

    listed = client.get("/agent/sessions").json()
    assert {item["id"] for item in listed} == {first["id"], second["id"]}

    detail = client.get(f"/agent/sessions/{first['id']}").json()
    assert detail["session"]["id"] == first["id"]
    assert detail["messages"] == []
    assert detail["events"] == []


def test_get_session_unknown_404(client):
    assert client.get("/agent/sessions/missing").status_code == 404


def test_rename_session(client):
    session = _create_session(client)

    response = client.patch(
        f"/agent/sessions/{session['id']}", json={"title": "python people"}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "python people"


def test_delete_session_removes_rows_and_sandbox(client, fake_manager):
    session = _create_session(client)

    response = client.delete(f"/agent/sessions/{session['id']}")

    assert response.status_code == 204
    assert client.get(f"/agent/sessions/{session['id']}").status_code == 404
    assert fake_manager.removed == [session["id"]]


def test_delete_session_unknown_404(client):
    assert client.delete("/agent/sessions/missing").status_code == 404


def test_create_session_sandbox_unavailable_503(client, monkeypatch, fake_manager):
    def broken():
        raise RuntimeError("Cannot reach the Docker daemon: nope")

    monkeypatch.setattr(sandbox_module, "get_sandbox_manager", broken)

    response = client.post("/agent/sessions")

    assert response.status_code == 503
    assert "Docker daemon" in response.json()["detail"]


def test_endpoints_disabled_503(client, monkeypatch):
    monkeypatch.setenv("SANDBOX_ENABLED", "0")

    assert client.post("/agent/sessions").status_code == 503
    assert client.get("/agent/sessions").json() == []  # history still listable


# ---- chat -----------------------------------------------------------------


def test_chat_streams_full_agent_trace(client, fake_manager, scripted_client):
    scripted_client.install([TOOL_TURN, FINAL_TURN])
    session = _create_session(client)

    events = _stream_chat(client, session["id"], "who knows python?")

    types = [event["type"] for event in events]
    assert types == [
        "run_started",
        "thought",
        "action",
        "output",
        "observation",
        "answer",
        "run_done",
    ]
    answer = next(event for event in events if event["type"] == "answer")
    assert answer["data"]["content"] == "Found [Alice](resume://1)"
    done = events[-1]
    assert done["data"]["status"] == "completed"

    # the tool ran in the (fake) sandbox with the model's code
    assert fake_manager.executions == [
        ("run_python", session["id"], "runs/001.py", "print('hi')")
    ]

    # the LLM saw the system prompt (with the resumes cheat-sheet) and history
    messages, tools = scripted_client.calls[0]
    assert messages[0]["role"] == "system"
    assert "/data/resumes/resumes.db" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "who knows python?"}
    assert {tool["function"]["name"] for tool in tools} == {
        "run_python",
        "install_packages",
    }

    # everything persisted for replay
    detail = client.get(f"/agent/sessions/{session['id']}").json()
    roles = [message["role"] for message in detail["messages"]]
    assert roles == ["user", "assistant"]
    assert detail["messages"][1]["content"] == "Found [Alice](resume://1)"
    assert len(detail["events"]) == len(events)
    assert detail["session"]["title"] == "who knows python?"


def test_chat_install_packages_flow(client, fake_manager, scripted_client):
    scripted_client.install(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-9",
                        "type": "function",
                        "function": {
                            "name": "install_packages",
                            "arguments": json.dumps({"packages": ["pypdf"]}),
                        },
                    }
                ],
            },
            FINAL_TURN,
        ]
    )
    session = _create_session(client)

    events = _stream_chat(client, session["id"], "parse the pdfs")

    assert fake_manager.executions == [("install_packages", session["id"], ["pypdf"])]
    observation = next(event for event in events if event["type"] == "observation")
    assert observation["data"]["exit_code"] == 0


def test_chat_tool_error_becomes_observation(client, fake_manager, scripted_client):
    scripted_client.install(
        [
            TOOL_TURN,
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-2",
                        "type": "function",
                        "function": {
                            "name": "explode",
                            "arguments": "{}",
                        },
                    }
                ],
            },
            FINAL_TURN,
        ]
    )
    session = _create_session(client)

    events = _stream_chat(client, session["id"], "do things")

    observation = [e for e in events if e["type"] == "observation"][1]
    assert "unknown tool: explode" in observation["data"]["output"]
    assert observation["data"]["exit_code"] == 1
    assert events[-1]["data"]["status"] == "completed"


def test_chat_llm_failure_reports_error(client, fake_manager, scripted_client):
    def explode(messages, tools):
        raise RuntimeError("OpenRouter chat request failed (500): boom")

    class ExplodingClient:
        chat = explode

    scripted_client.turns = []
    import agent_llm as llm

    original = llm.get_chat_client
    llm.get_chat_client = lambda: ExplodingClient()
    try:
        session = _create_session(client)
        events = _stream_chat(client, session["id"], "hello?")
    finally:
        llm.get_chat_client = original

    assert events[-1]["data"]["status"] == "error"
    assert any(event["type"] == "error" for event in events)
    detail = client.get(f"/agent/sessions/{session['id']}").json()
    assert detail["messages"][-1]["role"] == "assistant"
    assert "run failed" in detail["messages"][-1]["content"]


def test_chat_max_steps_ends_with_error(
    client, fake_manager, scripted_client, monkeypatch
):
    monkeypatch.setenv("AGENT_MAX_STEPS", "2")
    scripted_client.install([TOOL_TURN, TOOL_TURN, FINAL_TURN])
    session = _create_session(client)

    events = _stream_chat(client, session["id"], "loop forever")

    assert events[-1]["data"]["status"] == "error"
    assert "limit" in next(e for e in events if e["type"] == "error")["data"]["message"]


def test_chat_unknown_session_404(client, scripted_client):
    response = client.post("/agent/sessions/missing/chat", json={"content": "hi"})
    assert response.status_code == 404


def test_chat_second_run_conflict_409(client, scripted_client):
    session = _create_session(client)
    agent.runs.try_start(session["id"])
    try:
        response = client.post(
            f"/agent/sessions/{session['id']}/chat", json={"content": "hi"}
        )
        assert response.status_code == 409
        assert "already active" in response.json()["detail"]
    finally:
        agent.runs.end(session["id"])


def test_chat_validation(client):
    session = _create_session(client)
    assert (
        client.post(
            f"/agent/sessions/{session['id']}/chat", json={"content": ""}
        ).status_code
        == 422
    )


# ---- sandbox observability ------------------------------------------------


def test_sandbox_status_endpoint(client):
    session = _create_session(client)

    response = client.get(f"/agent/sessions/{session['id']}/sandbox")

    assert response.status_code == 200
    assert response.json()["running"] is True
    assert response.json()["mem_usage"] == "12.3 MiB"


def test_sandbox_logs_endpoint(client, fake_manager):
    session = _create_session(client)

    response = client.get(f"/agent/sessions/{session['id']}/sandbox/logs")

    assert response.status_code == 200
    assert response.json() == {"logs": "docker-log-line\n"}


def test_sandbox_logs_stream_endpoint(client):
    session = _create_session(client)

    with client.stream(
        "GET", f"/agent/sessions/{session['id']}/sandbox/logs/stream"
    ) as response:
        assert response.status_code == 200
        lines = list(response.iter_lines())

    assert any(
        line.startswith("data: ") and "docker-log-line" in line for line in lines
    )


def test_sandbox_files_endpoints(client, fake_manager):
    session = _create_session(client)
    fake_manager.files = [
        {"name": "runs", "path": "/workspace/runs", "size": 0, "is_dir": True},
        {
            "name": "001.py",
            "path": "/workspace/runs/001.py",
            "size": 12,
            "is_dir": False,
        },
    ]
    fake_manager.file_content = {
        "path": "/workspace/runs/001.py",
        "size": 12,
        "truncated": False,
        "binary": False,
        "content": "print('hi')",
    }

    listing = client.get(f"/agent/sessions/{session['id']}/sandbox/files")
    assert listing.status_code == 200
    assert listing.json()[0]["name"] == "runs"

    content = client.get(
        f"/agent/sessions/{session['id']}/sandbox/files/content",
        params={"path": "/workspace/runs/001.py"},
    )
    assert content.status_code == 200
    assert content.json()["content"] == "print('hi')"


def test_sandbox_files_traversal_rejected(client):
    session = _create_session(client)

    response = client.get(
        f"/agent/sessions/{session['id']}/sandbox/files/content",
        params={"path": "/workspace/../../etc/passwd"},
    )

    assert response.status_code == 400


def test_sandbox_file_missing_404(client, fake_manager):
    session = _create_session(client)
    fake_manager.file_content = None

    response = client.get(
        f"/agent/sessions/{session['id']}/sandbox/files/content",
        params={"path": "/workspace/nope.txt"},
    )

    assert response.status_code == 404


def test_sandbox_reset_endpoint(client, fake_manager):
    session = _create_session(client)

    response = client.post(f"/agent/sessions/{session['id']}/sandbox/reset")

    assert response.status_code == 200
    assert fake_manager.resetted == [session["id"]]
    events = client.get(f"/agent/sessions/{session['id']}").json()["events"]
    assert {"status": "reset"} in [event["data"] for event in events]


def test_sandbox_endpoints_unknown_session_404(client):
    assert client.get("/agent/sessions/missing/sandbox").status_code == 404
    assert client.get("/agent/sessions/missing/sandbox/logs").status_code == 404
