// Typed client for the Resume Ranker FastAPI backend (see ../models.py).

export interface StoredJob {
  job_id: string
  description: string
  posted_date: string
  created_at: string
  updated_at: string
  job_skills: string[]
  job_responsibilities: string[]
}

export interface JobPayload {
  job_id: string
  description: string
  posted_date?: string
  job_skills?: string[]
  job_responsibilities?: string[]
}

export interface RankResult {
  resume_id: number
  job_id: string
  file_name: string | null
  file_hash: string | null
  name: string | null
  email: string | null
  skills: string[]
  total_experience: number | null
  model: string
  candidate_skills: string
  candidate_experience: string
  skills_similarity: number
  experience_similarity: number
  average_similarity: number
}

export interface KeywordMatch {
  keyword: string
  count: number
}

export interface SearchResult {
  id: number
  name: string | null
  email: string | null
  file_name: string | null
  skills: string[]
  total_experience: number | null
  distinct_keywords: number
  total_matches: number
  matched_keywords: KeywordMatch[]
}

export interface ScoreRecord {
  resume_id: number
  job_id: string
  name: string | null
  email: string | null
  file_name: string | null
  skills: string[]
  total_experience: number | null
  skills_similarity: number
  experience_similarity: number
  average_similarity: number
  model: string | null
  updated_at: string
}

// AI assistant (agent chat + Docker sandbox observability)

export interface AgentSession {
  id: string
  title: string
  sandbox_status: string
  sandbox_container_id: string | null
  created_at: string
  updated_at: string
}

export interface AgentMessage {
  id: number
  session_id: string
  run_id: string | null
  role: string
  content: string
  created_at: string
}

export interface AgentEvent {
  seq: number
  type: string
  run_id: string | null
  data: Record<string, unknown>
  // present on records loaded from the API (live SSE events lack them)
  id?: number
  session_id?: string
  created_at?: string
}

export interface AgentSessionDetail {
  session: AgentSession
  messages: AgentMessage[]
  events: AgentEvent[]
}

export interface SandboxStatus {
  container_id: string | null
  name: string | null
  image: string | null
  status: string | null
  running: boolean
  started_at: string | null
  workspace_volume: string | null
  mem_usage: string | null
  cpu_percent: number | null
}

export interface SandboxFileEntry {
  name: string
  path: string
  size: number
  is_dir: boolean
  mtime: number | null
}

export interface SandboxFileContent {
  path: string
  size: number
  truncated: boolean
  binary: boolean
  content: string
}

export const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000"

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, init)
  if (!response.ok) {
    let detail = `Request failed (${response.status} ${response.statusText})`
    try {
      const body: unknown = await response.json()
      if (typeof body === "object" && body !== null && "detail" in body) {
        const { detail: parsed } = body as { detail: unknown }
        detail = typeof parsed === "string" ? parsed : JSON.stringify(parsed)
      }
    } catch {
      // non-JSON error body: keep the status-line message
    }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  listJobs: () => request<StoredJob[]>("/jobs"),

  createJob: (job: JobPayload) =>
    request<StoredJob>("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    }),

  updateJob: (jobId: string, changes: Partial<JobPayload>) =>
    request<StoredJob>(`/jobs/${encodeURIComponent(jobId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    }),

  deleteJob: (jobId: string) =>
    request<void>(`/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" }),

  rankResume: (file: File, jobId: string) => {
    const form = new FormData()
    form.append("resume_file", file)
    form.append("job_id", jobId)
    return request<RankResult>("/resumes/rank", { method: "POST", body: form })
  },

  searchResumes: (keywords: string[]) =>
    request<SearchResult[]>("/resumes/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keywords }),
    }),

  jobScores: (jobId: string) =>
    request<ScoreRecord[]>(`/jobs/${encodeURIComponent(jobId)}/scores`),
}

export const agentApi = {
  listSessions: () => request<AgentSession[]>("/agent/sessions"),

  createSession: () =>
    request<AgentSession>("/agent/sessions", { method: "POST" }),

  getSession: (sessionId: string) =>
    request<AgentSessionDetail>(`/agent/sessions/${encodeURIComponent(sessionId)}`),

  renameSession: (sessionId: string, title: string) =>
    request<AgentSession>(`/agent/sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),

  deleteSession: (sessionId: string) =>
    request<void>(`/agent/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    }),

  resetSandbox: (sessionId: string) =>
    request<SandboxStatus>(
      `/agent/sessions/${encodeURIComponent(sessionId)}/sandbox/reset`,
      { method: "POST" },
    ),

  sandboxStatus: (sessionId: string) =>
    request<SandboxStatus>(`/agent/sessions/${encodeURIComponent(sessionId)}/sandbox`),

  sandboxLogs: (sessionId: string, tail = 200) =>
    request<{ logs: string }>(
      `/agent/sessions/${encodeURIComponent(sessionId)}/sandbox/logs?tail=${tail}`,
    ),

  listSandboxFiles: (sessionId: string, path = "/workspace") =>
    request<SandboxFileEntry[]>(
      `/agent/sessions/${encodeURIComponent(sessionId)}/sandbox/files?path=${encodeURIComponent(path)}`,
    ),

  readSandboxFile: (sessionId: string, path: string) =>
    request<SandboxFileContent>(
      `/agent/sessions/${encodeURIComponent(sessionId)}/sandbox/files/content?path=${encodeURIComponent(path)}`,
    ),
}

// Direct link for opening a stored resume in a new browser tab (PDFs render
// inline; DOCX resumes are converted to PDF server-side). Navigation, not a
// fetch — CORS doesn't apply.
export const resumeFileUrl = (resumeId: number) =>
  `${BASE_URL}/resumes/${resumeId}/file`
