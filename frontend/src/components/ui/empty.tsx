import { Inbox } from 'lucide-react'
import { cn } from '@/lib/utils'

export function EmptyState({ title, detail, className }: { title: string; detail?: string; className?: string }) {
  return (
    <div className={cn('flex min-h-48 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-zinc-800 p-8 text-center', className)}>
      <div className="flex size-10 items-center justify-center rounded-lg bg-zinc-900 text-zinc-500">
        <Inbox className="size-5" />
      </div>
      <div>
        <p className="text-sm font-medium text-zinc-200">{title}</p>
        {detail ? <p className="mt-1 text-sm text-zinc-500">{detail}</p> : null}
      </div>
    </div>
  )
}
