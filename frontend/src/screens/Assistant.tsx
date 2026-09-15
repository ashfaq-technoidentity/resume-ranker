import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react"
import {
  agentApi,
  type AgentEvent,
  type AgentMessage,
  type AgentSession,
} from "../api"
import { ErrorBanner } from "../components/ErrorBanner"
import { Loading } from "../components/Loading"
import { streamAgentChat } from "../sse"
import { ActivitySteps } from "../components/agent/ActivitySteps"
import { ChatMessage } from "../components/agent/ChatMessage"
import { SandboxDrawer } from "../components/agent/SandboxDrawer"
import { SessionList } from "../components/agent/SessionList"
import { Icon } from "../components/agent/Icon"

type TranscriptItem =
  | { kind: "message"; message: AgentMessage }
  | { kind: "steps"; events: AgentEvent[] }

const SAMPLE_PROMPTS = [
  'Pick out candidates that have "python" in their resume',
  "Which candidates have 5+ years of experience with AWS?",
  "Compare the skill sets of the top-ranked candidates for J-1",
]

export function Assistant() {
  const [sessions, setSessions] = useState<AgentSession[] | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [replayEvents, setReplayEvents] = useState<AgentEvent[]>([])
  const [runEvents, setRunEvents] = useState<AgentEvent[]>([])
  const [running, setRunning] = useState(false)
  const [input, setInput] = useState("")
  const [error, setError] = useState("")
  const [drawerOpen, setDrawerOpen] = useState(true)
  const [resetKey, setResetKey] = useState(0)

  const activeIdRef = useRef<string | null>(null)
  const runEventsRef = useRef<AgentEvent[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const refreshSessions = useCallback(() => {
    agentApi
      .listSessions()
      .then(setSessions)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      )
  }, [])

  const selectSession = useCallback((sessionId: string) => {
    setActiveId(sessionId)
    activeIdRef.current = sessionId
    setMessages([])
    setReplayEvents([])
    setRunEvents([])
    runEventsRef.current = []
    setError("")
    agentApi
      .getSession(sessionId)
      .then((detail) => {
        if (activeIdRef.current !== sessionId) return
        setMessages(detail.messages)
        setReplayEvents(detail.events)
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      )
  }, [])

  useEffect(() => {
    refreshSessions()
  }, [refreshSessions])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages, runEvents])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [input])

  const newChat = () => {
    if (running) return
    setActiveId(null)
    activeIdRef.current = null
    setMessages([])
    setReplayEvents([])
    setRunEvents([])
    runEventsRef.current = []
    setError("")
    setInput("")
    textareaRef.current?.focus()
  }

  const deleteSession = async (sessionId: string) => {
    if (running && sessionId === activeId) return
    if (!window.confirm("Delete this chat and its sandbox?")) return
    try {
      await agentApi.deleteSession(sessionId)
      setSessions((prev) => (prev ?? []).filter((s) => s.id !== sessionId))
      if (activeId === sessionId) newChat()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const send = async () => {
    const content = input.trim()
    if (!content || running) return
    setError("")
    let sessionId = activeId
    if (!sessionId) {
      try {
        const session = await agentApi.createSession()
        setSessions((prev) => [session, ...(prev ?? [])])
        setActiveId(session.id)
        activeIdRef.current = session.id
        sessionId = session.id
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : String(err))
        return
      }
    }
    const runSession = sessionId
    setRunning(true)
    setInput("")
    setMessages((prev) => [
      ...prev,
      {
        id: -Date.now(),
        session_id: runSession,
        run_id: null,
        role: "user",
        content,
        created_at: new Date().toISOString(),
      },
    ])
    try {
      await streamAgentChat(runSession, content, (event) => {
        if (activeIdRef.current !== runSession) return
        runEventsRef.current = [...runEventsRef.current, event]
        setRunEvents(runEventsRef.current)
        const data = event.data ?? {}
        const answer = data.content
        if (event.type === "answer" && typeof answer === "string") {
          setMessages((prev) => [
            ...prev,
            {
              id: -(Date.now() + 1),
              session_id: runSession,
              run_id: event.run_id,
              role: "assistant",
              content: answer,
              created_at: new Date().toISOString(),
            },
          ])
        }
      })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
      // resync from the API — the run may have continued server-side
      if (activeIdRef.current === runSession) selectSession(runSession)
    } finally {
      if (activeIdRef.current === runSession) {
        setReplayEvents((prev) => [...prev, ...runEventsRef.current])
        setRunEvents([])
        runEventsRef.current = []
      }
      setRunning(false)
      refreshSessions()
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void send()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      void send()
    }
  }

  const resetSandbox = async () => {
    if (!activeId || running) return
    if (
      !window.confirm(
        "Reset the sandbox? The container is recreated and all installed packages and files are wiped.",
      )
    ) {
      return
    }
    try {
      await agentApi.resetSandbox(activeId)
      setResetKey((key) => key + 1)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const transcript = useMemo<TranscriptItem[]>(() => {
    const eventsByRun = new Map<string, AgentEvent[]>()
    for (const event of replayEvents) {
      if (!event.run_id) continue
      const list = eventsByRun.get(event.run_id) ?? []
      list.push(event)
      eventsByRun.set(event.run_id, list)
    }
    const items: TranscriptItem[] = []
    for (const message of messages) {
      if (message.role === "assistant" && message.run_id) {
        const events = eventsByRun.get(message.run_id)
        if (events?.length) items.push({ kind: "steps", events })
      }
      items.push({ kind: "message", message })
    }
    return items
  }, [messages, replayEvents])

  const runningId = running ? activeId : null
  const hasChat = activeId !== null || running

  return (
    <div className={`agent-layout ${drawerOpen && hasChat ? "" : "no-drawer"}`}>
      {sessions === null ? (
        <div className="session-list card">
          <Loading label="Loading sessions…" />
        </div>
      ) : (
        <SessionList
          activeId={activeId}
          onDelete={deleteSession}
          onNew={newChat}
          onSelect={selectSession}
          runningId={runningId}
          sessions={sessions}
        />
      )}

      <section className="chat card">
        {error && <ErrorBanner message={error} />}
        <div className="chat-scroll">
          {!hasChat && (
            <div className="chat-welcome">
              <div className="welcome-icon">
                <Icon name="sparkles" size={32} />
              </div>
              <h2>AI Assistant</h2>
              <p className="muted">
                Ask anything about your stored resumes. The assistant writes and
                runs Python in a sandboxed Docker container and can install
                packages it needs.
              </p>
              <div className="chat-samples">
                {SAMPLE_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    className="btn sample-prompt"
                    type="button"
                    onClick={() => {
                      setInput(prompt)
                      textareaRef.current?.focus()
                    }}
                  >
                    <Icon name="lightbulb" size={14} />
                    {prompt}
                  </button>
                ))}
              </div>
              <p className="muted small">
                Watch its steps, Docker logs, and workspace files in the side
                panel.
              </p>
            </div>
          )}
          {transcript.map((item, index) =>
            item.kind === "message" ? (
              <ChatMessage
                key={`m-${item.message.id}-${index}`}
                content={item.message.content}
                createdAt={item.message.created_at}
                role={item.message.role}
              />
            ) : (
              <ActivitySteps
                events={item.events}
                key={`s-${item.events[0]?.seq ?? index}`}
                running={false}
              />
            ),
          )}
          {running && <ActivitySteps events={runEvents} running />}
          <div ref={bottomRef} />
        </div>
        <form className="chat-composer" onSubmit={submit}>
          <textarea
            ref={textareaRef}
            disabled={running}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={
              running
                ? "The assistant is working…"
                : "Ask about your resumes…"
            }
            rows={1}
            value={input}
          />
          <div className="chat-composer-actions">
            {hasChat && (
              <button
                className="btn btn-small btn-icon"
                onClick={() => setDrawerOpen((open) => !open)}
                title={drawerOpen ? "Hide side panel" : "Show side panel"}
                type="button"
              >
                <Icon name="terminal" size={14} />
                {drawerOpen ? "Hide" : "Panel"}
              </button>
            )}
            <button
              className="btn btn-primary btn-icon"
              disabled={running || !input.trim()}
              title="Send message"
              type="submit"
            >
              <Icon name="send" size={16} />
              {running ? "Working…" : "Send"}
            </button>
          </div>
        </form>
        <div className="chat-hint muted small">
          Enter to send · Shift+Enter for a new line
        </div>
      </section>

      {hasChat && drawerOpen && activeId && (
        <SandboxDrawer
          onReset={resetSandbox}
          resetKey={resetKey}
          running={running}
          sessionId={activeId}
        />
      )}
    </div>
  )
}
