import { closestCenter, DndContext, type DragEndEvent } from '@dnd-kit/core'
import { RefreshCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { KanbanColumn } from '@/components/kanban/KanbanColumn'
import { usePipeline } from '@/hooks/usePipeline'

export default function PipelineKanban() {
  const { pipeline, stages, isLoading, updateStage } = usePipeline()

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return

    updateStage.mutate({
      contact_id: String(active.id),
      stage: String(over.id),
    })
  }

  if (isLoading) {
    return <Skeleton className="h-[36rem]" />
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-zinc-100">Operation Board</h2>
          <p className="mt-1 text-sm text-zinc-500">Track dossiers through their current relationship or operation state.</p>
        </div>
        <Button variant="ghost" onClick={() => window.location.reload()}>
          <RefreshCcw className="size-4" />
          Refresh Board
        </Button>
      </div>

      <DndContext collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <div className="flex min-h-0 gap-4 overflow-x-auto pb-4">
          {stages.map(({ id, label, color }) => (
            <KanbanColumn
              key={id}
              stage={id}
              label={label}
              color={color}
              items={pipeline.filter((item) => item.crm_stage === id)}
            />
          ))}
        </div>
      </DndContext>
    </div>
  )
}
