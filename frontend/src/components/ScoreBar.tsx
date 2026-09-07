interface ScoreBarProps {
  label: string
  value: number
}

export function ScoreBar({ label, value }: ScoreBarProps) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  return (
    <div className="score">
      <div className="score-head">
        <span>{label}</span>
        <span className="score-value">{(value * 100).toFixed(1)}%</span>
      </div>
      <div className="score-track">
        <div className="score-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
