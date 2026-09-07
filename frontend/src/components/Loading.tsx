export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="loading">{label}</div>
}
