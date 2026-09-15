export type IconName =
  | "sparkles"
  | "chat"
  | "send"
  | "plus"
  | "trash"
  | "chevron-down"
  | "chevron-right"
  | "terminal"
  | "code"
  | "package"
  | "folder"
  | "file"
  | "copy"
  | "check"
  | "refresh"
  | "external"
  | "lightbulb"
  | "pause"
  | "cpu"
  | "memory"

interface IconProps {
  name: IconName
  size?: number
  className?: string
}

export function Icon({ name, size = 16, className = "" }: IconProps) {
  const s = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
  }

  switch (name) {
    case "sparkles":
      return (
        <svg {...s}>
          <path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z" />
          <path d="M19 19l-1.5-1.5M5 5l1.5 1.5M20 4l-2 2M4 20l2-2" />
        </svg>
      )
    case "chat":
      return (
        <svg {...s}>
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7A8.38 8.38 0 0 1 4 11.5a8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
        </svg>
      )
    case "send":
      return (
        <svg {...s}>
          <line x1="22" y1="2" x2="11" y2="13" />
          <polygon points="22 2 15 22 11 13 2 9 22 2" />
        </svg>
      )
    case "plus":
      return (
        <svg {...s}>
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      )
    case "trash":
      return (
        <svg {...s}>
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          <line x1="10" y1="11" x2="10" y2="17" />
          <line x1="14" y1="11" x2="14" y2="17" />
        </svg>
      )
    case "chevron-down":
      return (
        <svg {...s}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      )
    case "chevron-right":
      return (
        <svg {...s}>
          <polyline points="9 18 15 12 9 6" />
        </svg>
      )
    case "terminal":
      return (
        <svg {...s}>
          <polyline points="4 17 10 11 4 5" />
          <line x1="12" y1="19" x2="20" y2="19" />
        </svg>
      )
    case "code":
      return (
        <svg {...s}>
          <polyline points="16 18 22 12 16 6" />
          <polyline points="8 6 2 12 8 18" />
        </svg>
      )
    case "package":
      return (
        <svg {...s}>
          <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
          <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
          <line x1="12" y1="22.08" x2="12" y2="12" />
        </svg>
      )
    case "folder":
      return (
        <svg {...s}>
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l4 3h9a2 2 0 0 1 2 2z" />
        </svg>
      )
    case "file":
      return (
        <svg {...s}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
      )
    case "copy":
      return (
        <svg {...s}>
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )
    case "check":
      return (
        <svg {...s}>
          <polyline points="20 6 9 17 4 12" />
        </svg>
      )
    case "refresh":
      return (
        <svg {...s}>
          <polyline points="23 4 23 10 17 10" />
          <polyline points="1 20 1 14 7 14" />
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
        </svg>
      )
    case "external":
      return (
        <svg {...s}>
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
          <polyline points="15 3 21 3 21 9" />
          <line x1="10" y1="14" x2="21" y2="3" />
        </svg>
      )
    case "lightbulb":
      return (
        <svg {...s}>
          <path d="M9 18h6" />
          <path d="M10 22h4" />
          <path d="M15.09 14c.18-.9.27-1.9.27-3 0-3.5-2.69-6.32-6-6.32S3.36 7.5 3.36 11c0 1.1.09 2.1.27 3" />
          <path d="M12 2v2" />
        </svg>
      )
    case "pause":
      return (
        <svg {...s}>
          <rect x="6" y="4" width="4" height="16" />
          <rect x="14" y="4" width="4" height="16" />
        </svg>
      )
    case "cpu":
      return (
        <svg {...s}>
          <rect x="4" y="4" width="16" height="16" rx="2" ry="2" />
          <rect x="9" y="9" width="6" height="6" />
          <line x1="9" y1="1" x2="9" y2="4" />
          <line x1="15" y1="1" x2="15" y2="4" />
          <line x1="9" y1="20" x2="9" y2="23" />
          <line x1="15" y1="20" x2="15" y2="23" />
          <line x1="20" y1="9" x2="23" y2="9" />
          <line x1="20" y1="14" x2="23" y2="14" />
          <line x1="1" y1="9" x2="4" y2="9" />
          <line x1="1" y1="14" x2="4" y2="14" />
        </svg>
      )
    case "memory":
      return (
        <svg {...s}>
          <rect x="2" y="6" width="20" height="12" rx="2" ry="2" />
          <line x1="6" y1="10" x2="6.01" y2="10" />
          <line x1="10" y1="10" x2="10.01" y2="10" />
          <line x1="14" y1="10" x2="14.01" y2="10" />
          <line x1="18" y1="10" x2="18.01" y2="10" />
          <line x1="8" y1="14" x2="8.01" y2="14" />
          <line x1="12" y1="14" x2="12.01" y2="14" />
          <line x1="16" y1="14" x2="16.01" y2="14" />
        </svg>
      )
    default:
      return null
  }
}
