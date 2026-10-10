import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'

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
    <section
      className={cx(
        'rounded-2xl border border-white/8 bg-white/[0.025] shadow-[0_18px_50px_-30px_rgba(15,23,42,0.9)] backdrop-blur-sm',
        className,
      )}
    >
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 border-b border-white/6 px-5 py-4">
          <div>
            {title && <h2 className="text-[15px] font-semibold text-slate-100">{title}</h2>}
            {subtitle && <p className="mt-1 text-xs text-slate-400">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={padded ? 'px-5 py-4' : undefined}>{children}</div>
    </section>
  )
}

const BADGE_TONES = {
  neutral: 'bg-slate-500/12 text-slate-300 ring-slate-400/20',
  indigo: 'bg-indigo-500/12 text-indigo-300 ring-indigo-400/25',
  emerald: 'bg-emerald-500/12 text-emerald-300 ring-emerald-400/25',
  amber: 'bg-amber-500/12 text-amber-300 ring-amber-400/25',
  rose: 'bg-rose-500/12 text-rose-300 ring-rose-400/25',
  sky: 'bg-sky-500/12 text-sky-300 ring-sky-400/25',
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
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset',
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
  primary:
    'bg-indigo-500 text-white hover:bg-indigo-400 disabled:bg-indigo-500/40 disabled:text-white/60',
  ghost: 'text-slate-300 hover:bg-white/6 hover:text-white',
  outline: 'border border-white/12 text-slate-200 hover:border-white/25 hover:bg-white/5',
  danger: 'border border-rose-500/30 text-rose-300 hover:bg-rose-500/10',
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
        'inline-flex items-center justify-center gap-2 rounded-xl px-3.5 py-2 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-70',
        BUTTON_VARIANTS[variant],
        className,
      )}
    >
      {loading && (
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-[1.6px] border-current border-t-transparent" />
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
    indigo: 'from-indigo-500 to-violet-400',
    emerald: 'from-emerald-500 to-teal-400',
    amber: 'from-amber-500 to-orange-400',
  }
  return (
    <div className={cx('h-1.5 w-full overflow-hidden rounded-full bg-white/8', className)}>
      <div
        className={cx('h-full rounded-full bg-gradient-to-r transition-all', colors[tone])}
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
    indigo: 'text-indigo-300',
    emerald: 'text-emerald-300',
    amber: 'text-amber-300',
    rose: 'text-rose-300',
  }
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.02] px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className={cx('mt-1.5 text-xl font-semibold tabular-nums', tones[tone])}>{value}</p>
      {hint && <p className="mt-1 text-[11px] text-slate-500">{hint}</p>}
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
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-white/10 px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-300">{title}</p>
      {description && <p className="max-w-md text-xs leading-relaxed text-slate-500">{description}</p>}
      {action}
    </div>
  )
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-rose-500/25 bg-rose-500/8 px-4 py-3">
      <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-rose-400" />
      <p className="flex-1 text-xs leading-relaxed text-rose-200">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="text-[11px] font-medium text-rose-300 underline underline-offset-2 hover:text-rose-200"
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
      <span className="text-[11px] font-medium text-slate-400">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-slate-600">{hint}</span>}
    </label>
  )
}

const INPUT_CLASS =
  'w-full rounded-xl border border-white/10 bg-slate-950/50 px-3 py-2 text-[13px] text-slate-100 outline-none transition-colors placeholder:text-slate-600 focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-500/15'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(INPUT_CLASS, className)} />
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(INPUT_CLASS, 'resize-y', className)} />
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={cx(INPUT_CLASS, 'appearance-none', className)}>
      {children}
    </select>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-[1.6px] border-indigo-400 border-t-transparent" />
      {label}
    </div>
  )
}
