"""HTTP API for the AI assistant (chat sessions + sandbox observability).

Routes live under ``/agent``. The heavy modules (agent loop, docker sandbox,
OpenRouter client) are imported lazily inside the handlers so an install
without them — or without a reachable Docker daemon — still serves the rest
of the API, mirroring the resume-workflow pattern in main.py.

``POST /agent/sessions/{id}/chat`` returns an SSE stream of agent events
(thoughts, actions, streamed sandbox output, the final answer); the same
events are persisted via agent_db so ``GET /agent/sessions/{id}`` replays a
session after a reload.
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

import agent_db
from models import (
    AgentChatRequest,
    AgentSessionDetail,
    AgentSessionRecord,
    AgentSessionRename,
    SandboxFileContent,
    SandboxFileEntry,
    SandboxStatus,
)

router = APIRouter(prefix="/agent", tags=["agent"])

# SSE responses need to reach the browser unbuffered
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

_background_tasks: set[asyncio.Task] = set()


def _require_manager(request: Request):
    """Return a usable SandboxManager; 503 when the feature can't run."""
    try:
        import sandbox
    except ImportError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI assistant is unavailable: {error}",
        ) from error
    if not sandbox.sandbox_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI assistant is disabled (SANDBOX_ENABLED=0)",
        )
    try:
        return sandbox.get_sandbox_manager()
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI assistant is unavailable: {error}",
        ) from error


def _require_agent_module(request: Request):
    """Import the agent loop module (run-lock checks); 503 when missing."""
    try:
        import agent
    except ImportError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI assistant is unavailable: {error}",
        ) from error
    return agent


def _require_agent(request: Request):
    """Manager + agent loop + chat client; 503 when any piece is unusable."""
    _require_manager(request)
    agent = _require_agent_module(request)
    try:
        import agent_llm
    except ImportError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI assistant modules are unavailable: {error}",
        ) from error
    try:
        agent_llm.get_chat_client()
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI assistant is not configured: {error}",
        ) from error
    return agent


def _require_session(request: Request, session_id: str) -> AgentSessionRecord:
    session = agent_db.get_session(request.app.state.engine, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )
    return session


# ---- sessions ----------------------------------------------------------


@router.post(
    "/sessions",
    response_model=AgentSessionRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a chat session (and its Docker sandbox)",
)
def create_session(request: Request) -> AgentSessionRecord:
    manager = _require_manager(request)
    session = agent_db.create_session(request.app.state.engine)
    try:
        container = manager.ensure_sandbox(session.id)
    except RuntimeError as error:
        agent_db.delete_session(request.app.state.engine, session.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to create the sandbox: {error}",
        ) from error
    return agent_db.update_session(
        request.app.state.engine,
        session.id,
        sandbox_status="running",
        sandbox_container_id=container.id,
    )


@router.get(
    "/sessions",
    response_model=list[AgentSessionRecord],
    summary="List chat sessions, most recently updated first",
)
def list_sessions(request: Request) -> list[AgentSessionRecord]:
    return agent_db.list_sessions(request.app.state.engine)


@router.get(
    "/sessions/{session_id}",
    response_model=AgentSessionDetail,
    summary="One session with its messages and full event trace (replay)",
)
def get_session_detail(session_id: str, request: Request) -> AgentSessionDetail:
    session = _require_session(request, session_id)
    engine = request.app.state.engine
    return AgentSessionDetail(
        session=session,
        messages=agent_db.list_messages(engine, session_id),
        events=agent_db.list_events(engine, session_id),
    )


@router.patch(
    "/sessions/{session_id}",
    response_model=AgentSessionRecord,
    summary="Rename a chat session",
)
def rename_session(
    session_id: str, changes: AgentSessionRename, request: Request
) -> AgentSessionRecord:
    _require_session(request, session_id)
    record = agent_db.update_session(
        request.app.state.engine, session_id, title=changes.title.strip()[:80]
    )
    assert record is not None  # _require_session guaranteed the row exists
    return record


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a session and destroy its sandbox",
)
def delete_session(session_id: str, request: Request) -> Response:
    _require_session(request, session_id)
    agent = _require_agent_module(request)
    if agent.runs.is_active(session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is active for this session — wait for it to finish",
        )
    try:
        _require_manager(request).remove_sandbox(session_id)
    except Exception:
        pass  # docker down — the rows still go away and orphans get swept
    agent_db.delete_session(request.app.state.engine, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- chat ---------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/chat",
    summary="Ask the assistant a question; streams agent events over SSE",
    description=(
        "Server-sent events: run_started, thought, action, output (streamed"
        " sandbox output), observation, answer, error, run_done. The same"
        " events are persisted and replayed by GET /agent/sessions/{id}."
    ),
)
async def chat(
    session_id: str, chat_request: AgentChatRequest, request: Request
) -> StreamingResponse:
    engine = request.app.state.engine
    agent = _require_agent(request)
    session = _require_session(request, session_id)
    if agent.runs.try_start(session_id):
        try:
            agent_db.add_message(engine, session_id, "user", chat_request.content)
            if session.title == agent_db.DEFAULT_TITLE:
                title = " ".join(chat_request.content.split())[:60]
                agent_db.update_session(
                    engine, session_id, title=title or agent_db.DEFAULT_TITLE
                )
        except Exception:
            agent.runs.end(session_id)
            raise
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already active for this session — wait for it to finish",
        )

    queue: asyncio.Queue = asyncio.Queue()

    async def _run() -> None:
        try:
            await agent.run_agent(engine, session_id, queue)
        finally:
            await queue.put(None)  # belt-and-braces: AgentRun.run also closes
            try:
                await asyncio.to_thread(_refresh_sandbox_status, request, session_id)
            except Exception:
                pass  # status refresh is best-effort decoration

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    async def event_stream():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


def _refresh_sandbox_status(request: Request, session_id: str) -> None:
    """Best-effort sync of the session's sandbox_status after activity."""
    manager = _require_manager(request)
    snapshot = manager.status(session_id)
    agent_db.update_session(
        request.app.state.engine,
        session_id,
        sandbox_status="running" if snapshot.get("running") else "stopped",
        sandbox_container_id=snapshot.get("container_id"),
    )


# ---- sandbox observability ----------------------------------------------


@router.get(
    "/sessions/{session_id}/sandbox",
    response_model=SandboxStatus,
    summary="Sandbox container status and resource usage",
)
def sandbox_status(session_id: str, request: Request) -> SandboxStatus:
    _require_session(request, session_id)
    manager = _require_manager(request)
    return SandboxStatus(**manager.status(session_id))


@router.post(
    "/sessions/{session_id}/sandbox/reset",
    response_model=SandboxStatus,
    summary="Reset the sandbox (fresh container, empty workspace)",
)
def reset_sandbox(session_id: str, request: Request) -> SandboxStatus:
    engine = request.app.state.engine
    _require_session(request, session_id)
    manager = _require_manager(request)
    agent = _require_agent_module(request)
    if agent.runs.is_active(session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is active for this session — wait for it to finish",
        )
    container = manager.reset_sandbox(session_id)
    agent_db.add_event(engine, session_id, "sandbox", {"status": "reset"})
    agent_db.update_session(
        engine,
        session_id,
        sandbox_status="running",
        sandbox_container_id=container.id,
    )
    return SandboxStatus(**manager.status(session_id))


@router.get(
    "/sessions/{session_id}/sandbox/logs",
    summary="Recent sandbox docker logs (the tailed activity.log)",
)
def get_sandbox_logs(
    session_id: str,
    request: Request,
    tail: int = Query(default=200, ge=1, le=5000),
) -> dict:
    _require_session(request, session_id)
    manager = _require_manager(request)
    return {"logs": manager.get_logs(session_id, tail)}


@router.get(
    "/sessions/{session_id}/sandbox/logs/stream",
    summary="Live sandbox docker logs over SSE",
)
def stream_sandbox_logs(
    session_id: str,
    request: Request,
    tail: int = Query(default=100, ge=0, le=5000),
) -> StreamingResponse:
    _require_session(request, session_id)
    manager = _require_manager(request)

    def log_lines():
        try:
            for chunk in manager.stream_logs(session_id, tail):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except RuntimeError as error:
            yield f"data: {json.dumps({'error': str(error)})}\n\n"

    return StreamingResponse(
        log_lines(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


@router.get(
    "/sessions/{session_id}/sandbox/files",
    response_model=list[SandboxFileEntry],
    summary="List one directory of the sandbox workspace",
)
def list_sandbox_files(
    session_id: str,
    request: Request,
    path: str = Query(default="/workspace"),
) -> list[SandboxFileEntry]:
    _require_session(request, session_id)
    manager = _require_manager(request)
    try:
        entries = manager.list_files(session_id, path)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return [SandboxFileEntry(**entry) for entry in entries]


@router.get(
    "/sessions/{session_id}/sandbox/files/content",
    response_model=SandboxFileContent,
    summary="Read one sandbox workspace file (text, size-capped)",
)
def read_sandbox_file(
    session_id: str,
    request: Request,
    path: str = Query(min_length=1),
) -> SandboxFileContent:
    _require_session(request, session_id)
    manager = _require_manager(request)
    try:
        content = manager.read_file(session_id, path)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{path}' not found in the sandbox workspace",
        )
    return SandboxFileContent(**content)
