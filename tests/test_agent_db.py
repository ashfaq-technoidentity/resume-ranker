import pytest

import agent_db
import jobs_db


@pytest.fixture()
def engine(tmp_path):
    engine = jobs_db.get_engine(f"sqlite:///{tmp_path}/agent.db")
    agent_db.init_db(engine)
    return engine


def test_create_session_defaults(engine):
    session = agent_db.create_session(engine)

    assert session.id
    assert len(session.id) == 32
    assert session.title == agent_db.DEFAULT_TITLE
    assert session.sandbox_status == "creating"
    assert session.created_at is not None


def test_list_sessions_returns_created_sessions(engine):
    first = agent_db.create_session(engine)
    second = agent_db.create_session(engine)

    listed = agent_db.list_sessions(engine)

    assert {session.id for session in listed} == {first.id, second.id}


def test_get_session_unknown_returns_none(engine):
    assert agent_db.get_session(engine, "missing") is None


def test_update_session_changes_fields(engine):
    session = agent_db.create_session(engine)

    updated = agent_db.update_session(
        engine, session.id, title="python candidates", sandbox_status="running"
    )

    assert updated is not None
    assert updated.title == "python candidates"
    assert updated.sandbox_status == "running"


def test_update_session_unknown_returns_none(engine):
    assert agent_db.update_session(engine, "missing", title="x") is None


def test_add_and_list_messages_chronological_with_limit(engine):
    session = agent_db.create_session(engine)
    for index in range(5):
        agent_db.add_message(
            engine, session.id, "user" if index % 2 == 0 else "assistant", f"m{index}"
        )

    messages = agent_db.list_messages(engine, session.id)

    assert [message.content for message in messages] == [
        "m0",
        "m1",
        "m2",
        "m3",
        "m4",
    ]
    last_three = agent_db.list_messages(engine, session.id, limit=3)
    assert [message.content for message in last_three] == ["m2", "m3", "m4"]


def test_add_event_assigns_per_session_sequences(engine):
    first = agent_db.create_session(engine)
    second = agent_db.create_session(engine)

    agent_db.add_event(engine, first.id, "run_started", {"run_id": "a"})
    agent_db.add_event(engine, second.id, "run_started", {"run_id": "b"})
    agent_db.add_event(engine, first.id, "thought", {"content": "hi"})

    first_events = agent_db.list_events(engine, first.id)
    assert [event.seq for event in first_events] == [1, 2]
    assert [event.type for event in first_events] == ["run_started", "thought"]
    assert first_events[1].data == {"content": "hi"}

    second_events = agent_db.list_events(engine, second.id)
    assert [event.seq for event in second_events] == [1]


def test_list_events_after_seq(engine):
    session = agent_db.create_session(engine)
    for index in range(4):
        agent_db.add_event(engine, session.id, "thought", {"n": index})

    tail = agent_db.list_events(engine, session.id, after_seq=2)

    assert [event.seq for event in tail] == [3, 4]


def test_delete_session_cascades_messages_and_events(engine):
    session = agent_db.create_session(engine)
    agent_db.add_message(engine, session.id, "user", "hello")
    agent_db.add_event(engine, session.id, "run_started", {})

    assert agent_db.delete_session(engine, session.id)

    assert agent_db.get_session(engine, session.id) is None
    assert agent_db.list_messages(engine, session.id) == []
    assert agent_db.list_events(engine, session.id) == []


def test_delete_session_unknown_returns_false(engine):
    assert not agent_db.delete_session(engine, "missing")


def test_list_session_ids(engine):
    session = agent_db.create_session(engine)

    assert agent_db.list_session_ids(engine) == {session.id}
