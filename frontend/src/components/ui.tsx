import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'

export function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ')
}

export function Card({
  title,
  subtitle,
  action,
  children,
  className,
  padded = true,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  children?: ReactNode
  className?: string
  padded?: boolean
}) {
  return (
    <section className={cx('surface', className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-3">
          <div className="min-w-0">
            {title && (
              <h2 className="truncate text-[13.5px] font-semibold text-ink">{title}</h2>
            )}
            {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={padded ? 'px-4 py-3.5' : undefined}>{children}</div>
    </section>
  )
}

const BADGE_TONES = {
  neutral: 'bg-slate-100 text-slate-600 ring-slate-200',
  indigo: 'bg-blue-50 text-blue-700 ring-blue-200',
  emerald: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  amber: 'bg-amber-50 text-amber-700 ring-amber-200',
  rose: 'bg-rose-50 text-rose-700 ring-rose-200',
  sky: 'bg-sky-50 text-sky-700 ring-sky-200',
} as const

export type BadgeTone = keyof typeof BADGE_TONES

export function Badge({
  children,
  tone = 'neutral',
  className,
}: {
  children: ReactNode
  tone?: BadgeTone
  className?: string
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset',
        BADGE_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

type ButtonVariant = 'primary' | 'ghost' | 'outline' | 'danger'

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-white hover:bg-accent-hover',
  ghost: 'text-ink-soft hover:bg-slate-100 hover:text-ink',
  outline: 'border border-line-strong bg-surface text-ink-soft hover:border-slate-400 hover:bg-slate-50',
  danger: 'border border-rose-200 bg-surface text-rose-600 hover:bg-rose-50',
}

export function Button({
  variant = 'primary',
  loading = false,
  className,
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      className={cx(
        'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55',
        BUTTON_VARIANTS[variant],
        className,
      )}
    >
      {loading && (
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" />
      )}
      {children}
    </button>
  )
}

export function ProgressBar({
  value,
  tone = 'indigo',
  className,
}: {
  value: number
  tone?: 'indigo' | 'emerald' | 'amber'
  className?: string
}) {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
  const colors = {
    indigo: 'bg-blue-600',
    emerald: 'bg-emerald-600',
    amber: 'bg-amber-500',
  }
  return (
    <div className={cx('h-1.5 w-full overflow-hidden rounded-full bg-slate-200', className)}>
      <div
        className={cx('h-full rounded-full transition-all', colors[tone])}
        style={{ width: `${clamped * 100}%` }}
      />
    </div>
  )
}

export function Stat({
  label,
  value,
  hint,
  tone = 'indigo',
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: 'indigo' | 'emerald' | 'amber' | 'rose'
}) {
  const tones = {
    indigo: 'text-ink',
    emerald: 'text-emerald-700',
    amber: 'text-amber-700',
    rose: 'text-rose-600',
  }
  return (
    <div className="surface-muted px-3.5 py-3">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className={cx('mt-1 text-xl font-semibold tabular-nums', tones[tone])}>{value}</p>
      {hint && <p className="mt-1 text-[11px] text-ink-muted">{hint}</p>}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface-muted px-6 py-9 text-center">
      <p className="text-[13px] font-medium text-ink">{title}</p>
      {description && (
        <p className="max-w-md text-xs leading-relaxed text-ink-muted">{description}</p>
      )}
      {action}
    </div>
  )
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2.5">
      <p className="flex-1 text-xs leading-relaxed text-rose-700">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 text-[11px] font-medium text-rose-700 underline underline-offset-2 hover:text-rose-800"
        >
          重试
        </button>
      )}
    </div>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-ink-soft">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-ink-muted">{hint}</span>}
    </label>
  )
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx('control', className)} />
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx('control resize-y', className)} />
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={cx('control appearance-none', className)}>
      {children}
    </select>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-ink-muted">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-accent border-t-transparent" />
      {label}
    </div>
  )
}
