import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { BASE_URL } from "../../api"
import { CodeBlock } from "./CodeBlock"
import { Icon } from "./Icon"
import { formatAbsolute, formatRelative } from "./time"

/** ReactMarkdown sanitises non-HTTP URL schemes, so replace the agent's
 *  resume://ID links with real API URLs before markdown parsing. */
function resolveResumeLinks(content: string): string {
  return content.replace(/resume:\/\/(\d+)/g, `${BASE_URL}/resumes/$1/file`)
}

function isResumeFileUrl(href: string | undefined): boolean {
  if (!href) return false
  return href.startsWith(`${BASE_URL}/resumes/`) && href.endsWith("/file")
}

const markdownComponents: Components = {
  a: ({ href, children }) => {
    return (
      <a
        className={isResumeFileUrl(href) ? "resume-link" : ""}
        href={href}
        target="_blank"
        rel="noreferrer"
      >
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
  const renderedContent = role === "assistant" ? resolveResumeLinks(content) : content
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
                {renderedContent}
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
