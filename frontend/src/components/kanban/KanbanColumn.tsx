import { useDroppable } from '@dnd-kit/core'
import { KanbanCard } from '@/components/kanban/KanbanCard'
import { EmptyState } from '@/components/ui/empty'
import type { PipelineItem } from '@/types'

export function KanbanColumn({
  stage,
  items,
  label,
  color,
}: {
  stage: string
  items: PipelineItem[]
  label: string
  color: string
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage })

  return (
    <section className="flex min-w-72 flex-1 flex-col">
      <div className={`sticky top-0 z-10 flex items-center justify-between rounded-t-lg px-4 py-3 text-sm font-semibold text-white ${color}`}>
        <span>{label}</span>
        <span className="rounded-md bg-black/30 px-2 py-0.5 text-xs">{items.length}</span>
      </div>

      <div
        ref={setNodeRef}
        className={
          isOver
            ? 'flex min-h-[32rem] flex-1 flex-col gap-3 rounded-b-lg border border-t-0 border-cyan-400/50 bg-[#122757]/80 p-3'
            : 'flex min-h-[32rem] flex-1 flex-col gap-3 rounded-b-lg border border-t-0 border-blue-900/70 bg-[#0f1b3d]/75 p-3'
        }
      >
        {items.map((item) => (
          <KanbanCard key={item.id} item={item} />
        ))}
        {!items.length ? <EmptyState className="min-h-32 p-4" title="Empty stage" /> : null}
      </div>
    </section>
  )
}
