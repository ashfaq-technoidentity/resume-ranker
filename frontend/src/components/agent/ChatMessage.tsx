import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { resumeFileUrl } from "../../api"
import { CodeBlock } from "./CodeBlock"
import { Icon } from "./Icon"
import { formatAbsolute, formatRelative } from "./time"

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
            {children}
            <Icon name="external" size={12} className="link-icon" />
          </a>
        )
      }
    }
    return (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
        <Icon name="external" size={12} className="link-icon" />
      </a>
    )
  },
  pre: ({ children, ...props }) => <CodeBlock {...props}>{children}</CodeBlock>,
}

interface ChatMessageProps {
  role: string
  content: string
  createdAt?: string
}

export function ChatMessage({ role, content, createdAt }: ChatMessageProps) {
  const isAssistant = role === "assistant"
  const timeText = createdAt ? formatAbsolute(createdAt) : undefined
  const timeAgo = createdAt ? formatRelative(createdAt) : undefined

  return (
    <div className={`chat-msg chat-msg-${role}`}>
      <div className="chat-avatar" aria-hidden>
        {isAssistant ? <Icon name="sparkles" size={18} /> : "Y"}
      </div>
      <div className="chat-content">
        <div className="chat-meta">
          {isAssistant ? "Assistant" : "You"}
          {timeText && (
            <span className="chat-time" title={timeText}>
              {timeAgo}
            </span>
          )}
        </div>
        <div className="chat-bubble">
          {isAssistant ? (
            <div className="md-body">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {content}
              </ReactMarkdown>
            </div>
          ) : (
            <div className="chat-text">{content}</div>
          )}
        </div>
      </div>
    </div>
  )
}
