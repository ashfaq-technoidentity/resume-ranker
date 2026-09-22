import { useState, type FormEvent } from "react"
import { api, type RankResult, type StoredJob } from "../api"
import { Chips } from "../components/Chips"
import { ErrorBanner } from "../components/ErrorBanner"
import { ScoreBar } from "../components/ScoreBar"

interface RankProps {
  jobs: StoredJob[]
  onSwitchToBatch?: () => void
}

export function Rank({ jobs, onSwitchToBatch }: RankProps) {
  const [jobId, setJobId] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<RankResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!file || !jobId) return
    setBusy(true)
    setError("")
    setResult(null)
    try {
      setResult(await api.rankResume(file, jobId))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!jobs.length) {
    return (
      <div className="card empty-state">
        No jobs stored yet. Create a job on the <strong>Jobs</strong> tab first —
        ranking compares a resume against a job's skills and responsibilities.
      </div>
    )
  }

  const selected = jobs.find((job) => job.job_id === jobId)
  const rankable =
    !!selected &&
    (selected.job_skills.length > 0 || selected.job_responsibilities.length > 0)

  return (
    <div className="stack">
      <form className="card form" onSubmit={submit}>
        <h2>Rank a resume</h2>
        <label>
          Job
          <select
            value={jobId}
            onChange={(event) => setJobId(event.target.value)}
            required
          >
            <option value="" disabled>
              Select a job…
            </option>
            {jobs.map((job) => (
              <option key={job.job_id} value={job.job_id}>
                {job.job_id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Resume file (PDF or DOCX)
          <input
            type="file"
            accept=".pdf,.docx"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
        </label>
        {selected && !rankable && (
          <div className="warn-note">
            This job has no skills or responsibilities, so ranking will be
            rejected. Add them on the Jobs tab.
          </div>
        )}
        <div className="form-actions">
          <button
            className="btn btn-primary"
            type="submit"
            disabled={busy || !file || !jobId}
          >
            {busy ? "Ranking…" : "Rank resume"}
          </button>
          {onSwitchToBatch && (
            <button
              className="btn btn-secondary"
              type="button"
              onClick={onSwitchToBatch}
              title="Upload multiple resumes at once"
            >
              Batch upload multiple…
            </button>
          )}
        </div>
        <p className="muted small">
          The resume is parsed, stored, and scored against the job's skills and
          responsibilities. Re-ranking the same file updates its stored scores.
        </p>
      </form>

      {error && <ErrorBanner message={error} />}

      {result && (
        <article className="card">
          <header className="result-head">
            <div>
              <h2>{result.name || "Unknown candidate"}</h2>
              <div className="muted small">
                {[result.email, result.file_name].filter(Boolean).join(" · ")}
              </div>
            </div>
            <div className="score-badge">
              {(result.average_similarity * 100).toFixed(1)}% match
            </div>
          </header>
          <div className="chip-group">
            <span className="chip-label">Skills</span>
            <Chips items={result.skills} tone="accent" />
          </div>
          {result.total_experience != null && (
            <p className="muted">{result.total_experience} years of experience</p>
          )}
          <ScoreBar label="Skills similarity" value={result.skills_similarity} />
          <ScoreBar
            label="Experience similarity"
            value={result.experience_similarity}
          />
          <ScoreBar label="Average" value={result.average_similarity} />
          <p className="muted small">
            Embedding model: {result.model} · resume #{result.resume_id}
          </p>
        </article>
      )}
    </div>
  )
}
