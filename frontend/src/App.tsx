import { useCallback, useEffect, useState } from "react"
import { api, type StoredJob } from "./api"
import { ErrorBanner } from "./components/ErrorBanner"
import { Loading } from "./components/Loading"
import { Assistant } from "./screens/Assistant"
import { BatchUpload } from "./screens/BatchUpload"
import { History } from "./screens/History"
import { Jobs } from "./screens/Jobs"
import { Rank } from "./screens/Rank"
import { Search } from "./screens/Search"

type Tab = "jobs" | "batch" | "rank" | "search" | "history" | "assistant"

const TABS: { id: Tab; label: string }[] = [
  { id: "jobs", label: "Jobs" },
  { id: "batch", label: "Batch upload" },
  { id: "rank", label: "Rank resume" },
  { id: "search", label: "Search" },
  { id: "history", label: "Score history" },
  { id: "assistant", label: "AI Assistant" },
]

export default function App() {
  const [tab, setTab] = useState<Tab>("jobs")
  const [jobs, setJobs] = useState<StoredJob[]>([])
  const [jobsError, setJobsError] = useState("")
  const [loadingJobs, setLoadingJobs] = useState(true)
  const [jobsVersion, setJobsVersion] = useState(0)

  const reloadJobs = useCallback(() => {
    setLoadingJobs(true)
    setJobsError("")
    setJobsVersion((version) => version + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    api
      .listJobs()
      .then((loaded) => {
        if (cancelled) return
        setJobs(loaded)
        setJobsError("")
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setJobsError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoadingJobs(false)
      })
    return () => {
      cancelled = true
    }
  }, [jobsVersion])

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <span className="brand">Resume Ranker</span>
          <nav className="tabs">
            {TABS.map(({ id, label }) => (
              <button
                key={id}
                className={`tab ${tab === id ? "tab-active" : ""}`}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>
      <main className={`container ${tab === "assistant" ? "container-wide" : ""}`}>
        {jobsError && <ErrorBanner message={jobsError} />}
        {tab === "assistant" ? (
          <Assistant />
        ) : loadingJobs ? (
          <Loading label="Loading jobs…" />
        ) : (
          <>
            {tab === "jobs" && <Jobs jobs={jobs} onJobsChanged={reloadJobs} />}
            {tab === "batch" && <BatchUpload jobs={jobs} />}
            {tab === "rank" && <Rank jobs={jobs} onSwitchToBatch={() => setTab("batch")} />}
            {tab === "search" && <Search />}
            {tab === "history" && <History jobs={jobs} />}
          </>
        )}
      </main>
    </div>
  )
}
