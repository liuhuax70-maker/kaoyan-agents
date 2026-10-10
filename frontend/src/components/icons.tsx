import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function Base({ size = 18, children, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

export function IconDashboard(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="3" y="3" width="7" height="9" rx="1.6" />
      <rect x="14" y="3" width="7" height="5" rx="1.6" />
      <rect x="14" y="12" width="7" height="9" rx="1.6" />
      <rect x="3" y="16" width="7" height="5" rx="1.6" />
    </Base>
  )
}

export function IconChat(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M21 12a8 8 0 0 1-8 8H8l-5 3 1.4-4.6A8 8 0 0 1 13 4a8 8 0 0 1 8 8Z" />
      <path d="M9 11h8M9 15h5" />
    </Base>
  )
}

export function IconPlan(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="4" y="4" width="16" height="17" rx="2.4" />
      <path d="M8 3v3M16 3v3M8 11h8M8 15h5" />
    </Base>
  )
}

export function IconSystem(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2 2 2 0 1 1-4 0 1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 15a2 2 0 1 1 0-4 1.7 1.7 0 0 0 1.4-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 4.6a2 2 0 1 1 4 0 1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.7 1.7 0 0 0 21 11a2 2 0 1 1 0 4Z" />
    </Base>
  )
}

export function IconSpark(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 3v4M12 17v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M3 12h4M17 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8" />
    </Base>
  )
}

export function IconCheck(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M20 6 9 17l-5-5" />
    </Base>
  )
}

export function IconBell(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M18 8a6 6 0 1 0-12 0c0 7-3 8-3 8h18s-3-1-3-8" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" />
    </Base>
  )
}

export function IconChart(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M3 3v18h18" />
      <path d="M7 15l4-4 3 3 5-6" />
    </Base>
  )
}

export function IconRefresh(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M21 12a9 9 0 1 1-3-6.7L21 8" />
      <path d="M21 3v5h-5" />
    </Base>
  )
}

/* ---------- 对话页专用 ---------- */

export function IconPlus(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 5v14M5 12h14" />
    </Base>
  )
}

export function IconArrowUp(props: IconProps) {
  return (
    <Base {...props} strokeWidth={2}>
      <path d="M12 19V5M5 12l7-7 7 7" />
    </Base>
  )
}

export function IconStop(props: IconProps) {
  return (
    <Base {...props} strokeWidth={0}>
      <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
    </Base>
  )
}

/** 「联网搜索」 */
export function IconGlobe(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.5 2.6 2.5 15.4 0 18M12 3c-2.5 2.6-2.5 15.4 0 18" />
    </Base>
  )
}

/** 「深度思考」 */
export function IconBulb(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M9 18h6M10 21h4" />
      <path d="M12 3a6 6 0 0 1 3.5 10.9c-.5.4-.8 1-.8 1.6H9.3c0-.6-.3-1.2-.8-1.6A6 6 0 0 1 12 3Z" />
    </Base>
  )
}

export function IconCopy(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="9" y="9" width="11" height="11" rx="2.4" />
      <path d="M5 15V6a2 2 0 0 1 2-2h9" />
    </Base>
  )
}

export function IconMenu(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 6h16M4 12h16M4 18h16" />
    </Base>
  )
}
