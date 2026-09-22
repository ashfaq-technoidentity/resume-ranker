import { useState, useRef, type FormEvent, type ChangeEvent, type DragEvent } from "react"
import { api, resumeFileUrl, type BatchResumeResponse, type StoredJob } from "../api"
import { Chips } from "../components/Chips"
import { ErrorBanner } from "../components/ErrorBanner"
import { ScoreBar } from "../components/ScoreBar"

interface BatchUploadProps {
  jobs: StoredJob[]
}

export function BatchUpload({ jobs }: BatchUploadProps) {
  const [selectedJobId, setSelectedJobId] = useState("")
  const [files, setFiles] = useState<File[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [result, setResult] = useState<BatchResumeResponse | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return
    const newFiles = Array.from(e.target.files)
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => `${f.name}-${f.size}`))
      const added = newFiles.filter((f) => !existing.has(`${f.name}-${f.size}`))
      return [...prev, ...added]
    })
    e.target.value = ""
  }

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    if (!e.dataTransfer.files) return
    const droppedFiles = Array.from(e.dataTransfer.files).filter((file) => {
      const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase()
      return ext === ".pdf" || ext === ".docx"
    })
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => `${f.name}-${f.size}`))
      const added = droppedFiles.filter((f) => !existing.has(`${f.name}-${f.size}`))
      return [...prev, ...added]
    })
  }

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const clearAllFiles = () => {
    setFiles([])
    setResult(null)
    setError("")
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!files.length) return

    setBusy(true)
    setError("")
    setResult(null)

    try {
      const response = await api.batchUploadResumes(files, selectedJobId || undefined)
      setResult(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const selectedJob = jobs.find((j) => j.job_id === selectedJobId)
  const rankable =
    !selectedJob ||
    selectedJob.job_skills.length > 0 ||
    selectedJob.job_responsibilities.length > 0

  return (
    <div className="stack">
      <form className="card form" onSubmit={submit}>
        <h2>Batch insert resumes</h2>
        <p className="muted">
          Upload multiple PDF or DOCX resumes. Files are parsed and stored in the database
          in parallel, with optional semantic scoring against a stored job.
        </p>

        <label>
          Assign to Job for Ranking (Optional)
          <select
            value={selectedJobId}
            onChange={(e) => setSelectedJobId(e.target.value)}
          >
            <option value="">None — Insert into database only</option>
            {jobs.map((job) => (
              <option key={job.job_id} value={job.job_id}>
                {job.job_id} ({job.description.slice(0, 50)}...)
              </option>
            ))}
          </select>
        </label>

        {selectedJob && !rankable && (
          <div className="warn-note">
            This job has no skills or responsibilities, so ranking will fail.
            Add them on the Jobs tab or select &quot;None&quot; to insert only.
          </div>
        )}

        <div
          className={`dropzone ${isDragging ? "dropzone-active" : ""}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              fileInputRef.current?.click()
            }
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.docx"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />
          <div className="dropzone-content">
            <svg
              className="dropzone-icon"
              width="36"
              height="36"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <div>
              <strong>Drag &amp; drop resume files here</strong>, or{" "}
              <span className="file-link">browse</span>
            </div>
            <div className="muted small">Supports .pdf and .docx files</div>
          </div>
        </div>

        {files.length > 0 && (
          <div className="file-preview-list">
            <div className="file-preview-header">
              <span>
                <strong>{files.length}</strong> {files.length === 1 ? "file" : "files"} selected
              </span>
              <button
                type="button"
                className="btn btn-sm"
                onClick={clearAllFiles}
                disabled={busy}
              >
                Clear all
              </button>
            </div>
            <div className="file-items-scroll">
              {files.map((file, i) => (
                <div key={`${file.name}-${file.size}-${i}`} className="file-item">
                  <div className="file-item-info">
                    <span className="file-item-name">{file.name}</span>
                    <span className="file-item-size muted small">
                      {formatFileSize(file.size)}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="file-item-remove"
                    onClick={() => removeFile(i)}
                    disabled={busy}
                    aria-label={`Remove ${file.name}`}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="form-actions">
          <button
            className="btn btn-primary"
            type="submit"
            disabled={busy || files.length === 0 || (!!selectedJob && !rankable)}
          >
            {busy
              ? `Processing ${files.length} ${files.length === 1 ? "resume" : "resumes"} in parallel…`
              : `Upload & Process ${files.length} ${files.length === 1 ? "Resume" : "Resumes"}`}
          </button>
        </div>
      </form>

      {error && <ErrorBanner message={error} />}

      {result && (
        <div className="stack">
          <div className="card batch-summary-card">
            <h3>Batch Processing Summary</h3>
            <div className="batch-stats">
              <div className="batch-stat-box">
                <span className="batch-stat-label">Total Files</span>
                <span className="batch-stat-value">{result.total}</span>
              </div>
              <div className="batch-stat-box">
                <span className="batch-stat-label">Succeeded</span>
                <span className="batch-stat-value text-success">
                  {result.succeeded}
                </span>
              </div>
              <div className="batch-stat-box">
                <span className="batch-stat-label">Failed</span>
                <span
                  className={`batch-stat-value ${result.failed > 0 ? "text-error" : ""}`}
                >
                  {result.failed}
                </span>
              </div>
              {result.items.some((it) => it.average_similarity != null) && (
                <div className="batch-stat-box">
                  <span className="batch-stat-label">Avg Match Score</span>
                  <span className="batch-stat-value">
                    {(
                      (result.items.reduce(
                        (acc, curr) => acc + (curr.average_similarity || 0),
                        0,
                      ) /
                        (result.items.filter((it) => it.average_similarity != null)
                          .length || 1)) *
                      100
                    ).toFixed(1)}
                    %
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="card table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Status</th>
                  <th>Candidate</th>
                  <th>File</th>
                  <th>Exp</th>
                  <th>Skills</th>
                  {result.items.some((it) => it.average_similarity != null) && (
                    <th>Match</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {result.items.map((item, index) => (
                  <tr key={`${item.file_name}-${index}`}>
                    <td className="num">{index + 1}</td>
                    <td>
                      {item.status === "success" ? (
                        <span className="status-pill status-pill-success">
                          Success
                        </span>
                      ) : (
                        <span
                          className="status-pill status-pill-error"
                          title={item.error || "Error"}
                        >
                          Failed
                        </span>
                      )}
                    </td>
                    <td>
                      <div>
                        <strong>{item.name || "Unknown Candidate"}</strong>
                      </div>
                      {item.email && (
                        <div className="muted small">{item.email}</div>
                      )}
                      {item.error && (
                        <div className="error-note small">{item.error}</div>
                      )}
                    </td>
                    <td>
                      {item.resume_id != null ? (
                        <a
                          href={resumeFileUrl(item.resume_id)}
                          target="_blank"
                          rel="noreferrer"
                          className="file-link"
                          title="Preview resume in new tab"
                        >
                          {item.file_name}
                        </a>
                      ) : (
                        item.file_name
                      )}
                    </td>
                    <td>
                      {item.total_experience != null
                        ? `${item.total_experience} yrs`
                        : "—"}
                    </td>
                    <td className="chip-cell">
                      <Chips items={item.skills} tone="accent" />
                    </td>
                    {result.items.some((it) => it.average_similarity != null) && (
                      <td>
                        {item.average_similarity != null ? (
                          <div style={{ minWidth: 160 }}>
                            <div className="score-badge" style={{ display: "inline-block", marginBottom: 6 }}>
                              {(item.average_similarity * 100).toFixed(1)}% match
                            </div>
                            <ScoreBar
                              label="Skills"
                              value={item.skills_similarity ?? 0}
                            />
                            <ScoreBar
                              label="Exp"
                              value={item.experience_similarity ?? 0}
                            />
                          </div>
                        ) : (
                          "—"
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
