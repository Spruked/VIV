import { useEffect } from 'react'
import PipelineKanban from '@/components/kanban/PipelineKanban'
import { usePipeline } from '@/hooks/usePipeline'
import { updateVIVContext } from '@/lib/orb-integration'

export default function Pipeline() {
  const { pipeline } = usePipeline()

  useEffect(() => {
    const byStage = pipeline.reduce<Record<string, number>>((acc, item) => {
      acc[item.crm_stage] = (acc[item.crm_stage] || 0) + 1
      return acc
    }, {})
    updateVIVContext({
      currentView: 'pipeline',
      pipelineSummary: {
        total: pipeline.length,
        byStage,
      },
    })
  }, [pipeline])

  return <PipelineKanban />
}
