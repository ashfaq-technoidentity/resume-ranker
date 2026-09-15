"""Docker sandboxes for the AI assistant.

Each chat session owns one sandbox container (the minimal ``sandbox`` image
target from the Dockerfile) with:

- a writable workspace volume at ``/workspace`` (venv, scripts and results
  persist for the session; resetting the sandbox wipes them)
- the resumes SQLite database mounted READ-ONLY at
  ``/data/resumes/resumes.db`` (a single-file bind mount locally, the whole
  ``resumes`` volume under docker compose)

Code runs via ``docker exec`` with the image's ``agent-run`` wrapper, which
tee's its output into ``/workspace/activity.log``; the container's main
process tails that file, so every install/run shows up in ``docker logs``.
No network connection between the API and the sandbox is needed —
everything goes through the Docker SDK. The docker module is imported
lazily so installs without it (or without a running daemon) still serve the
rest of the API; callers map RuntimeError to a 503.
"""

import io
import os
import re
import tarfile
import time

SANDBOX_LABEL = "resume-ranker.sandbox"
SESSION_LABEL = "resume-ranker.session"
WORKSPACE = "/workspace"
RESUMES_DB_IN_SANDBOX = "/data/resumes/resumes.db"
RESUMES_DIR_IN_SANDBOX = "/data/resumes"

SANDBOX_IMAGE_ENV = "SANDBOX_IMAGE"
DEFAULT_SANDBOX_IMAGE = "resume-ranker-sandbox"

# PyPI name/version specs (e.g. pypdf, pypdf[crypto], pandas>=2), rejecting
# leading dashes so pip flags can never be smuggled in through a package name
_PACKAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\[\],=<>!~;+-]*$")
_MAX_PACKAGES = 20
_MAX_PACKAGE_LENGTH = 200

# file-content reads are capped so the files browser stays snappy
_MAX_READ_BYTES = 1024 * 1024

_LIST_FILES_CODE = (
    "import json,os,sys\n"
    "p = sys.argv[1]\n"
    "entries = []\n"
    "for name in sorted(os.listdir(p)):\n"
    "    full = os.path.join(p, name)\n"
    "    entries.append({'name': name, 'path': full,\n"
    "        'size': 0 if os.path.isdir(full) else os.path.getsize(full),\n"
    "        'is_dir': os.path.isdir(full),\n"
    "        'mtime': os.path.getmtime(full)})\n"
    "print(json.dumps(entries))\n"
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def sandbox_enabled() -> bool:
    """SANDBOX_ENABLED=0 turns the whole agent feature off (503 in the API)."""
    return os.environ.get("SANDBOX_ENABLED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def default_resumes_mount() -> str:
    """Mount spec for the resumes DB: the single file, read-only.

    Local dev binds just the DB file (never the project dir, which holds
    .env with the API key); docker compose overrides this with the whole
    ``resumes`` volume, which contains only the DB.
    """
    db_path = os.path.abspath(
        os.environ.get("RESUMES_DB_PATH", "resumes.db") or "resumes.db"
    )
    return f"bind:{db_path}:{RESUMES_DB_IN_SANDBOX}:ro"


def parse_mount_spec(spec: str) -> dict:
    """Parse ``bind|volume:<source>:<dest>[:mode]`` into a docker-py volumes
    dict (bind mounts and named volumes share the same shape)."""
    parts = spec.split(":")
    if len(parts) == 3:
        kind, source, dest = parts
        mode = "ro"
    elif len(parts) == 4:
        kind, source, dest, mode = parts
    else:
        raise RuntimeError(
            f"Invalid SANDBOX_RESUMES_MOUNT '{spec}': expected "
            "bind|volume:<source>:<dest>[:ro|rw]"
        )
    if kind not in ("bind", "volume"):
        raise RuntimeError(
            f"Invalid SANDBOX_RESUMES_MOUNT '{spec}': kind must be bind or volume"
        )
    if not source or not dest.startswith("/"):
        raise RuntimeError(f"Invalid SANDBOX_RESUMES_MOUNT '{spec}'")
    return {source: {"bind": dest, "mode": mode}}


class StreamingExec:
    """One docker exec with live output chunks and the final exit code."""

    def __init__(
        self, api, container_id: str, cmd: list[str], environment: dict | None = None
    ) -> None:
        self._api = api
        self._exec_id = api.exec_create(
            container_id, cmd, environment=environment, workdir=WORKSPACE
        )["Id"]
        self.exit_code: int | None = None

    def chunks(self):
        """Yield output chunks as they arrive; sets exit_code when done."""
        for chunk in self._api.exec_start(self._exec_id, stream=True, demux=False):
            if chunk:
                yield chunk.decode("utf-8", errors="replace")
        self.exit_code = self._api.exec_inspect(self._exec_id).get("ExitCode")


class SandboxManager:
    """Manages per-session sandbox containers and workspace volumes."""

    def __init__(self, client) -> None:
        self._client = client
        self._last_used: dict[str, float] = {}
        self._script_counters: dict[str, int] = {}

    # ---- helpers -------------------------------------------------------

    def _volume_name(self, session_id: str) -> str:
        return f"resume-ranker-ws-{session_id}"

    def _container_name(self, session_id: str) -> str:
        return f"resume-ranker-sandbox-{session_id}"

    def _resumes_mount(self) -> dict:
        spec = os.environ.get("SANDBOX_RESUMES_MOUNT") or default_resumes_mount()
        mount = parse_mount_spec(spec)
        source = next(iter(mount))
        if source.startswith("/") and not os.path.exists(source):
            raise RuntimeError(
                f"Resumes database not found at '{source}' — store some "
                "resumes first (the sandbox mounts it read-only)"
            )
        return mount

    def _touch(self, session_id: str) -> None:
        self._last_used[session_id] = time.monotonic()

    def _find_container(self, session_id: str):
        """A session's container (stopped ones included), or None."""
        containers = self._client.containers.list(
            all=True, filters={"label": f"{SESSION_LABEL}={session_id}"}
        )
        return containers[0] if containers else None

    @staticmethod
    def _tar_script_bytes(arcname: str, content: bytes) -> bytes:
        """In-memory tarball with a parent dir entry plus one file."""
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            parent = tarfile.TarInfo(arcname.split("/")[0])
            parent.type = tarfile.DIRTYPE
            parent.mode = 0o755
            tar.addfile(parent)
            info = tarfile.TarInfo(arcname)
            info.size = len(content)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(content))
        return buffer.getvalue()

    # ---- lifecycle -----------------------------------------------------

    def ensure_sandbox(self, session_id: str):
        """Return the session's running container, creating it if needed."""
        self._touch(session_id)
        container = self._find_container(session_id)
        if container is not None:
            if container.status != "running":
                container.start()
            return container

        volume_name = self._volume_name(session_id)
        try:
            workspace = self._client.volumes.create(
                name=volume_name,
                labels={SANDBOX_LABEL: "true", SESSION_LABEL: session_id},
            )
            container = self._client.containers.create(
                image=os.environ.get(SANDBOX_IMAGE_ENV, DEFAULT_SANDBOX_IMAGE),
                name=self._container_name(session_id),
                volumes={
                    workspace.name: {"bind": WORKSPACE, "mode": "rw"},
                    **self._resumes_mount(),
                },
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                mem_limit=os.environ.get("SANDBOX_MEM_LIMIT", "1g"),
                nano_cpus=int(_env_float("SANDBOX_CPUS", 1.0) * 1_000_000_000),
                pids_limit=_env_int("SANDBOX_PIDS_LIMIT", 256),
                labels={SANDBOX_LABEL: "true", SESSION_LABEL: session_id},
                # the sandbox needs internet for pip installs; everything
                # else about it is locked down (no caps, resource limits)
                detach=True,
            )
            container.start()
            return container
        except Exception as error:
            message = str(error)
            if "No such image" in message or "manifest unknown" in message:
                raise RuntimeError(
                    "Sandbox image "
                    f"'{os.environ.get(SANDBOX_IMAGE_ENV, DEFAULT_SANDBOX_IMAGE)}' "
                    "not found — build it with: docker build --target sandbox "
                    "-t resume-ranker-sandbox ."
                ) from error
            raise RuntimeError(
                f"Failed to create sandbox container: {message}"
            ) from error

    def remove_sandbox(self, session_id: str, keep_volume: bool = False) -> None:
        """Destroy the session's container (and workspace volume)."""
        self._script_counters.pop(session_id, None)
        container = self._find_container(session_id)
        if container is not None:
            container.remove(force=True)
        if not keep_volume:
            try:
                self._client.volumes.get(self._volume_name(session_id)).remove(
                    force=True
                )
            except Exception:
                pass  # volume already gone / in use — best effort cleanup

    def reset_sandbox(self, session_id: str):
        """Fresh container + empty workspace (installs and files wiped)."""
        self.remove_sandbox(session_id)
        return self.ensure_sandbox(session_id)

    # ---- execution -----------------------------------------------------

    def next_script_name(self, session_id: str) -> str:
        counter = self._script_counters.get(session_id, 0) + 1
        self._script_counters[session_id] = counter
        return f"runs/{counter:03d}.py"

    def run_code(self, session_id: str, script_name: str, code: str) -> StreamingExec:
        """Write ``code`` into the workspace and execute it via agent-run.

        The wrapper tee's output into activity.log (visible in docker logs)
        and hard-kills scripts that run past SANDBOX_EXEC_TIMEOUT.
        """
        container = self.ensure_sandbox(session_id)
        self._touch(session_id)
        try:
            container.put_archive(
                WORKSPACE,
                self._tar_script_bytes(script_name, code.encode("utf-8")),
            )
        except Exception as error:
            raise RuntimeError(f"Failed to stage script in sandbox: {error}") from error
        timeout = _env_int("SANDBOX_EXEC_TIMEOUT", 120)
        return self._exec(
            container,
            ["agent-run", script_name],
            environment={"AGENT_RUN_TIMEOUT": str(timeout)},
        )

    def install_packages(self, session_id: str, packages: list[str]) -> StreamingExec:
        """pip install packages into the session venv (agent-pip wrapper)."""
        if not packages:
            raise RuntimeError("No packages to install")
        if len(packages) > _MAX_PACKAGES:
            raise RuntimeError(f"At most {_MAX_PACKAGES} packages per install")
        for package in packages:
            if (
                not _PACKAGE_PATTERN.match(package)
                or len(package) > _MAX_PACKAGE_LENGTH
            ):
                raise RuntimeError(f"Invalid package spec: {package!r}")
        container = self.ensure_sandbox(session_id)
        self._touch(session_id)
        timeout = _env_int("SANDBOX_EXEC_TIMEOUT", 120)
        return self._exec(
            container,
            ["agent-pip", *packages],
            environment={"AGENT_RUN_TIMEOUT": str(timeout)},
        )

    def _exec(
        self, container, cmd: list[str], environment: dict | None = None
    ) -> StreamingExec:
        return StreamingExec(self._client.api, container.id, cmd, environment)

    # ---- observability --------------------------------------------------

    def get_logs(self, session_id: str, tail: int = 200) -> str:
        container = self._find_container(session_id)
        if container is None:
            return ""
        return container.logs(tail=tail).decode("utf-8", errors="replace")

    def stream_logs(self, session_id: str, tail: int = 100):
        """Live docker logs (follows the tailed activity.log)."""
        container = self._find_container(session_id)
        if container is None:
            raise RuntimeError(f"No sandbox for session {session_id}")
        self._touch(session_id)
        for chunk in container.logs(stream=True, follow=True, tail=tail):
            yield chunk.decode("utf-8", errors="replace")

    def list_files(self, session_id: str, path: str = WORKSPACE) -> list[dict]:
        """One workspace directory's entries (name/size/is_dir/mtime)."""
        import json

        path = self._safe_workspace_path(path)
        container = self._find_container(session_id)
        if container is None:
            return []
        self._touch(session_id)
        result = container.exec_run(["python3", "-c", _LIST_FILES_CODE, path])
        if result.exit_code != 0 or not result.output:
            raise RuntimeError(f"Failed to list sandbox files at '{path}'")
        entries = json.loads(result.output.decode("utf-8"))
        return [entry for entry in entries if not entry["name"].startswith(".")]

    def read_file(self, session_id: str, path: str) -> dict | None:
        """One sandbox file's content (capped at 1 MiB, text-decoded)."""
        path = self._safe_workspace_path(path)
        container = self._find_container(session_id)
        if container is None:
            return None
        self._touch(session_id)
        try:
            stream, stat = container.get_archive(path)
        except Exception:
            return None  # missing file
        size = int(stat.get("size", 0))
        data = b"".join(stream)
        content_bytes = self._extract_file_from_tar(data, path)
        truncated = len(content_bytes) > _MAX_READ_BYTES
        content_bytes = content_bytes[:_MAX_READ_BYTES]
        binary = b"\x00" in content_bytes[:8192]
        return {
            "path": path,
            "size": size,
            "truncated": truncated,
            "binary": binary,
            "content": (
                "" if binary else content_bytes.decode("utf-8", errors="replace")
            ),
        }

    @staticmethod
    def _extract_file_from_tar(tar_bytes: bytes, path: str) -> bytes:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
            stripped = path.lstrip("/")
            # docker names a directly-requested file by its basename, but a
            # file reached through a directory request keeps its relative
            # path — accept either
            names = {
                member.name.rstrip("/")
                for member in tar.getmembers()
                if member.isfile()
            }
            for name in (stripped, stripped.split("/")[-1]):
                if name in names:
                    extracted = tar.extractfile(name)
                    return extracted.read() if extracted else b""
            return b""

    @staticmethod
    def _safe_workspace_path(path: str) -> str:
        """Reject path traversal; everything readable must live in /workspace."""
        import posixpath

        if not path.startswith("/"):
            path = posixpath.join(WORKSPACE, path)
        normalized = posixpath.normpath(path)
        if normalized == ".." or normalized.startswith("../"):
            raise ValueError(f"Path escapes the sandbox workspace: {path}")
        if not (normalized == WORKSPACE or normalized.startswith(WORKSPACE + "/")):
            raise ValueError(f"Only files inside {WORKSPACE} are readable: {path}")
        return normalized

    def status(self, session_id: str) -> dict:
        """Container state + a resource-usage snapshot."""
        container = self._find_container(session_id)
        if container is None:
            return {"running": False, "status": "missing"}
        state = container.attrs.get("State", {}) or {}
        running = bool(state.get("Running"))
        result = {
            "container_id": container.id,
            "name": container.name,
            "image": container.attrs.get("Config", {}).get("Image"),
            "status": container.status,
            "running": running,
            "started_at": state.get("StartedAt"),
            "workspace_volume": self._volume_name(session_id),
        }
        if running:
            try:
                stats = container.stats(stream=False)
                memory = stats.get("memory_stats", {})
                cpu = stats.get("cpu_stats", {})
                precpu = stats.get("precpu_stats", {})
                usage = memory.get("usage")
                if usage is not None:
                    result["mem_usage"] = _human_size(int(usage))
                cpu_delta = (cpu.get("cpu_usage", {}) or {}).get("total_usage", 0) - (
                    precpu.get("cpu_usage", {}) or {}
                ).get("total_usage", 0)
                system_delta = cpu.get("system_cpu_usage", 0) - precpu.get(
                    "system_cpu_usage", 0
                )
                online = cpu.get("online_cpus", 0) or len(
                    (cpu.get("cpu_usage", {}) or {}).get("percpu_usage", []) or [1]
                )
                if system_delta > 0:
                    result["cpu_percent"] = round(
                        cpu_delta / system_delta * online * 100, 1
                    )
            except Exception:
                pass  # stats are best-effort decoration
        return result

    # ---- housekeeping ----------------------------------------------------

    def reap_idle(self) -> list[str]:
        """Stop sandboxes idle past SANDBOX_IDLE_TIMEOUT (volumes are kept)."""
        timeout = _env_float("SANDBOX_IDLE_TIMEOUT", 1800.0)
        stopped: list[str] = []
        for container in self._client.containers.list(
            filters={"label": f"{SANDBOX_LABEL}=true"}
        ):
            session_id = container.labels.get(SESSION_LABEL)
            if not session_id:
                continue
            last_used = self._last_used.get(session_id)
            if last_used is None:
                # unknown after an API restart: fall back to the container's
                # start time so long-forgotten sandboxes still get reaped
                started = container.attrs.get("State", {}).get("StartedAt")
                try:
                    from datetime import datetime, timezone

                    started_at = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - started_at).total_seconds()
                except Exception:
                    age = 0.0
                if age < timeout:
                    continue
            elif time.monotonic() - last_used < timeout:
                continue
            try:
                container.stop(timeout=5)
                stopped.append(session_id)
            except Exception:
                pass  # already stopping — fine
        return stopped

    def sweep_orphans(self, known_session_ids: set[str]) -> list[str]:
        """Remove containers/volumes whose session no longer exists in the DB."""
        removed: list[str] = []
        for container in self._client.containers.list(
            all=True, filters={"label": f"{SANDBOX_LABEL}=true"}
        ):
            session_id = container.labels.get(SESSION_LABEL)
            if session_id and session_id not in known_session_ids:
                try:
                    container.remove(force=True)
                    removed.append(session_id)
                except Exception:
                    pass
        for volume in self._client.volumes.list(
            filters={"label": f"{SANDBOX_LABEL}=true"}
        ):
            session_id = volume.labels.get(SESSION_LABEL)
            if session_id and session_id not in known_session_ids:
                try:
                    volume.remove(force=True)
                except Exception:
                    pass
        return removed


def _human_size(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


_manager: SandboxManager | None = None


def get_sandbox_manager() -> SandboxManager:
    """Singleton manager; raises RuntimeError when docker is unusable."""
    global _manager
    if _manager is not None:
        return _manager
    if not sandbox_enabled():
        raise RuntimeError("The agent sandbox is disabled (SANDBOX_ENABLED=0)")
    try:
        import docker
    except ImportError as error:
        raise RuntimeError(f"The docker package is not installed: {error}") from error
    try:
        client = docker.from_env()
        client.ping()
    except Exception as error:
        raise RuntimeError(f"Cannot reach the Docker daemon: {error}") from error
    _manager = SandboxManager(client)
    return _manager
