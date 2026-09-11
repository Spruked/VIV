import * as React from 'react'
import { cn } from '@/lib/utils'

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        'h-10 w-full rounded-lg border border-blue-900/70 bg-[#0b1633] px-3 text-sm text-zinc-100 outline-none transition placeholder:text-cyan-200/40 focus:border-cyan-400/70',
        className,
      )}
      {...props}
    />
  ),
)

Input.displayName = 'Input'
