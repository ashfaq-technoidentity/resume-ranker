import type { AgentSession } from "../../api"
import { Icon } from "./Icon"
import { formatAbsolute, formatRelative } from "./time"

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
        <Icon name="plus" size={16} />
        New chat
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
                  <span className="session-name">{session.title}</span>
                </span>
                <span
                  className="session-meta"
                  title={formatAbsolute(session.created_at)}
                >
                  {formatRelative(session.created_at)}
                </span>
              </button>
              <button
                className="session-delete"
                onClick={() => onDelete(session.id)}
                disabled={session.id === runningId}
                title="Delete chat"
                type="button"
              >
                <Icon name="trash" size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
