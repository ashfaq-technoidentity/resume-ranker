"""The AI assistant's agent loop.

A classic tool-calling loop: the model (via agent_llm) either answers in
plain text (the run ends) or calls one of the tools (install_packages,
run_python) which execute in the session's Docker sandbox. Every step —
thoughts, actions, streamed output, observations, the final answer, and
errors — is emitted as an event that is both persisted (agent_db, for
replay after a reload) and pushed to the SSE live queue.
"""

import asyncio
import json
import os
import sqlite3
import threading
import uuid

import agent_db
import agent_llm
import sandbox

DEFAULT_MAX_STEPS = 12
DEFAULT_HISTORY_MESSAGES = 20
DEFAULT_OBSERVATION_CHARS = 8000
# streamed exec output is coalesced to lines and capped so a chatty script
# can't flood the event log (the full output still lands in the observation)
_MAX_OUTPUT_LINES = 500
_MAX_RAW_OUTPUT_CHARS = 64000

TIMEOUT_EXIT_CODES = (124, 137)

SYSTEM_PROMPT = """You are the AI assistant of the Resume Ranker app. Users ask questions about the stored resumes; you answer by writing and running Python code inside a Docker sandbox.

## Environment
- You run Python 3.12 in a sandboxed container. Your working directory is /workspace — a private, persistent folder for this chat session. Save scripts and results there; files survive between your turns.
- Install packages with the install_packages tool (they go into /workspace/.venv and persist for the session). Do not try to run pip yourself.
- run_python executes Python code as a script (no stdin) and returns its stdout and stderr. Execution is capped at {timeout} seconds — killed scripts exit with code 137.
- Keep printed output small: print summaries, and save full data to files in /workspace.

## Resumes data
- The resumes database is a SQLite file mounted READ-ONLY at /data/resumes/resumes.db. First copy it into your workspace and open the copy, e.g. shutil.copy("/data/resumes/resumes.db", "/workspace/resumes.db"). Never write to /data/resumes — it is read-only.
- Schema:
    resumes(id, file_name, file_ext, file_hash, name, email, mobile_number,
            skills, degree, designation, company_names, college_name,  -- JSON arrays
            total_experience, no_of_pages, resume_text, file_blob, error,
            created_at, updated_at)
    resume_job_scores(resume_id, job_id, skills_similarity,
                      experience_similarity, average_similarity, model,
                      created_at, updated_at)
- resume_text already contains extracted text for every resume — usually enough for keyword and skill questions.
- file_blob contains the original file bytes (PDF or DOCX). Write them into /workspace and parse them with a library you installed (e.g. pypdf) when you need more than resume_text.
- There are currently {resume_count} resumes stored.

## Answering
- Final answers are markdown. When you mention specific candidates, link them as [Name](resume://ID) using resumes.id — the UI turns those into clickable resume previews and download links.
- If the user asks for a resume download link, give the same [Name](resume://ID) link and tell them it opens the file (PDFs display inline; the browser can save the file from there). Do not present /workspace paths as user-facing download links — they are inside the sandbox and are not directly clickable in the UI.
- The user can see every step you take and can browse your files and logs, so keep the trail tidy and reference files you saved when useful.
- Do not modify the databases, send data to external services, or install packages unrelated to the task.
"""

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "install_packages",
            "description": (
                "Install Python packages (PyPI) into the sandbox's persistent "
                "venv. Call this before run_python when the code needs a "
                "library outside the standard library."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            'PyPI package specs, e.g. ["pypdf"] or ["pandas>=2"]'
                        ),
                    }
                },
                "required": ["packages"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Execute Python 3 code in the sandbox as a script (no stdin); "
                "its stdout and stderr are returned. Files written to the "
                "current directory (/workspace) persist across calls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python code to execute.",
                    }
                },
                "required": ["code"],
            },
        },
    },
]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def count_resumes() -> int:
    """Best-effort row count of the resumes DB (0 when unreadable)."""
    path = os.environ.get("RESUMES_DB_PATH", "resumes.db")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT COUNT(*) FROM resumes").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def build_system_prompt() -> str:
    return SYSTEM_PROMPT.format(
        timeout=_env_int("SANDBOX_EXEC_TIMEOUT", 120),
        resume_count=count_resumes(),
    )


class EventEmitter:
    """Persists events to agent_db and forwards them to the SSE queue."""

    def __init__(
        self, engine, session_id: str, run_id: str, queue: asyncio.Queue
    ) -> None:
        self.engine = engine
        self.session_id = session_id
        self.run_id = run_id
        self.queue = queue

    async def emit(self, event_type: str, data: dict) -> agent_db.AgentEventRecord:
        record = await asyncio.to_thread(
            agent_db.add_event,
            self.engine,
            self.session_id,
            event_type,
            data,
            self.run_id,
        )
        # same shape as AgentEventRecord so live SSE and DB replay match
        await self.queue.put(
            {
                "seq": record.seq,
                "type": record.type,
                "run_id": record.run_id,
                "data": record.data,
            }
        )
        return record


class RunRegistry:
    """Tracks which sessions have an active run (one at a time)."""

    def __init__(self) -> None:
        self._active: set[str] = set()

    def try_start(self, session_id: str) -> bool:
        if session_id in self._active:
            return False
        self._active.add(session_id)
        return True

    def is_active(self, session_id: str) -> bool:
        return session_id in self._active

    def end(self, session_id: str) -> None:
        self._active.discard(session_id)


runs = RunRegistry()


class AgentRun:
    """One user question → tool-calling loop → final answer."""

    def __init__(self, engine, session_id: str, queue: asyncio.Queue) -> None:
        self.engine = engine
        self.session_id = session_id
        self.queue = queue
        self.run_id = uuid.uuid4().hex[:12]
        self.emitter = EventEmitter(engine, session_id, self.run_id, queue)
        self.manager = sandbox.get_sandbox_manager()
        self.client = agent_llm.get_chat_client()
        self.max_steps = _env_int("AGENT_MAX_STEPS", DEFAULT_MAX_STEPS)

    async def run(self) -> None:
        try:
            await self.emitter.emit("run_started", {"run_id": self.run_id})
            await self._loop()
        except Exception as error:  # noqa: BLE001 - reported to the user
            message = str(error)
            if len(message) > 600:
                message = message[:600] + "…"
            await self.emitter.emit("error", {"message": message})
            await asyncio.to_thread(
                agent_db.add_message,
                self.engine,
                self.session_id,
                "assistant",
                f"The run failed: {message}",
                self.run_id,
            )
            await self.emitter.emit(
                "run_done", {"run_id": self.run_id, "status": "error"}
            )
        finally:
            await self.queue.put(None)

    async def _loop(self) -> None:
        history = await asyncio.to_thread(
            agent_db.list_messages,
            self.engine,
            self.session_id,
            _env_int("AGENT_HISTORY_MAX_MESSAGES", DEFAULT_HISTORY_MESSAGES),
        )
        llm_messages: list[dict] = [
            {"role": "system", "content": build_system_prompt()},
            *[{"role": m.role, "content": m.content} for m in history],
        ]
        for _ in range(self.max_steps):
            message = await asyncio.to_thread(
                self.client.chat, llm_messages, AGENT_TOOLS
            )
            content = message.get("content") or ""
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                # no tool calls: this turn's text is the final answer (never
                # duplicated as a "thought" event)
                if not content:
                    raise RuntimeError("The model returned an empty response")
                record = await asyncio.to_thread(
                    agent_db.add_message,
                    self.engine,
                    self.session_id,
                    "assistant",
                    content,
                    self.run_id,
                )
                await self.emitter.emit(
                    "answer", {"content": content, "message_id": record.id}
                )
                await self.emitter.emit(
                    "run_done", {"run_id": self.run_id, "status": "completed"}
                )
                return
            if content:
                await self.emitter.emit("thought", {"content": content})
            llm_messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                observation, exit_code = await self._execute_call(call)
                await self.emitter.emit(
                    "observation",
                    {
                        "tool_call_id": call.get("id", ""),
                        "tool": call["function"]["name"],
                        "exit_code": exit_code,
                        "output": observation,
                    },
                )
                llm_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": observation,
                    }
                )
        raise RuntimeError(
            f"the agent reached its limit of {self.max_steps} steps without "
            "finishing an answer"
        )

    async def _execute_call(self, call: dict) -> tuple[str, int]:
        name = call["function"]["name"]
        tool_call_id = call.get("id", "")
        try:
            arguments = json.loads(call["function"].get("arguments") or "{}")
        except json.JSONDecodeError as error:
            return f"Invalid arguments JSON for {name}: {error}", 1

        await self.emitter.emit(
            "action", {"tool_call_id": tool_call_id, "tool": name, "input": arguments}
        )
        try:
            if name == "run_python":
                code = arguments.get("code")
                if not isinstance(code, str) or not code.strip():
                    raise ValueError("run_python requires non-empty 'code'")
                script_name = await asyncio.to_thread(
                    self.manager.next_script_name, self.session_id
                )
                execution = await asyncio.to_thread(
                    self.manager.run_code, self.session_id, script_name, code
                )
                return await _stream_execution(
                    self.emitter, execution, tool_call_id, name
                )
            if name == "install_packages":
                packages = arguments.get("packages")
                if not isinstance(packages, list) or not packages:
                    raise ValueError("install_packages requires 'packages'")
                execution = await asyncio.to_thread(
                    self.manager.install_packages, self.session_id, packages
                )
                return await _stream_execution(
                    self.emitter, execution, tool_call_id, name
                )
            raise ValueError(f"unknown tool: {name}")
        except Exception as error:  # noqa: BLE001 - fed back as observation
            return f"{name} failed: {error}", 1


async def _stream_execution(
    emitter, execution, tool_call_id: str, tool: str
) -> tuple[str, int]:
    """Consume a sandbox exec's live output, emitting coalesced line events.

    Returns (observation_text, exit_code) — the observation is the output
    capped for the LLM context, with a note when the script timed out.
    """
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    lines_emitted = 0

    def pump() -> None:
        nonlocal lines_emitted
        buffer = ""
        suppressed = False
        try:
            for chunk in execution.chunks():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    lines_emitted += 1
                    if lines_emitted <= _MAX_OUTPUT_LINES:
                        asyncio.run_coroutine_threadsafe(
                            queue.put(line + "\n"), loop
                        ).result()
                    elif not suppressed:
                        suppressed = True
                        asyncio.run_coroutine_threadsafe(
                            queue.put(
                                f"... output beyond {_MAX_OUTPUT_LINES} lines "
                                "is hidden; see /workspace/activity.log ...\n"
                            ),
                            loop,
                        ).result()
        finally:
            if buffer and lines_emitted <= _MAX_OUTPUT_LINES:
                asyncio.run_coroutine_threadsafe(queue.put(buffer), loop).result()
            asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    parts: list[str] = []
    while True:
        item = await queue.get()
        if item is None:
            break
        parts.append(item)
        await emitter.emit("output", {"tool_call_id": tool_call_id, "chunk": item})
    thread.join(timeout=5)

    output = "".join(parts)
    if len(output) > _MAX_RAW_OUTPUT_CHARS:
        output = (
            output[: _MAX_RAW_OUTPUT_CHARS // 2]
            + "\n... [output truncated] ...\n"
            + output[-_MAX_RAW_OUTPUT_CHARS // 2 :]
        )
    exit_code = execution.exit_code
    if exit_code in TIMEOUT_EXIT_CODES:
        output = (
            "The command was killed after exceeding the execution timeout.\n" + output
        )
    observation = output[
        : _env_int("AGENT_OBSERVATION_MAX_CHARS", DEFAULT_OBSERVATION_CHARS)
    ]
    if len(output) > len(observation):
        observation += "\n... [output truncated for the model]"
    return observation, exit_code


async def run_agent(engine, session_id: str, queue: asyncio.Queue) -> None:
    """Run one agent turn; the caller holds the per-session run lock
    (``runs.try_start``), and this always releases it."""
    try:
        await AgentRun(engine, session_id, queue).run()
    finally:
        runs.end(session_id)
