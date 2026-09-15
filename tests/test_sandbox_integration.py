"""Real-Docker integration tests for the sandbox.

Skipped unless the sandbox image exists and SANDBOX_INTEGRATION=1 is set:

    docker build --target sandbox -t resume-ranker-sandbox .
    SANDBOX_INTEGRATION=1 python -m pytest tests/test_sandbox_integration.py -v
"""

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SANDBOX_INTEGRATION") != "1",
    reason="set SANDBOX_INTEGRATION=1 to run docker integration tests",
)


@pytest.fixture()
def manager():
    from sandbox import get_sandbox_manager

    return get_sandbox_manager()


@pytest.fixture()
def session_id(manager):
    session_id = "it-" + uuid.uuid4().hex[:12]
    manager.ensure_sandbox(session_id)
    yield session_id
    manager.remove_sandbox(session_id)


def test_sandbox_runs_code_and_mirrors_logs(manager, session_id):
    code = (
        "import sys\n"
        "print('hello from the sandbox')\n"
        "with open('/workspace/marker.txt', 'w') as f:\n"
        "    f.write('made it')\n"
        "sys.exit(0)\n"
    )
    execution = manager.run_code(session_id, "runs/001.py", code)

    output = "".join(execution.chunks())

    assert "hello from the sandbox" in output
    assert execution.exit_code == 0
    # docker logs contain the same output (via the tailed activity.log)
    assert "hello from the sandbox" in manager.get_logs(session_id, tail=50)


def test_sandbox_nonzero_exit_code_is_propagated(manager, session_id):
    execution = manager.run_code(session_id, "runs/002.py", "raise SystemExit(3)\n")

    "".join(execution.chunks())
    assert execution.exit_code == 3


def test_sandbox_workspace_files_and_reads(manager, session_id):
    execution = manager.run_code(
        session_id,
        "runs/003.py",
        "open('/workspace/results.txt', 'w').write('42')\n",
    )
    "".join(execution.chunks())

    names = {entry["name"] for entry in manager.list_files(session_id)}
    assert {"runs", "results.txt", "activity.log"} <= names

    content = manager.read_file(session_id, "/workspace/results.txt")
    assert content is not None
    assert content["content"] == "42"


def test_sandbox_reset_wipes_state(manager, session_id):
    execution = manager.run_code(
        session_id, "runs/004.py", "open('/workspace/before.txt', 'w').write('x')\n"
    )
    "".join(execution.chunks())
    manager.reset_sandbox(session_id)

    names = {entry["name"] for entry in manager.list_files(session_id)}
    assert "before.txt" not in names
    # the fresh container has only the activity log
    assert names == {"activity.log"}
