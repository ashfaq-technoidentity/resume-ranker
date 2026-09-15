import io
import json
import tarfile

import pytest

import sandbox as sandbox_module
from sandbox import SandboxManager, _human_size, parse_mount_spec

# ---- fake docker SDK objects --------------------------------------------


class FakeExecResult:
    def __init__(self, exit_code: int, output: bytes):
        self.exit_code = exit_code
        self.output = output


class FakeApi:
    def __init__(self):
        self.execs: dict[str, dict] = {}
        self._counter = 0

    def exec_create(self, container_id, cmd, environment=None, workdir=None):
        self._counter += 1
        exec_id = f"exec-{self._counter}"
        scripted = self.execs.get(exec_id, {})
        self.execs[exec_id] = {
            "cmd": cmd,
            "environment": environment,
            "workdir": workdir,
            "container": container_id,
            "output": scripted.get("output", []),
            "exit_code": scripted.get("exit_code", 0),
        }
        return {"Id": exec_id}

    def exec_start(self, exec_id, stream=True, demux=False):
        for chunk in self.execs[exec_id]["output"]:
            yield chunk.encode()

    def exec_inspect(self, exec_id):
        return {"ExitCode": self.execs[exec_id]["exit_code"], "Running": False}

    def script_next(self, output: list[str], exit_code: int = 0) -> None:
        """Make the next created exec return this output/exit code."""
        exec_id = f"exec-{self._counter + 1}"
        self.execs[exec_id] = {
            "output": output,
            "exit_code": exit_code,
        }


class FakeContainer:
    def __init__(self, client, kwargs: dict):
        self._client = client
        self.kwargs = dict(kwargs)
        self.id = f"cid-{kwargs['name']}"
        self.name = kwargs["name"]
        self.labels = dict(kwargs.get("labels") or {})
        self.status = "created"
        self.attrs = {
            "State": {
                "Running": False,
                "StartedAt": "2026-01-01T00:00:00Z",
            },
            "Config": {"Image": kwargs.get("image")},
        }
        self.put_archives: list[tuple[str, bytes]] = []
        self.removed = False

    def start(self):
        self.status = "running"
        self.attrs["State"]["Running"] = True

    def stop(self, timeout=None):
        self.status = "exited"
        self.attrs["State"]["Running"] = False

    def remove(self, force=False):
        self.removed = True
        self._client.containers._remove(self)

    def put_archive(self, path, data):
        self.put_archives.append((path, data))

    def logs(self, tail=None, stream=False, follow=False):
        text = "\n".join(self._client.log_lines.get(self.name, []))
        if stream:
            return iter([text.encode()])
        return text.encode()

    def exec_run(self, cmd, **kwargs):
        return self._client.exec_results.get(
            (self.name, tuple(cmd)), FakeExecResult(1, b"")
        )

    def get_archive(self, path):
        return self._client.get_archive(self, path)


class FakeContainers:
    def __init__(self, client):
        self._client = client
        self.items: list[FakeContainer] = []
        self.create_kwargs: list[dict] = []
        self.fail_create: Exception | None = None

    def _remove(self, container):
        if container in self.items:
            self.items.remove(container)

    def create(self, **kwargs):
        if self.fail_create:
            raise self.fail_create
        self.create_kwargs.append(kwargs)
        container = FakeContainer(self._client, kwargs)
        self.items.append(container)
        return container

    def list(self, all=False, filters=None):
        label_filter = (filters or {}).get("label")
        result = []
        for container in self.items:
            if container.removed:
                continue
            if label_filter and not self._matches(container, label_filter):
                continue
            if not all and container.status != "running":
                continue
            result.append(container)
        return result

    @staticmethod
    def _matches(container, label_filter: str) -> bool:
        key, _, value = label_filter.partition("=")
        return container.labels.get(key) == value


class FakeVolume:
    def __init__(self, name, labels):
        self.name = name
        self.labels = dict(labels)
        self.removed = False

    def remove(self, force=False):
        self.removed = True


class FakeVolumes:
    def __init__(self, client):
        self._client = client
        self.items: list[FakeVolume] = []

    def create(self, name, labels=None):
        volume = FakeVolume(name, labels or {})
        self.items.append(volume)
        return volume

    def get(self, name):
        for volume in self.items:
            if volume.name == name:
                return volume
        raise Exception(f"volume {name} not found")

    def list(self, filters=None):
        label_filter = (filters or {}).get("label")
        key, _, value = label_filter.partition("=")
        return [
            volume
            for volume in self.items
            if not volume.removed and volume.labels.get(key) == value
        ]

    def _remove(self, volume):
        volume.removed = True


class FakeDockerClient:
    def __init__(self):
        self.api = FakeApi()
        self.containers = FakeContainers(self)
        self.volumes = FakeVolumes(self)
        self.log_lines: dict[str, list[str]] = {}
        self.exec_results: dict[tuple[str, tuple], FakeExecResult] = {}
        self.pinged = False

    def ping(self):
        self.pinged = True

    def get_archive(self, container, path):
        member = path.lstrip("/")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo(member)
            payload = json.dumps({"path": path, "marker": True}).encode()
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        return iter([buffer.getvalue()]), {"name": member, "size": 40}


@pytest.fixture()
def resumes_db(tmp_path, monkeypatch):
    db_file = tmp_path / "resumes.db"
    db_file.write_bytes(b"sqlite-data")
    monkeypatch.setenv("RESUMES_DB_PATH", str(db_file))
    return db_file


@pytest.fixture()
def manager(tmp_path, resumes_db, monkeypatch):
    monkeypatch.delenv("SANDBOX_RESUMES_MOUNT", raising=False)
    client = FakeDockerClient()
    return SandboxManager(client)


# ---- mount specs and paths ----------------------------------------------


def test_parse_mount_spec_bind_with_mode():
    assert parse_mount_spec("bind:/tmp/x.db:/data/resumes/resumes.db:ro") == {
        "/tmp/x.db": {"bind": "/data/resumes/resumes.db", "mode": "ro"}
    }


def test_parse_mount_spec_volume_defaults_ro():
    assert parse_mount_spec("volume:resumes:/data/resumes") == {
        "resumes": {"bind": "/data/resumes", "mode": "ro"}
    }


@pytest.mark.parametrize(
    "spec",
    [
        "nonsense",
        "symlink:/x:/y",
        "bind:",
        "bind:/x",
        "bind:/x:relative",
    ],
)
def test_parse_mount_spec_invalid(spec):
    with pytest.raises(RuntimeError, match="SANDBOX_RESUMES_MOUNT"):
        parse_mount_spec(spec)


def test_default_resumes_mount_binds_the_db_file(tmp_path, monkeypatch):
    db_file = tmp_path / "resumes.db"
    monkeypatch.setenv("RESUMES_DB_PATH", str(db_file))
    monkeypatch.delenv("SANDBOX_RESUMES_MOUNT", raising=False)

    spec = sandbox_module.default_resumes_mount()

    assert spec == f"bind:{db_file}:/data/resumes/resumes.db:ro"


def test_safe_workspace_path_rejects_traversal():
    for path in ["..", "../etc/passwd", "/workspace/../etc", "/etc/passwd"]:
        with pytest.raises(ValueError):
            SandboxManager._safe_workspace_path(path)


def test_safe_workspace_path_normalizes():
    assert SandboxManager._safe_workspace_path("runs/1.py") == "/workspace/runs/1.py"
    assert SandboxManager._safe_workspace_path("/workspace//a/../b") == ("/workspace/b")


# ---- lifecycle -----------------------------------------------------------


def test_ensure_sandbox_creates_hardened_container(manager, resumes_db):
    container = manager.ensure_sandbox("sess1")

    assert container.status == "running"
    kwargs = manager._client.containers.create_kwargs[0]
    assert kwargs["name"] == "resume-ranker-sandbox-sess1"
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges"]
    assert kwargs["pids_limit"] == 256
    assert kwargs["labels"]["resume-ranker.session"] == "sess1"
    # workspace volume (rw) + resumes db (ro) are both mounted
    volumes = kwargs["volumes"]
    assert volumes["resume-ranker-ws-sess1"] == {
        "bind": "/workspace",
        "mode": "rw",
    }
    assert str(resumes_db) in volumes
    assert volumes[str(resumes_db)]["mode"] == "ro"


def test_ensure_sandbox_reuses_and_starts_existing_container(manager):
    manager.ensure_sandbox("sess1")
    manager._client.containers.items[0].stop()

    container = manager.ensure_sandbox("sess1")

    assert len(manager._client.containers.create_kwargs) == 1
    assert container.status == "running"


def test_ensure_sandbox_missing_image_hint(manager):
    manager._client.containers.fail_create = Exception("No such image: boom")

    with pytest.raises(RuntimeError, match="docker build --target sandbox"):
        manager.ensure_sandbox("sess1")


def test_resumes_mount_missing_file_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_RESUMES_MOUNT", f"bind:{tmp_path}/nope.db:/data/x:ro")
    client = FakeDockerClient()
    manager = SandboxManager(client)

    with pytest.raises(RuntimeError, match="Resumes database not found"):
        manager.ensure_sandbox("sess1")


def test_reset_sandbox_destroys_and_recreates(manager):
    manager.ensure_sandbox("sess1")
    first = manager._client.containers.items[0]

    manager.reset_sandbox("sess1")

    assert first.removed
    volumes = [v for v in manager._client.volumes.items if not v.removed]
    assert len(volumes) == 1  # fresh workspace volume
    assert len(manager._client.containers.items) == 1


def test_remove_sandbox_cleans_up(manager):
    manager.ensure_sandbox("sess1")

    manager.remove_sandbox("sess1")

    assert manager._client.containers.items == []
    assert [v for v in manager._client.volumes.items if not v.removed] == []


# ---- execution -----------------------------------------------------------


def test_run_code_stages_script_and_execs_agent_run(manager):
    manager.ensure_sandbox("sess1")
    manager._client.api.script_next(["hello\n", "world\n"], exit_code=0)

    execution = manager.run_code("sess1", "runs/001.py", "print('hello')")

    container = manager._client.containers.items[0]
    path, data = container.put_archives[0]
    assert path == "/workspace"
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        assert tar.getmember("runs").isdir()
        member = tar.extractfile("runs/001.py")
        assert member.read() == b"print('hello')"

    chunks = list(execution.chunks())
    assert chunks == ["hello\n", "world\n"]
    assert execution.exit_code == 0
    exec_spec = next(iter(manager._client.api.execs.values()))
    assert exec_spec["cmd"] == ["agent-run", "runs/001.py"]
    assert exec_spec["environment"] == {"AGENT_RUN_TIMEOUT": "120"}
    assert exec_spec["workdir"] == "/workspace"


def test_next_script_name_increments_per_session(manager):
    assert manager.next_script_name("s1") == "runs/001.py"
    assert manager.next_script_name("s1") == "runs/002.py"
    assert manager.next_script_name("s2") == "runs/001.py"


def test_install_packages_validates_specs(manager):
    manager.ensure_sandbox("sess1")

    with pytest.raises(RuntimeError, match="Invalid package spec"):
        manager.install_packages("sess1", ["--index-url=http://evil"])
    with pytest.raises(RuntimeError, match="Invalid package spec"):
        manager.install_packages("sess1", ["pypdf; rm -rf /"])
    with pytest.raises(RuntimeError, match="At most"):
        manager.install_packages("sess1", [f"pkg{i}" for i in range(21)])


def test_install_packages_execs_agent_pip(manager):
    manager.ensure_sandbox("sess1")
    manager._client.api.script_next(["Collecting pypdf\n"], exit_code=0)

    execution = manager.install_packages("sess1", ["pypdf", "pandas>=2"])

    assert list(execution.chunks()) == ["Collecting pypdf\n"]
    exec_spec = next(iter(manager._client.api.execs.values()))
    assert exec_spec["cmd"] == ["agent-pip", "pypdf", "pandas>=2"]


# ---- observability -------------------------------------------------------


def test_get_logs(manager):
    manager.ensure_sandbox("sess1")
    manager._client.log_lines["resume-ranker-sandbox-sess1"] = ["line1", "line2"]

    assert manager.get_logs("sess1", tail=10) == "line1\nline2"
    assert manager.get_logs("missing") == ""


def test_stream_logs_yields_chunks(manager):
    manager.ensure_sandbox("sess1")
    manager._client.log_lines["resume-ranker-sandbox-sess1"] = ["booting"]

    assert list(manager.stream_logs("sess1")) == ["booting"]


def test_list_files_execs_json_listing(manager):
    manager.ensure_sandbox("sess1")
    entries = [
        {"name": "a.py", "path": "/workspace/a.py", "size": 3, "is_dir": False},
    ]
    manager._client.exec_results[
        (
            "resume-ranker-sandbox-sess1",
            ("python3", "-c", sandbox_module._LIST_FILES_CODE, "/workspace"),
        )
    ] = FakeExecResult(0, json.dumps(entries).encode())

    assert manager.list_files("sess1") == entries


def test_list_files_missing_container_returns_empty(manager):
    assert manager.list_files("missing") == []


def test_read_file_extracts_tar_content(manager):
    manager.ensure_sandbox("sess1")

    content = manager.read_file("sess1", "/workspace/runs/001.py")

    assert content is not None
    assert content["path"] == "/workspace/runs/001.py"
    assert json.loads(content["content"])["path"] == "/workspace/runs/001.py"
    assert content["binary"] is False


def test_read_file_missing_returns_none(manager):
    manager.ensure_sandbox("sess1")

    def broken(container, path):
        raise Exception("no such file")

    manager._client.get_archive = broken
    assert manager.read_file("sess1", "/workspace/nope.txt") is None


def test_status_missing_container(manager):
    assert manager.status("missing") == {"running": False, "status": "missing"}


def test_status_running_container(manager):
    manager.ensure_sandbox("sess1")

    snapshot = manager.status("sess1")

    assert snapshot["running"] is True
    assert snapshot["name"] == "resume-ranker-sandbox-sess1"
    assert snapshot["workspace_volume"] == "resume-ranker-ws-sess1"


# ---- housekeeping ---------------------------------------------------------


def test_reap_idle_stops_stale_containers(manager, monkeypatch):
    monkeypatch.setenv("SANDBOX_IDLE_TIMEOUT", "0")
    manager.ensure_sandbox("sess1")
    manager.ensure_sandbox("sess2")
    manager._last_used["sess2"] = float("inf")  # never reaped

    stopped = manager.reap_idle()

    assert stopped == ["sess1"]
    statuses = {c.name: c.status for c in manager._client.containers.items}
    assert statuses["resume-ranker-sandbox-sess1"] == "exited"
    assert statuses["resume-ranker-sandbox-sess2"] == "running"


def test_sweep_orphans_removes_unknown_sessions(manager):
    manager.ensure_sandbox("known")
    manager.ensure_sandbox("orphan")

    removed = manager.sweep_orphans({"known"})

    assert removed == ["orphan"]
    names = [c.name for c in manager._client.containers.items]
    assert "resume-ranker-sandbox-orphan" not in names
    volume_names = [v.name for v in manager._client.volumes.items if not v.removed]
    assert "resume-ranker-ws-orphan" not in volume_names


def test_human_size():
    assert _human_size(512) == "512 B"
    assert _human_size(2048) == "2.0 KiB"
    assert _human_size(5 * 1024 * 1024) == "5.0 MiB"
