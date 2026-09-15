import { useCallback, useEffect, useState } from "react"
import { agentApi, type SandboxFileContent, type SandboxFileEntry } from "../../api"

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`
}

// Browser for the sandbox's /workspace: scripts the agent wrote, results it
// saved, and activity.log (the same file the docker-logs panel streams).

export function SandboxFilesPanel({
  sessionId,
  resetKey,
}: {
  sessionId: string
  resetKey: number
}) {
  const [path, setPath] = useState("/workspace")
  const [entries, setEntries] = useState<SandboxFileEntry[] | null>(null)
  const [file, setFile] = useState<SandboxFileContent | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const load = useCallback(
    (dir: string) => {
      setBusy(true)
      setError("")
      setFile(null)
      agentApi
        .listSandboxFiles(sessionId, dir)
        .then(setEntries)
        .catch((err: unknown) => {
          setEntries(null)
          setError(err instanceof Error ? err.message : String(err))
        })
        .finally(() => setBusy(false))
    },
    [sessionId],
  )

  useEffect(() => {
    setPath("/workspace")
    load("/workspace")
  }, [sessionId, resetKey, load])

  const openFile = (entry: SandboxFileEntry) => {
    setError("")
    setBusy(true)
    agentApi
      .readSandboxFile(sessionId, entry.path)
      .then(setFile)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      )
      .finally(() => setBusy(false))
  }

  const segments = path.split("/").filter(Boolean)
  const breadcrumb = ["/", ...segments.map((segment, index) => (
    <span key={`${segments.slice(0, index + 1).join("/")}`}>
      <button
        className="crumb"
        type="button"
        onClick={() => {
          const next = `/${segments.slice(0, index + 1).join("/")}`
          setPath(next)
          load(next)
        }}
      >
        {segment}
      </button>
      {index < segments.length - 1 ? "/" : ""}
    </span>
  ))]

  return (
    <div className="files-panel">
      <div className="logs-toolbar">
        <span className="crumbs">{breadcrumb}</span>
        <button
          className="btn btn-small"
          type="button"
          disabled={busy}
          onClick={() => load(path)}
        >
          Refresh
        </button>
      </div>
      {error && <p className="muted small">{error}</p>}
      {entries === null && !error && <p className="muted small">No sandbox files.</p>}
      {entries !== null && (
        <ul className="filetree">
          {entries.map((entry) => (
            <li key={entry.path}>
              <button
                className="filetree-row"
                type="button"
                onClick={() =>
                  entry.is_dir ? (setPath(entry.path), load(entry.path)) : openFile(entry)
                }
              >
                <span aria-hidden>{entry.is_dir ? "📁" : "📄"}</span>
                <span className="filetree-name">{entry.name}</span>
                <span className="muted small">
                  {entry.is_dir ? "" : formatSize(entry.size)}
                </span>
              </button>
            </li>
          ))}
          {entries.length === 0 && (
            <li className="muted small filetree-empty">(empty directory)</li>
          )}
        </ul>
      )}
      {file && (
        <div className="file-viewer">
          <div className="logs-toolbar">
            <span className="muted small">
              {file.path}
              {file.truncated ? " (truncated)" : ""}
            </span>
            <button className="btn btn-small" type="button" onClick={() => setFile(null)}>
              Close
            </button>
          </div>
          {file.binary ? (
            <p className="muted small">Binary file — download it from the sandbox.</p>
          ) : (
            <pre className="console">{file.content || "(empty file)"}</pre>
          )}
        </div>
      )}
    </div>
  )
}
