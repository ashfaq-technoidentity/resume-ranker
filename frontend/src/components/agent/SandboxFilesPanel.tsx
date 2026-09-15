import { useCallback, useEffect, useState } from "react"
import { agentApi, type SandboxFileContent, type SandboxFileEntry } from "../../api"
import { Icon } from "./Icon"

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`
}

function formatTime(mtime: number | null): string {
  if (!mtime) return ""
  return new Intl.DateTimeFormat("en", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(mtime * 1000)
}

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
  const breadcrumb = [
    <button
      key="root"
      className="crumb"
      type="button"
      onClick={() => {
        setPath("/workspace")
        load("/workspace")
      }}
    >
      workspace
    </button>,
    ...segments.slice(1).map((segment, index) => {
      const prefix = "/" + segments.slice(0, index + 2).join("/")
      return (
        <span key={prefix}>
          <span className="crumb-separator">/</span>
          <button
            className="crumb"
            type="button"
            onClick={() => {
              setPath(prefix)
              load(prefix)
            }}
          >
            {segment}
          </button>
        </span>
      )
    }),
  ]

  return (
    <div className="files-panel">
      <div className="logs-toolbar">
        <span className="crumbs">
          <Icon name="folder" size={14} />
          {breadcrumb}
        </span>
        <button
          className="btn btn-small btn-icon"
          type="button"
          disabled={busy}
          onClick={() => load(path)}
          title="Refresh"
        >
          <Icon name="refresh" size={14} />
        </button>
      </div>
      {error && <p className="muted small error-text">{error}</p>}
      {entries === null && !error && (
        <p className="muted small">No sandbox files.</p>
      )}
      {entries !== null && (
        <ul className="filetree">
          {entries.map((entry) => (
            <li key={entry.path}>
              <button
                className="filetree-row"
                type="button"
                onClick={() =>
                  entry.is_dir
                    ? (setPath(entry.path), load(entry.path))
                    : openFile(entry)
                }
              >
                <span className="filetree-icon" aria-hidden>
                  <Icon name={entry.is_dir ? "folder" : "file"} size={14} />
                </span>
                <span className="filetree-name">{entry.name}</span>
                <span className="muted small filetree-meta">
                  {entry.is_dir ? "" : formatSize(entry.size)}
                  {entry.mtime && !entry.is_dir ? ` · ${formatTime(entry.mtime)}` : ""}
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
            <span className="muted small file-path">{file.path}</span>
            {file.truncated && <span className="muted small">(truncated)</span>}
            <button
              className="btn btn-small"
              type="button"
              onClick={() => setFile(null)}
            >
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
