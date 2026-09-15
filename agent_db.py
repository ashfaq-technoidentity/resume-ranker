"""AI-assistant session storage.

Backed by SQLAlchemy Core (like jobs_db) so the same code runs on SQLite
(default) and PostgreSQL (via DATABASE_URL, used by the Docker deployment).
Each session owns a Docker sandbox; chat messages and the append-only agent
event trace (thoughts, actions, observations, answers) are persisted so the
frontend can replay a session after a reload.
"""

import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    delete,
    func,
    insert,
    select,
    update,
)

from models import (
    AgentEventRecord,
    AgentMessageRecord,
    AgentSessionRecord,
)

metadata = MetaData()

agent_sessions = Table(
    "agent_sessions",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("title", String(80), nullable=False),
    Column("sandbox_status", String(16), nullable=False),
    Column("sandbox_container_id", String(64)),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)

agent_messages = Table(
    "agent_messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(32), nullable=False, index=True),
    Column("run_id", String(32)),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

agent_events = Table(
    "agent_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(32), nullable=False, index=True),
    Column("run_id", String(32)),
    Column("seq", Integer, nullable=False),
    Column("type", String(32), nullable=False),
    Column("data", JSON, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

DEFAULT_TITLE = "New chat"


def init_db(engine: Engine) -> None:
    metadata.create_all(engine)


def _touch_session(conn, session_id: str) -> None:
    conn.execute(
        update(agent_sessions)
        .where(agent_sessions.c.id == session_id)
        .values(updated_at=func.now())
    )


def create_session(
    engine: Engine,
    *,
    session_id: str | None = None,
    title: str = DEFAULT_TITLE,
    sandbox_status: str = "creating",
) -> AgentSessionRecord:
    """Create a chat session row; returns the stored record."""
    session_id = session_id or uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(
            insert(agent_sessions).values(
                id=session_id, title=title, sandbox_status=sandbox_status
            )
        )
        row = (
            conn.execute(
                select(agent_sessions).where(agent_sessions.c.id == session_id)
            )
            .mappings()
            .one()
        )
    return AgentSessionRecord(**row)


def list_sessions(engine: Engine) -> list[AgentSessionRecord]:
    stmt = select(agent_sessions).order_by(
        agent_sessions.c.updated_at.desc(), agent_sessions.c.id
    )
    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return [AgentSessionRecord(**row) for row in rows]


def get_session(engine: Engine, session_id: str) -> AgentSessionRecord | None:
    stmt = select(agent_sessions).where(agent_sessions.c.id == session_id)
    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()
    return AgentSessionRecord(**row) if row else None


def list_session_ids(engine: Engine) -> set[str]:
    """All session ids (used to sweep orphaned sandbox containers/volumes)."""
    with engine.connect() as conn:
        rows = conn.execute(select(agent_sessions.c.id)).all()
    return {row[0] for row in rows}


def update_session(
    engine: Engine,
    session_id: str,
    *,
    title: str | None = None,
    sandbox_status: str | None = None,
    sandbox_container_id: str | None = None,
) -> AgentSessionRecord | None:
    """Update the given session fields; None when the session doesn't exist."""
    values: dict = {"updated_at": func.now()}
    if title is not None:
        values["title"] = title
    if sandbox_status is not None:
        values["sandbox_status"] = sandbox_status
    if sandbox_container_id is not None:
        values["sandbox_container_id"] = sandbox_container_id
    with engine.begin() as conn:
        result = conn.execute(
            update(agent_sessions)
            .where(agent_sessions.c.id == session_id)
            .values(values)
        )
        if result.rowcount == 0:
            return None
        row = (
            conn.execute(
                select(agent_sessions).where(agent_sessions.c.id == session_id)
            )
            .mappings()
            .first()
        )
    return AgentSessionRecord(**row) if row else None


def delete_session(engine: Engine, session_id: str) -> bool:
    """Remove a session and its messages/events; True when a row was deleted."""
    with engine.begin() as conn:
        conn.execute(
            delete(agent_messages).where(agent_messages.c.session_id == session_id)
        )
        conn.execute(
            delete(agent_events).where(agent_events.c.session_id == session_id)
        )
        deleted = conn.execute(
            delete(agent_sessions).where(agent_sessions.c.id == session_id)
        ).rowcount
    return deleted > 0


def add_message(
    engine: Engine,
    session_id: str,
    role: str,
    content: str,
    run_id: str | None = None,
) -> AgentMessageRecord:
    """Store one chat message (user question or assistant final answer)."""
    with engine.begin() as conn:
        result = conn.execute(
            insert(agent_messages).values(
                session_id=session_id, run_id=run_id, role=role, content=content
            )
        )
        _touch_session(conn, session_id)
        row = (
            conn.execute(
                select(agent_messages).where(
                    agent_messages.c.id == result.inserted_primary_key[0]
                )
            )
            .mappings()
            .one()
        )
    return AgentMessageRecord(**row)


def list_messages(
    engine: Engine, session_id: str, limit: int | None = None
) -> list[AgentMessageRecord]:
    """A session's messages in chronological order.

    ``limit`` keeps only the most recent N messages (LLM context window)
    while still returning them oldest-first.
    """
    stmt = select(agent_messages).where(
        agent_messages.c.session_id == session_id
    )
    with engine.connect() as conn:
        if limit is not None:
            recent = conn.execute(
                stmt.order_by(agent_messages.c.id.desc()).limit(limit)
            ).mappings().all()
            rows = list(reversed(recent))
        else:
            rows = conn.execute(stmt.order_by(agent_messages.c.id)).mappings().all()
    return [AgentMessageRecord(**row) for row in rows]


def add_event(
    engine: Engine,
    session_id: str,
    event_type: str,
    data: dict,
    run_id: str | None = None,
) -> AgentEventRecord:
    """Append one agent trace event with the next per-session sequence number."""
    with engine.begin() as conn:
        seq = (
            conn.execute(
                select(func.coalesce(func.max(agent_events.c.seq), 0)).where(
                    agent_events.c.session_id == session_id
                )
            ).scalar()
            + 1
        )
        result = conn.execute(
            insert(agent_events).values(
                session_id=session_id,
                run_id=run_id,
                seq=seq,
                type=event_type,
                data=data,
            )
        )
        _touch_session(conn, session_id)
        row = (
            conn.execute(
                select(agent_events).where(
                    agent_events.c.id == result.inserted_primary_key[0]
                )
            )
            .mappings()
            .one()
        )
    return AgentEventRecord(**row)


def list_events(
    engine: Engine, session_id: str, after_seq: int = 0
) -> list[AgentEventRecord]:
    """A session's events in sequence order, optionally only those after ``seq``."""
    stmt = select(agent_events).where(
        agent_events.c.session_id == session_id,
        agent_events.c.seq > after_seq,
    ).order_by(agent_events.c.seq)
    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return [AgentEventRecord(**row) for row in rows]


if __name__ == "__main__":
    from jobs_db import get_engine

    engine = get_engine()
    init_db(engine)
    print(f"Agent tables ready in {engine.url}")
