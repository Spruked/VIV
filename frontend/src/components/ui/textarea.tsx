import * as React from 'react'
import { cn } from '@/lib/utils'

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        'min-h-24 w-full resize-y rounded-lg border border-blue-900/70 bg-[#0b1633] px-3 py-2 text-sm text-zinc-100 outline-none transition placeholder:text-cyan-200/40 focus:border-cyan-400/70',
        className,
      )}
      {...props}
    />
  ),
)

Textarea.displayName = 'Textarea'
