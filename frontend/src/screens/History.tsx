import { useEffect, useState } from "react"
import { api, resumeFileUrl, type ScoreRecord, type StoredJob } from "../api"
import { ErrorBanner } from "../components/ErrorBanner"
import { Loading } from "../components/Loading"

interface HistoryProps {
  jobs: StoredJob[]
}

export function History({ jobs }: HistoryProps) {
  const [jobId, setJobId] = useState("")
  const [records, setRecords] = useState<ScoreRecord[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const onJobChange = (value: string) => {
    setJobId(value)
    setRecords(null)
    setError("")
    setBusy(value !== "")
  }

  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    api
      .jobScores(jobId)
      .then((scores) => {
        if (!cancelled) setRecords(scores)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => {
      cancelled = true
    }
  }, [jobId])

  if (!jobs.length) {
    return (
      <div className="card empty-state">
        No jobs stored yet — score history appears once you rank resumes
        against a job.
      </div>
    )
  }

  return (
    <div className="stack">
      <form className="card form" onSubmit={(event) => event.preventDefault()}>
        <h2>Score history</h2>
        <label>
          Job
          <select value={jobId} onChange={(event) => onJobChange(event.target.value)}>
            <option value="">Select a job…</option>
            {jobs.map((job) => (
              <option key={job.job_id} value={job.job_id}>
                {job.job_id}
              </option>
            ))}
          </select>
        </label>
        <p className="muted small">
          Every resume ranked against the selected job, best average similarity
          first. Re-ranking the same resume updates its row.
        </p>
      </form>

      {error && <ErrorBanner message={error} />}
      {busy && <Loading label="Loading scores…" />}

      {records &&
        (records.length ? (
          <div className="card table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Candidate</th>
                  <th>File</th>
                  <th>Exp (yrs)</th>
                  <th>Skills sim</th>
                  <th>Exp sim</th>
                  <th>Average</th>
                  <th>Model</th>
                  <th>Ranked</th>
                </tr>
              </thead>
              <tbody>
                {records.map((record, index) => (
                  <tr key={record.resume_id}>
                    <td className="num">{index + 1}</td>
                    <td>
                      <div>{record.name || `Resume #${record.resume_id}`}</div>
                      <div className="muted small">{record.email}</div>
                    </td>
                    <td>
                      {record.file_name ? (
                        <a
                          href={resumeFileUrl(record.resume_id)}
                          target="_blank"
                          rel="noopener noreferrer"
                          title="Open the resume in a new tab (DOCX files are converted to PDF)"
                        >
                          {record.file_name}
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{record.total_experience ?? "—"}</td>
                    <td className="num">
                      {(record.skills_similarity * 100).toFixed(1)}%
                    </td>
                    <td className="num">
                      {(record.experience_similarity * 100).toFixed(1)}%
                    </td>
                    <td className="num">
                      <span
                        className="mini-bar"
                        aria-hidden="true"
                      >
                        <span
                          className="mini-fill"
                          style={{
                            width: `${
                              Math.max(0, Math.min(1, record.average_similarity)) *
                              100
                            }%`,
                          }}
                        />
                      </span>
                      {(record.average_similarity * 100).toFixed(1)}%
                    </td>
                    <td className="muted small">{record.model}</td>
                    <td className="muted small">
                      {record.updated_at.replace("T", " ").replace("Z", "")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="card empty-state">
            No resumes ranked against this job yet.
          </div>
        ))}
    </div>
  )
}
