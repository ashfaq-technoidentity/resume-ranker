interface ChipsProps {
  items: string[]
  tone?: "accent" | "neutral"
}

export function Chips({ items, tone = "neutral" }: ChipsProps) {
  if (!items.length) return <span className="muted">—</span>
  return (
    <>
      {items.map((item) => (
        <span key={item} className={`chip chip-${tone}`}>
          {item}
        </span>
      ))}
    </>
  )
}
