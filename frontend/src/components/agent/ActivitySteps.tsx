import { useEffect, useRef, useState } from "react"
import type { AgentEvent } from "../../api"
import { Icon } from "./Icon"

// Steps the agent took during one run: thoughts and tool calls with their
// (streamed) output. Rendered from live SSE events or replayed DB events.

type ToolStep = {
  kind: "tool"
  tool: string
  toolCallId: string
  input: Record<string, unknown>
  output: string
  exitCode: number | null
  done: boolean
}

type ThoughtStep = { kind: "thought"; content: string }

type Step = ToolStep | ThoughtStep

function toSteps(events: AgentEvent[]): Step[] {
  const steps: Step[] = []
  for (const event of events) {
    const data = event.data ?? {}
    if (event.type === "thought") {
      steps.push({ kind: "thought", content: String(data.content ?? "") })
    } else if (event.type === "action") {
      steps.push({
        kind: "tool",
        tool: String(data.tool ?? "tool"),
        toolCallId: String(data.tool_call_id ?? ""),
        input: (data.input as Record<string, unknown>) ?? {},
        output: "",
        exitCode: null,
        done: false,
      })
    } else if (event.type === "output" || event.type === "observation") {
      for (let index = steps.length - 1; index >= 0; index -= 1) {
        const step = steps[index]
        if (step.kind !== "tool" || step.toolCallId !== data.tool_call_id) continue
        if (event.type === "output") {
          step.output += String(data.chunk ?? "")
        } else {
          step.done = true
          step.exitCode = typeof data.exit_code === "number" ? data.exit_code : null
          if (!step.output && typeof data.output === "string") step.output = data.output
        }
        break
      }
    }
  }
  return steps
}

function ToolStepView({ step }: { step: ToolStep }) {
  const [open, setOpen] = useState(!step.done)
  const wasDone = useRef(step.done)

  useEffect(() => {
    // auto-collapse the step once it finishes (like ChatGPT's tool blocks)
    if (step.done && !wasDone.current) setOpen(false)
    wasDone.current = step.done
  }, [step.done])

  const isPython = step.tool === "run_python"
  const code = isPython
    ? String(step.input.code ?? "")
    : `pip install ${((step.input.packages as string[]) ?? []).join(" ")}`
  const exitOk = step.exitCode === 0
  const exitBadge =
    step.exitCode === null ? (
      <span className="step-badge step-running-badge">
        <span className="step-spinner" aria-hidden />
        running
      </span>
    ) : (
      <span className={`step-badge ${exitOk ? "step-ok" : "step-fail"}`}>
        {exitOk && <Icon name="check" size={10} />}
        exit {step.exitCode}
      </span>
    )

  return (
    <div className={`step step-tool ${open ? "step-open" : ""}`}>
      <button className="step-head" onClick={() => setOpen(!open)} type="button">
        <span className="step-chevron" aria-hidden>
          <Icon name={open ? "chevron-down" : "chevron-right"} size={12} />
        </span>
        <span className="step-icon">
          <Icon name={isPython ? "terminal" : "package"} size={14} />
        </span>
        <span className="step-title">
          {isPython ? "Ran Python" : "Installed packages"}
        </span>
        {exitBadge}
      </button>
      {open && (
        <div className="step-body">
          <div className="step-section">
            <span className="step-section-label">Input</span>
            <pre className="step-code">{code}</pre>
          </div>
          {step.output && (
            <div className="step-section">
              <span className="step-section-label">Output</span>
              <pre className="step-output">
                {step.output}
                {!step.done && <span className="cursor">▊</span>}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ActivitySteps({
  events,
  running,
}: {
  events: AgentEvent[]
  running: boolean
}) {
  const [open, setOpen] = useState(running)
  const wasRunning = useRef(running)
  const steps = toSteps(events)

  useEffect(() => {
    if (running && !wasRunning.current) setOpen(true)
    if (!running && wasRunning.current) setOpen(false)
    wasRunning.current = running
  }, [running])

  if (!steps.length) return null
  return (
    <div className={`steps ${open ? "steps-open" : ""}`}>
      <button className="steps-toggle" onClick={() => setOpen(!open)} type="button">
        <span className="step-chevron" aria-hidden>
          <Icon name={open ? "chevron-down" : "chevron-right"} size={12} />
        </span>
        <span className="step-icon">
          <Icon name="code" size={14} />
        </span>
        <span className="steps-toggle-title">
          {running ? "Assistant is working" : `Agent steps (${steps.length})`}
        </span>
      </button>
      {open && (
        <div className="steps-list">
          {steps.map((step, index) =>
            step.kind === "thought" ? (
              <div className="step step-thought" key={`thought-${index}`}>
                <span className="step-thought-icon">
                  <Icon name="lightbulb" size={14} />
                </span>
                {step.content}
              </div>
            ) : (
              <ToolStepView key={`tool-${index}`} step={step} />
            ),
          )}
        </div>
      )}
    </div>
  )
}
