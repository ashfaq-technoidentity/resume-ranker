// Streaming helpers for the AI assistant's server-sent-event endpoints.
// The chat endpoint is a POST whose response is an SSE stream, consumed with
// fetch + a hand-rolled frame parser; the docker-logs endpoint is a GET
// consumed with the browser's EventSource (which auto-reconnects).

import type { AgentEvent } from "./api"

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000"

async function readErrorDetail(response: Response): Promise<string> {
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
  return detail
}

export async function streamAgentChat(
  sessionId: string,
  content: string,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(
    `${BASE_URL}/agent/sessions/${encodeURIComponent(sessionId)}/chat`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
      signal,
    },
  )
  if (!response.ok || !response.body) {
    throw new Error(await readErrorDetail(response))
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let separator = buffer.indexOf("\n\n")
    while (separator !== -1) {
      const frame = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n")
      if (data) {
        try {
          onEvent(JSON.parse(data) as AgentEvent)
        } catch {
          // ignore malformed frames
        }
      }
      separator = buffer.indexOf("\n\n")
    }
  }
}

export const sandboxLogsStreamUrl = (sessionId: string, tail = 100) =>
  `${BASE_URL}/agent/sessions/${encodeURIComponent(
    sessionId,
  )}/sandbox/logs/stream?tail=${tail}`
