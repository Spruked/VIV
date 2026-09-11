import * as React from 'react'
import { cn } from '@/lib/utils'

type BadgeVariant = 'default' | 'success' | 'warning' | 'muted'

const variants: Record<BadgeVariant, string> = {
  default: 'border-blue-900/70 bg-[#10224f] text-cyan-100',
  success: 'border-teal-700/60 bg-teal-950/40 text-teal-200',
  warning: 'border-violet-700/60 bg-violet-950/40 text-violet-200',
  muted: 'border-slate-700 bg-slate-900/70 text-slate-300',
}

export function Badge({
  className,
  variant = 'default',
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  return (
    <span
      className={cn('inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium', variants[variant], className)}
      {...props}
    />
  )
}
