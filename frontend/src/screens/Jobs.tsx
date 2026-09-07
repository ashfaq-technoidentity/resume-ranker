import { useState } from "react"
import { api, type StoredJob } from "../api"
import { Chips } from "../components/Chips"
import { ErrorBanner } from "../components/ErrorBanner"
import { TagInput } from "../components/TagInput"

interface JobsProps {
  jobs: StoredJob[]
  onJobsChanged: () => void
}

interface JobFormState {
  job_id: string
  description: string
  posted_date: string
  job_skills: string[]
  job_responsibilities: string[]
}

const EMPTY_FORM: JobFormState = {
  job_id: "",
  description: "",
  posted_date: new Date().toISOString().slice(0, 10),
  job_skills: [],
  job_responsibilities: [],
}

export function Jobs({ jobs, onJobsChanged }: JobsProps) {
  const [editing, setEditing] = useState<StoredJob | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<JobFormState>(EMPTY_FORM)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const startCreate = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setCreating(true)
    setError("")
  }

  const startEdit = (job: StoredJob) => {
    setCreating(false)
    setEditing(job)
    setForm({
      job_id: job.job_id,
      description: job.description,
      posted_date: job.posted_date,
      job_skills: [...job.job_skills],
      job_responsibilities: [...job.job_responsibilities],
    })
    setError("")
  }

  const closeForm = () => {
    setCreating(false)
    setEditing(null)
  }

  const save = async () => {
    setBusy(true)
    setError("")
    try {
      if (editing) {
        await api.updateJob(editing.job_id, {
          description: form.description,
          posted_date: form.posted_date,
          job_skills: form.job_skills,
          job_responsibilities: form.job_responsibilities,
        })
      } else {
        await api.createJob(form)
      }
      closeForm()
      onJobsChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (job: StoredJob) => {
    if (!window.confirm(`Delete job '${job.job_id}'? Stored ranking scores are kept.`))
      return
    setBusy(true)
    setError("")
    try {
      await api.deleteJob(job.job_id)
      onJobsChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <h1>
          Jobs <span className="muted">({jobs.length})</span>
        </h1>
        <button className="btn btn-primary" onClick={startCreate}>
          New job
        </button>
      </div>

      {error && <ErrorBanner message={error} />}

      {(creating || editing) && (
        <form
          className="card form"
          onSubmit={(event) => {
            event.preventDefault()
            void save()
          }}
        >
          <h2>{editing ? `Edit ${editing.job_id}` : "New job"}</h2>
          <label>
            Job ID
            <input
              value={form.job_id}
              onChange={(event) => setForm({ ...form, job_id: event.target.value })}
              disabled={!!editing}
              placeholder="e.g. J-BACKEND-1"
              required
              maxLength={255}
            />
          </label>
          <label>
            Description
            <textarea
              value={form.description}
              onChange={(event) =>
                setForm({ ...form, description: event.target.value })
              }
              rows={4}
              required
              placeholder="Paste the full job description"
            />
          </label>
          <label>
            Posted date
            <input
              type="date"
              value={form.posted_date}
              onChange={(event) =>
                setForm({ ...form, posted_date: event.target.value })
              }
            />
          </label>
          <label>
            Skills
            <TagInput
              value={form.job_skills}
              onChange={(job_skills) => setForm({ ...form, job_skills })}
              placeholder="Type a skill and press Enter"
            />
          </label>
          <label>
            Responsibilities
            <TagInput
              value={form.job_responsibilities}
              onChange={(job_responsibilities) =>
                setForm({ ...form, job_responsibilities })
              }
              placeholder="Type a responsibility and press Enter"
            />
          </label>
          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {editing ? "Save changes" : "Create job"}
            </button>
            <button type="button" className="btn" onClick={closeForm} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {jobs.length === 0 && !creating && (
        <div className="card empty-state">
          No jobs yet. Create one to rank resumes against its skills and
          responsibilities.
        </div>
      )}

      {jobs.map((job) => {
        const rankable =
          job.job_skills.length > 0 || job.job_responsibilities.length > 0
        return (
          <article className="card job" key={job.job_id}>
            <header>
              <div>
                <h3>{job.job_id}</h3>
                <div className="muted small">Posted {job.posted_date}</div>
              </div>
              <div className="row-actions">
                <button className="btn" onClick={() => startEdit(job)}>
                  Edit
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => void remove(job)}
                  disabled={busy}
                >
                  Delete
                </button>
              </div>
            </header>
            <p className="description">{job.description}</p>
            {job.job_skills.length > 0 && (
              <div className="chip-group">
                <span className="chip-label">Skills</span>
                <Chips items={job.job_skills} tone="accent" />
              </div>
            )}
            {job.job_responsibilities.length > 0 && (
              <div className="chip-group">
                <span className="chip-label">Responsibilities</span>
                <Chips items={job.job_responsibilities} />
              </div>
            )}
            {!rankable && (
              <div className="warn-note">
                No skills or responsibilities yet — add them to make this job
                rankable.
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
