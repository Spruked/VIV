import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Mail, Server, Users } from 'lucide-react'
import { ContextDebugPanel } from '@/components/ContextDebugPanel'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { SectionHeader } from '@/components/SectionHeader'
import { pipelineStages } from '@/hooks/usePipeline'
import { api } from '@/lib/api'
import { updateVIVContext } from '@/lib/orb-integration'
import type { UnifiedStatus } from '@/types'

const lifecycleLabels = Object.fromEntries(pipelineStages.map((stage) => [stage.id, stage.label])) as Record<string, string>

function StatCard({ title, value, detail, icon: Icon }: { title: string; value: string | number; detail: string; icon: typeof Server }) {
  const valueText = String(value)
  const valueClass = valueText.length > 11 ? 'text-2xl' : 'text-3xl'

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{detail}</CardDescription>
        </div>
        <div className="flex size-10 items-center justify-center rounded-lg bg-zinc-900 text-zinc-400">
          <Icon className="size-5" />
        </div>
      </CardHeader>
      <CardContent>
        <div className={`${valueClass} break-words font-semibold leading-tight text-zinc-100`}>{value}</div>
      </CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: async () => (await api.get('/health')).data as { status: string; service: string },
  })

  const status = useQuery({
    queryKey: ['viv-unified-status'],
    queryFn: async () => (await api.get('/cali/crm/unified/status')).data as UnifiedStatus,
  })

  const pipeline = status.data?.crm_pipeline
  const connector = status.data?.crm_email_connector
  const externalEmail = status.data?.external_email
  const vivApiStatus = health.data?.status || (!status.isError ? 'ok' : 'unknown')
  const bridgeStatus = externalEmail?.status || (externalEmail?.enabled ? 'degraded' : 'disabled')
  const bridgeBadge = bridgeStatus === 'online' ? 'success' : 'warning'
  const bridgeDetail = externalEmail?.detail || externalEmail?.api_base || 'VIV communications bridge'

  useEffect(() => {
    if (!pipeline) return
    updateVIVContext({
      currentView: 'dashboard',
      pipelineSummary: {
        total: pipeline.total,
        byStage: pipeline.stages,
      },
      lastAction: 'dashboard_status_loaded',
    })
  }, [pipeline])

  return (
    <div>
      <SectionHeader title="Command Center" detail="Your current intelligence picture across dossiers, communications, signals, events, and operations." />

      <div className="grid gap-4 lg:grid-cols-4">
        {health.isLoading ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-36" />)
        ) : (
          <>
            <StatCard title="VIV Core" value={vivApiStatus} detail={health.data?.service || 'protected local intelligence API'} icon={Server} />
            <StatCard title="Active Dossiers" value={pipeline?.total ?? 0} detail="subjects currently in operational scope" icon={Users} />
            <StatCard title="Communications Bridge" value={bridgeStatus} detail={bridgeDetail} icon={Mail} />
            <StatCard title="Connection Mediator" value={connector?.status || 'unknown'} detail="identity and communication handoff" icon={Activity} />
          </>
        )}
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <CardHeader>
            <CardTitle>Operational Snapshot</CardTitle>
            <CardDescription>Current dossier distribution across the VIV lifecycle.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {Object.entries(pipeline?.stages || {}).map(([stage, count]) => (
                <div key={stage} className="rounded-lg border border-zinc-800 bg-black/30 p-4">
                  <div className="text-xs uppercase text-zinc-500">{lifecycleLabels[stage] || stage.replaceAll('_', ' ')}</div>
                  <div className="mt-2 text-2xl font-semibold text-zinc-100">{count}</div>
                </div>
              ))}
              {!pipeline ? <Skeleton className="h-24" /> : null}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System Connections</CardTitle>
            <CardDescription>Authorized local services and connected VIV systems.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex items-center justify-between rounded-lg border border-zinc-800 p-3">
              <span className="text-sm text-zinc-400">VIV core</span>
              <Badge variant={vivApiStatus === 'ok' ? 'success' : 'warning'}>{vivApiStatus}</Badge>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-zinc-800 p-3">
              <span className="text-sm text-zinc-400">Communications bridge</span>
              <Badge variant={bridgeBadge}>{bridgeStatus}</Badge>
            </div>
            {externalEmail?.detail ? (
              <div className="rounded-lg border border-zinc-800 p-3 text-xs text-zinc-500">
                Communications detail: {externalEmail.detail}
              </div>
            ) : null}
            <div className="flex items-center justify-between rounded-lg border border-zinc-800 p-3">
              <span className="text-sm text-zinc-400">Access control</span>
              <Badge variant={status.isError ? 'warning' : 'success'}>{status.isError ? 'check token' : 'accepted'}</Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-5">
        <ContextDebugPanel />
      </div>
    </div>
  )
}
