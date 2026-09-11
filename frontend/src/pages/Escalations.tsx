import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, ExternalLink, Radio, UserCheck } from 'lucide-react'
import { toast } from 'sonner'
import { SectionHeader } from '@/components/SectionHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty'
import { api } from '@/lib/api'
import { useBusinessContext } from '@/providers/BusinessContextProvider'

export type Escalation = {
  escalation_id: string
  party_id?: string | null
  business_scope?: string | null
  channel: string
  thread_id?: string | null
  trigger_reason: string
  priority: 'p0' | 'p1' | 'p2' | 'p3'
  dossier_context?: Record<string, unknown>
  orb_actions?: Array<Record<string, unknown>>
  orb_stop_reason: string
  state: 'created' | 'notified' | 'acknowledged' | 'owned' | 'resolved' | 'closed'
  sla_due_at?: string | null
  owner?: string | null
  acked_at?: string | null
  resolved_at?: string | null
  continuation_ref?: string | null
  created_at: string
}

const priorityTone: Record<string, 'warning' | 'muted'> = {
  p0: 'warning',
  p1: 'warning',
  p2: 'muted',
  p3: 'muted',
}

function readable(value?: string | null) {
  return String(value || 'unknown').replaceAll('_', ' ')
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export default function Escalations() {
  const queryClient = useQueryClient()
  const { businessScope } = useBusinessContext()

  const escalationsQuery = useQuery({
    queryKey: ['escalations', businessScope],
    queryFn: async () => {
      const response = await api.get('/cali/intelligence/escalations', {
        params: { business_scope: businessScope, state: 'open', limit: 100 },
      })
      return response.data as { escalations: Escalation[]; count: number }
    },
    refetchInterval: 15_000,
  })

  const transition = useMutation({
    mutationFn: async ({ escalationId, state }: { escalationId: string; state: string }) =>
      api.post(`/cali/intelligence/escalations/${encodeURIComponent(escalationId)}/transition`, {
        state,
        owner: 'bryan@spruked.com',
      }),
    onSuccess: async (_, variables) => {
      toast.success(`Escalation ${variables.state}`)
      await queryClient.invalidateQueries({ queryKey: ['escalations'] })
    },
    onError: (error) => toast.error(error.message),
  })

  const items = escalationsQuery.data?.escalations || []

  return (
    <div>
      <SectionHeader
        title="Escalations"
        detail="Items requiring human attention, judgment, approval, ownership, or follow-through."
        action={
          <Button variant="secondary" onClick={() => void escalationsQuery.refetch()}>
            <Radio className="size-4" />
            Refresh
          </Button>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-3">
          {items.length ? items.map((item) => (
            <Card key={item.escalation_id} className="overflow-hidden">
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <div className={`mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl ${item.priority === 'p0' ? 'bg-red-950 text-red-300' : item.priority === 'p1' ? 'bg-amber-950 text-amber-300' : 'bg-blue-950 text-blue-300'}`}>
                      {item.priority === 'p0' || item.priority === 'p1' ? <img className="size-10 rounded-lg object-cover brightness-125 saturate-150 drop-shadow-[0_0_18px_rgba(248,113,113,0.6)]" src="/redVIVlogo.png" alt="" /> : <AlertTriangle className="size-6" />}
                    </div>
                    <div className="min-w-0">
                      <CardTitle className="capitalize">{readable(item.trigger_reason)}</CardTitle>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                        <span>{item.channel}</span><span>·</span><span>{item.business_scope || 'unscoped'}</span><span>·</span><span>{formatDate(item.created_at)}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Badge variant={priorityTone[item.priority] || 'muted'} className={item.priority === 'p0' ? 'border-red-800/60 bg-red-950/50 text-red-200' : undefined}>{item.priority.toUpperCase()}</Badge>
                    <Badge variant="muted">{item.state}</Badge>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="rounded-lg border border-zinc-800 bg-zinc-950/45 p-3 text-sm leading-6 text-zinc-300">
                  <div><span className="text-zinc-500">Reason: </span>{item.orb_stop_reason}</div>
                  {item.sla_due_at ? <div><span className="text-zinc-500">Response target: </span>{formatDate(item.sla_due_at)}</div> : null}
                  {item.owner ? <div><span className="text-zinc-500">Owner: </span>{item.owner}</div> : null}
                </div>

                {item.dossier_context && Object.keys(item.dossier_context).length ? (
                  <div className="mt-3 rounded-lg border border-blue-900/40 bg-blue-950/15 p-3">
                    <div className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-blue-400">Permitted Dossier Context</div>
                    <div className="space-y-1 text-xs text-zinc-400">
                      {Object.entries(item.dossier_context).slice(0, 8).map(([key, value]) => (
                        <div key={key}><span className="text-zinc-600">{readable(key)}: </span>{typeof value === 'string' ? value : JSON.stringify(value)}</div>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="mt-4 flex flex-wrap justify-end gap-2">
                  {item.continuation_ref ? (
                    <Button variant="secondary" onClick={() => window.open(String(item.continuation_ref), '_blank', 'noopener,noreferrer')}>
                      <ExternalLink className="size-4" />Continue
                    </Button>
                  ) : null}
                  {item.state === 'created' || item.state === 'notified' ? (
                    <Button variant="secondary" onClick={() => transition.mutate({ escalationId: item.escalation_id, state: 'acknowledged' })}>
                      <UserCheck className="size-4" />Acknowledge
                    </Button>
                  ) : null}
                  {item.state === 'acknowledged' ? (
                    <Button variant="primary" onClick={() => transition.mutate({ escalationId: item.escalation_id, state: 'owned' })}>
                      <UserCheck className="size-4" />Take Ownership
                    </Button>
                  ) : null}
                  {item.state === 'owned' || item.state === 'acknowledged' ? (
                    <Button variant="primary" onClick={() => transition.mutate({ escalationId: item.escalation_id, state: 'resolved' })}>
                      <CheckCircle2 className="size-4" />Resolve
                    </Button>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          )) : (
            <Card><CardContent><EmptyState title="No open escalations" detail="Items requiring human attention will appear here with relevant dossier context and continuation state." /></CardContent></Card>
          )}
        </div>

        <Card className="h-fit">
          <CardHeader><CardTitle>Escalation Rules</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-3 text-sm leading-6 text-zinc-400">
              <p>Permission boundaries, explicit human requests, security signals, billing or money issues, low-confidence safety answers, and repeated ORB failure can create deterministic escalations.</p>
              <p>The originating interaction remains attached through its continuation reference so context is not lost.</p>
              <p>Additional channels remain connector-dependent; the escalation record and ownership workflow are local and operational.</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
