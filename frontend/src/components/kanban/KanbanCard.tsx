import { useDraggable } from '@dnd-kit/core'
import { Calendar, Mail } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { compactDate, initials } from '@/lib/utils'
import type { PipelineItem } from '@/types'

export function KanbanCard({ item }: { item: PipelineItem }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: item.id,
  })

  const style = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
      }
    : undefined

  return (
    <Card
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className={isDragging ? 'cursor-grabbing p-4 opacity-70 ring-1 ring-white/30' : 'cursor-grab p-4 transition hover:border-zinc-600'}
    >
      <div className="flex items-start gap-3">
        <div className="flex size-9 items-center justify-center rounded-lg bg-zinc-900 text-xs font-semibold text-zinc-300">
          {initials(item.name)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-zinc-100">{item.name}</div>
          <div className="mt-1 flex items-center gap-1 truncate text-xs text-zinc-500">
            <Mail className="size-3" />
            {item.email || 'No origin'}
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Badge variant="muted">{item.type || item.contact_type || 'subject'}</Badge>
        {item.next_follow_up_at ? (
          <span className="inline-flex items-center gap-1 text-xs text-amber-300">
            <Calendar className="size-3" />
            {compactDate(item.next_follow_up_at)}
          </span>
        ) : null}
      </div>
    </Card>
  )
}
