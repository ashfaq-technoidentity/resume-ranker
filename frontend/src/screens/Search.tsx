import { useState, type FormEvent } from "react"
import { api, type SearchResult } from "../api"
import { Chips } from "../components/Chips"
import { ErrorBanner } from "../components/ErrorBanner"
import { TagInput } from "../components/TagInput"

export function Search() {
  const [keywords, setKeywords] = useState<string[]>([])
  const [results, setResults] = useState<SearchResult[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!keywords.length) return
    setBusy(true)
    setError("")
    try {
      setResults(await api.searchResumes(keywords))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <form className="card form" onSubmit={submit}>
        <h2>Search stored resumes</h2>
        <label>
          Keywords
          <TagInput
            value={keywords}
            onChange={setKeywords}
            placeholder="e.g. python, docker"
          />
        </label>
        <div className="form-actions">
          <button
            className="btn btn-primary"
            type="submit"
            disabled={busy || !keywords.length}
          >
            {busy ? "Searching…" : "Search"}
          </button>
        </div>
        <p className="muted small">
          Full-text search over resumes stored by the rank workflow, best
          matches first.
        </p>
      </form>

      {error && <ErrorBanner message={error} />}

      {results &&
        (results.length ? (
          <div className="card table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>File</th>
                  <th>Exp (yrs)</th>
                  <th>Skills</th>
                  <th>Matches</th>
                </tr>
              </thead>
              <tbody>
                {results.map((resume) => (
                  <tr key={resume.id}>
                    <td>
                      <div>{resume.name || "Unknown"}</div>
                      <div className="muted small">{resume.email}</div>
                    </td>
                    <td>{resume.file_name}</td>
                    <td>{resume.total_experience ?? "—"}</td>
                    <td className="chip-cell">
                      <Chips items={resume.skills} tone="accent" />
                    </td>
                    <td>
                      <div className="chip-group">
                        {resume.matched_keywords.map((match) => (
                          <span className="chip" key={match.keyword}>
                            {match.keyword} ×{match.count}
                          </span>
                        ))}
                      </div>
                      <div className="muted small">
                        {resume.distinct_keywords} distinct ·{" "}
                        {resume.total_matches} total
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="card empty-state">
            No stored resumes match those keywords.
          </div>
        ))}
    </div>
  )
}
