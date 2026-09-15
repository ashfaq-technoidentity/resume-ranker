import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { resumeFileUrl } from "../../api"

const markdownComponents: Components = {
  a: ({ href, children }) => {
    if (typeof href === "string" && href.startsWith("resume://")) {
      const id = Number(href.slice("resume://".length))
      if (Number.isInteger(id) && id > 0) {
        return (
          <a
            className="resume-link"
            href={resumeFileUrl(id)}
            target="_blank"
            rel="noreferrer"
          >
            {children} ↗
          </a>
        )
      }
    }
    return (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    )
  },
}

export function ChatMessage({ role, content }: { role: string; content: string }) {
  return (
    <div className={`chat-msg chat-msg-${role}`}>
      <div className="chat-bubble">
        {role === "assistant" ? (
          <div className="md-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {content}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="chat-text">{content}</div>
        )}
      </div>
    </div>
  )
}
