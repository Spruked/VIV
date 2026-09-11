import * as React from 'react'
import { cn } from '@/lib/utils'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
type ButtonSize = 'sm' | 'md' | 'icon'

const variants: Record<ButtonVariant, string> = {
  primary: 'border-cyan-400/30 bg-gradient-to-r from-[#1d4ed8] via-[#00c2ff] to-[#00d2b5] text-white hover:brightness-110',
  secondary: 'border-blue-900/70 bg-[#0f1b3d] text-zinc-100 hover:bg-[#162754]',
  ghost: 'border-transparent bg-transparent text-cyan-200 hover:bg-[#10224f] hover:text-cyan-100',
  danger: 'border-red-950 bg-red-950/40 text-red-200 hover:bg-red-950/70',
}

const sizes: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-10 px-4 text-sm',
  icon: 'size-10 p-0',
}

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: ButtonSize
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'secondary', size = 'md', ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        'inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border font-medium outline-none transition disabled:cursor-not-allowed disabled:opacity-50',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  ),
)

Button.displayName = 'Button'
