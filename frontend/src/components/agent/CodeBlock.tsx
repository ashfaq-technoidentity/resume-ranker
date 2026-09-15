import { useState, type ReactNode } from "react"
import { Icon } from "./Icon"

interface CodeBlockProps {
  children?: ReactNode
  className?: string
}

function extractText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node)
  if (Array.isArray(node)) return node.map(extractText).join("")
  if (node && typeof node === "object" && "props" in node) {
    return extractText((node as { props?: { children?: ReactNode } }).props?.children)
  }
  return ""
}

function extractLanguage(node: ReactNode): string {
  if (node && typeof node === "object" && "props" in node) {
    const props = (node as { props?: { className?: string; children?: ReactNode } }).props
    const fromClass = props?.className?.replace("language-", "")
    if (fromClass) return fromClass
    return extractLanguage(props?.children)
  }
  if (Array.isArray(node)) {
    for (const child of node) {
      const lang = extractLanguage(child)
      if (lang) return lang
    }
  }
  return ""
}

export function CodeBlock({ children, className }: CodeBlockProps) {
  const [copied, setCopied] = useState(false)
  const text = extractText(children).replace(/\n$/, "")
  const language =
    className?.replace("language-", "") || extractLanguage(children) || ""

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore
    }
  }

  return (
    <div className="code-block">
      <div className="code-header">
        <span className="code-lang">{language || "code"}</span>
        <button
          type="button"
          className="btn btn-ghost btn-icon"
          onClick={copy}
          disabled={!text}
          title="Copy to clipboard"
        >
          <Icon name={copied ? "check" : "copy"} size={14} />
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className={className}>{children}</pre>
    </div>
  )
}
