import { useEffect, useState } from "react"
import { agentApi, type SandboxStatus } from "../../api"
import { DockerLogsPanel } from "./DockerLogsPanel"
import { SandboxFilesPanel } from "./SandboxFilesPanel"
import { Icon } from "./Icon"

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
            <div className="drawer-meta">
              {status?.image && (
                <span className="chip" title="Image">{status.image}</span>
              )}
              {status?.mem_usage && (
                <span className="chip" title="Memory">
                  <Icon name="memory" size={12} /> {status.mem_usage}
                </span>
              )}
              {status?.cpu_percent != null && (
                <span className="chip" title="CPU">
                  <Icon name="cpu" size={12} /> {status.cpu_percent}%
                </span>
              )}
            </div>
          </div>
        </div>
        <button
          className="btn btn-danger btn-small btn-icon"
          type="button"
          disabled={running}
          onClick={onReset}
          title={running ? "Wait for the run to finish" : "Fresh container, empty workspace"}
        >
          <Icon name="refresh" size={14} />
        </button>
      </div>
      <div className="drawer-tabs">
        <button
          className={`tab ${tab === "logs" ? "tab-active" : ""}`}
          onClick={() => setTab("logs")}
          type="button"
        >
          <Icon name="terminal" size={13} />
          Docker logs
        </button>
        <button
          className={`tab ${tab === "files" ? "tab-active" : ""}`}
          onClick={() => setTab("files")}
          type="button"
        >
          <Icon name="folder" size={13} />
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
