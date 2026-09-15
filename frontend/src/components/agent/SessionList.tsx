import type { AgentSession } from "../../api"

export function SessionList({
  sessions,
  activeId,
  runningId,
  onSelect,
  onDelete,
  onNew,
}: {
  sessions: AgentSession[]
  activeId: string | null
  runningId: string | null
  onSelect: (sessionId: string) => void
  onDelete: (sessionId: string) => void
  onNew: () => void
}) {
  return (
    <div className="session-list card">
      <button
        className="btn btn-primary session-new"
        onClick={onNew}
        disabled={runningId !== null}
        type="button"
      >
        + New chat
      </button>
      {sessions.length === 0 ? (
        <p className="muted small session-empty">No chats yet.</p>
      ) : (
        <ul className="session-items">
          {sessions.map((session) => (
            <li
              key={session.id}
              className={`session-item ${session.id === activeId ? "session-active" : ""}`}
            >
              <button
                className="session-button"
                onClick={() => onSelect(session.id)}
                type="button"
                title={session.title}
              >
                <span className="session-title">
                  {session.id === runningId && (
                    <span className="session-spinner" aria-label="running" />
                  )}
                  {session.title}
                </span>
              </button>
              <button
                className="session-delete"
                onClick={() => onDelete(session.id)}
                disabled={session.id === runningId}
                title="Delete chat"
                type="button"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
