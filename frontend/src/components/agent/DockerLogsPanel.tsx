import { useEffect, useRef, useState } from "react"
import { agentApi } from "../../api"
import { sandboxLogsStreamUrl } from "../../sse"

const MAX_LINES = 2000

// Live view of the sandbox's `docker logs` (the container tails
// /workspace/activity.log, so every install/run shows up here).

export function DockerLogsPanel({
  sessionId,
  resetKey,
}: {
  sessionId: string
  resetKey: number
}) {
  const [lines, setLines] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [notice, setNotice] = useState("")
  const consoleRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    let cancelled = false
    setLines([])
    setNotice("")
    setConnected(false)

    agentApi
      .sandboxLogs(sessionId)
      .then((result) => {
        if (cancelled) return
        setLines(result.logs ? result.logs.split("\n").slice(-MAX_LINES) : [])
      })
      .catch((err: unknown) => {
        if (!cancelled) setNotice(err instanceof Error ? err.message : String(err))
      })

    const source = new EventSource(sandboxLogsStreamUrl(sessionId))
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    source.onmessage = (message) => {
      try {
        const payload = JSON.parse(message.data) as {
          chunk?: string
          error?: string
        }
        if (payload.error) {
          setNotice(payload.error)
          source.close()
          setConnected(false)
          return
        }
        if (payload.chunk) {
          setLines((prev) =>
            [...prev, ...payload.chunk!.split("\n")].slice(-MAX_LINES),
          )
        }
      } catch {
        // ignore malformed frames
      }
    }
    return () => {
      cancelled = true
      source.close()
    }
  }, [sessionId, resetKey])

  useEffect(() => {
    if (consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight
    }
  }, [lines])

  return (
    <div className="logs-panel">
      <div className="logs-toolbar">
        <span className={`dot ${connected ? "dot-ok" : "dot-off"}`} />
        <span className="muted small">
          {connected ? "streaming docker logs" : "not streaming"}
        </span>
      </div>
      {notice && <p className="muted small">{notice}</p>}
      <pre className="console" ref={consoleRef}>
        {lines.length ? lines.join("\n") : "(no logs yet — ask the assistant something)"}
      </pre>
    </div>
  )
}
