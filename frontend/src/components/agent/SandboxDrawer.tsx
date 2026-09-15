import { useEffect, useState } from "react"
import { agentApi, type SandboxStatus } from "../../api"
import { DockerLogsPanel } from "./DockerLogsPanel"
import { SandboxFilesPanel } from "./SandboxFilesPanel"

// Right-hand drawer: sandbox status + reset, docker logs, and the workspace
// file browser. Panels re-initialise whenever the sandbox is reset
// (resetKey changes).

export function SandboxDrawer({
  sessionId,
  resetKey,
  running,
  onReset,
}: {
  sessionId: string
  resetKey: number
  running: boolean
  onReset: () => void
}) {
  const [tab, setTab] = useState<"logs" | "files">("logs")
  const [status, setStatus] = useState<SandboxStatus | null>(null)

  useEffect(() => {
    agentApi
      .sandboxStatus(sessionId)
      .then(setStatus)
      .catch(() => setStatus(null))
  }, [sessionId, resetKey])

  return (
    <aside className="drawer card">
      <div className="drawer-head">
        <div className="drawer-status">
          <span className={`dot ${status?.running ? "dot-ok" : "dot-off"}`} />
          <div>
            <div className="drawer-title">
              {status?.running ? "Sandbox running" : "Sandbox stopped"}
            </div>
            <div className="muted small">
              {status?.image ?? "—"}
              {status?.mem_usage ? ` · ${status.mem_usage}` : ""}
              {status?.cpu_percent != null ? ` · ${status.cpu_percent}% cpu` : ""}
            </div>
          </div>
        </div>
        <button
          className="btn btn-danger btn-small"
          type="button"
          disabled={running}
          onClick={onReset}
          title={running ? "Wait for the run to finish" : "Fresh container, empty workspace"}
        >
          Reset sandbox
        </button>
      </div>
      <div className="drawer-tabs">
        <button
          className={`tab ${tab === "logs" ? "tab-active" : ""}`}
          onClick={() => setTab("logs")}
          type="button"
        >
          Docker logs
        </button>
        <button
          className={`tab ${tab === "files" ? "tab-active" : ""}`}
          onClick={() => setTab("files")}
          type="button"
        >
          Files
        </button>
      </div>
      {tab === "logs" ? (
        <DockerLogsPanel resetKey={resetKey} sessionId={sessionId} />
      ) : (
        <SandboxFilesPanel resetKey={resetKey} sessionId={sessionId} />
      )}
    </aside>
  )
}
