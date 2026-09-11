import { useEffect, useMemo, useState } from 'react'
import { DollarSign, Save, TrendingDown, TrendingUp } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { DossierValueProfile } from '@/types'

export type DossierValueDraft = {
  real_value: number
  cost: number
  intrinsic_value: number
  future_potential_value: number
  confidence: number
  notes: string
  source: string
}

type Props = {
  profile?: DossierValueProfile | null
  contextLabel?: string
  saving?: boolean
  onSave: (draft: DossierValueDraft) => void
}

function money(value: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(Number(value || 0))
}

function numberValue(value: string) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0
}

export function DossierValueProfilePanel({ profile, contextLabel = 'All contexts', saving = false, onSave }: Props) {
  const [draft, setDraft] = useState<DossierValueDraft>({
    real_value: 0,
    cost: 0,
    intrinsic_value: 0,
    future_potential_value: 0,
    confidence: 0,
    notes: '',
    source: 'operator',
  })

  useEffect(() => {
    setDraft({
      real_value: Number(profile?.real_value || 0),
      cost: Number(profile?.cost || 0),
      intrinsic_value: Number(profile?.intrinsic_value || 0),
      future_potential_value: Number(profile?.future_potential_value || 0),
      confidence: Number(profile?.confidence || 0),
      notes: profile?.notes || '',
      source: profile?.source && profile.source !== 'unscored' ? profile.source : 'operator',
    })
  }, [profile])

  const netReal = useMemo(() => draft.real_value - draft.cost, [draft.real_value, draft.cost])
  const netTotal = useMemo(
    () => netReal + draft.intrinsic_value + draft.future_potential_value,
    [netReal, draft.intrinsic_value, draft.future_potential_value],
  )
  const positive = netTotal >= 0
  const TrendIcon = positive ? TrendingUp : TrendingDown

  return (
    <section className="rounded-xl border border-blue-500/25 bg-[#0b1325] p-4 shadow-lg shadow-black/20">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.15em] text-blue-400">
            <DollarSign className="size-3.5" />VIV Value Profile
          </div>
          <div className="mt-1 text-xs text-zinc-500">{contextLabel}</div>
        </div>
        <Badge variant="muted">Confidence {Math.round(draft.confidence)}%</Badge>
      </div>

      <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-950/55 p-4">
        <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-zinc-500">Net Total Value</div>
        <div className={`mt-1 flex items-center gap-2 text-3xl font-semibold ${positive ? 'text-emerald-400' : 'text-rose-400'}`}>
          <TrendIcon className="size-6" />{money(netTotal)}
        </div>
        <div className="mt-1 text-[11px] text-zinc-600">Real Value − Cost + Intrinsic Value + Future Potential Value</div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-emerald-900/40 bg-emerald-950/10 p-3">
          <div className="text-[9px] font-bold uppercase tracking-wide text-emerald-500">Real Value</div>
          <div className="mt-1 text-xl font-semibold text-emerald-300">{money(draft.real_value)}</div>
          <div className="mt-1 text-[10px] leading-4 text-zinc-600">Actual dollar value already produced.</div>
        </div>
        <div className="rounded-lg border border-rose-900/40 bg-rose-950/10 p-3">
          <div className="text-[9px] font-bold uppercase tracking-wide text-rose-500">Cost</div>
          <div className="mt-1 text-xl font-semibold text-rose-300">{money(draft.cost)}</div>
          <div className="mt-1 text-[10px] leading-4 text-zinc-600">Actual dollars spent, lost, or attributable to the relationship.</div>
        </div>
        <div className="rounded-lg border border-cyan-900/40 bg-cyan-950/10 p-3">
          <div className="text-[9px] font-bold uppercase tracking-wide text-cyan-500">Intrinsic Value</div>
          <div className="mt-1 text-xl font-semibold text-cyan-300">{money(draft.intrinsic_value)}</div>
          <div className="mt-1 text-[10px] leading-4 text-zinc-600">Present economic relationship value not already counted as realized dollars.</div>
        </div>
        <div className="rounded-lg border border-violet-900/40 bg-violet-950/10 p-3">
          <div className="text-[9px] font-bold uppercase tracking-wide text-violet-500">Future Potential Value</div>
          <div className="mt-1 text-xl font-semibold text-violet-300">{money(draft.future_potential_value)}</div>
          <div className="mt-1 text-[10px] leading-4 text-zinc-600">Reasonable forward dollar potential of the relationship.</div>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950/45 px-3 py-2.5 text-sm">
        <span className="text-zinc-500">Net Real Contribution</span>
        <span className={`font-semibold ${netReal >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{money(netReal)}</span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="text-xs text-zinc-400">Real Value ($)<Input className="mt-1" type="number" min="0" step="0.01" value={draft.real_value} onChange={(event) => setDraft({ ...draft, real_value: numberValue(event.target.value) })} /></label>
        <label className="text-xs text-zinc-400">Cost ($)<Input className="mt-1" type="number" min="0" step="0.01" value={draft.cost} onChange={(event) => setDraft({ ...draft, cost: numberValue(event.target.value) })} /></label>
        <label className="text-xs text-zinc-400">Intrinsic Value ($)<Input className="mt-1" type="number" min="0" step="0.01" value={draft.intrinsic_value} onChange={(event) => setDraft({ ...draft, intrinsic_value: numberValue(event.target.value) })} /></label>
        <label className="text-xs text-zinc-400">Future Potential Value ($)<Input className="mt-1" type="number" min="0" step="0.01" value={draft.future_potential_value} onChange={(event) => setDraft({ ...draft, future_potential_value: numberValue(event.target.value) })} /></label>
        <label className="text-xs text-zinc-400 sm:col-span-2">Confidence (0–100)<Input className="mt-1" type="number" min="0" max="100" step="1" value={draft.confidence} onChange={(event) => setDraft({ ...draft, confidence: Math.min(100, numberValue(event.target.value)) })} /></label>
        <label className="text-xs text-zinc-400 sm:col-span-2">Value rationale / evidence<Textarea className="mt-1" value={draft.notes} onChange={(event) => setDraft({ ...draft, notes: event.target.value })} placeholder="Why this person has this intrinsic and future potential value; note factual sources, assumptions, introductions, opportunities, or relationship factors." /></label>
      </div>

      <div className="mt-3 flex items-center justify-between gap-3 border-t border-zinc-800 pt-3">
        <div className="text-[10px] leading-4 text-zinc-600">Source: {draft.source || 'operator'}{profile?.updated_at ? ` · updated ${new Date(profile.updated_at).toLocaleDateString()}` : ''}</div>
        <Button size="sm" variant="primary" disabled={saving} onClick={() => onSave(draft)}><Save className="size-3.5" />Save Value Profile</Button>
      </div>
    </section>
  )
}
