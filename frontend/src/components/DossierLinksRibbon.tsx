import { useEffect, useState, type ReactNode } from 'react'
import { ExternalLink, Globe, Image, Link2, MapPin, Newspaper, Phone, Radar, RefreshCcw, Search, Trash2, Users } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { ExternalLinkRecord } from '@/types'

const PLATFORM_ICONS: Record<string, { icon: ReactNode; color: string }> = {
  google_search: { icon: <Search size={14} />, color: 'text-blue-400 hover:bg-blue-950/40' },
  google_maps: { icon: <MapPin size={14} />, color: 'text-emerald-400 hover:bg-emerald-950/40' },
  facebook: { icon: <Link2 size={14} />, color: 'text-indigo-400 hover:bg-indigo-950/40' },
  linkedin: { icon: <Link2 size={14} />, color: 'text-cyan-400 hover:bg-cyan-950/40' },
  github: { icon: <Link2 size={14} />, color: 'text-purple-400 hover:bg-purple-950/40' },
  domain_lookup: { icon: <Globe size={14} />, color: 'text-amber-400 hover:bg-amber-950/40' },
  company_website: { icon: <Globe size={14} />, color: 'text-zinc-400 hover:bg-zinc-800/40' },
  sec_edgar: { icon: <Globe size={14} />, color: 'text-emerald-300 hover:bg-emerald-950/40' },
  court_records: { icon: <Search size={14} />, color: 'text-amber-300 hover:bg-amber-950/40' },
  state_sos: { icon: <MapPin size={14} />, color: 'text-blue-300 hover:bg-blue-950/40' },
  patent_uspto: { icon: <Link2 size={14} />, color: 'text-purple-300 hover:bg-purple-950/40' },
  professional_license: { icon: <Globe size={14} />, color: 'text-cyan-300 hover:bg-cyan-950/40' },
  trademark_uspto: { icon: <Search size={14} />, color: 'text-violet-400 hover:bg-violet-950/40' },
  phone_public: { icon: <Phone size={14} />, color: 'text-emerald-400 hover:bg-emerald-950/40' },
  property_records: { icon: <MapPin size={14} />, color: 'text-orange-400 hover:bg-orange-950/40' },
  public_images: { icon: <Image size={14} />, color: 'text-pink-400 hover:bg-pink-950/40' },
  associate_public: { icon: <Users size={14} />, color: 'text-indigo-400 hover:bg-indigo-950/40' },
  custom: { icon: <Link2 size={14} />, color: 'text-teal-400 hover:bg-teal-950/40' },
}

const STATUS_BADGES: Record<string, string> = {
  generated_search: 'border-amber-500/30 text-amber-500 bg-amber-950/20',
  detected: 'border-blue-500/30 text-blue-400 bg-blue-950/20',
  verified: 'border-emerald-500/30 text-emerald-400 bg-emerald-950/20',
  manual: 'border-zinc-500/30 text-zinc-300 bg-zinc-800/20',
  broken: 'border-rose-500/30 text-rose-400 bg-rose-950/20',
}

type ResearchItem = {
  research_id: string
  category: string
  title: string
  url: string
  snippet?: string | null
  source_name?: string | null
  provider: string
  published_at?: string | null
  captured_at?: string | null
  confidence?: number
  verification_state?: string
}

function researchDate(value?: string | null) {
  if (!value) return ''
  const parsed = new Date(value)
  if (!Number.isNaN(parsed.getTime())) return parsed.toLocaleDateString()
  return String(value).replace('T', ' ').slice(0, 10)
}

export function DossierLinksRibbon({ contactId }: { contactId: string }) {
  const [links, setLinks] = useState<ExternalLinkRecord[]>([])
  const [research, setResearch] = useState<ResearchItem[]>([])
  const [loading, setLoading] = useState(false)
  const [researchLoading, setResearchLoading] = useState(false)

  const fetchLinks = async () => {
    try {
      const response = await api.get(`/cali/contacts/${contactId}/external-links`)
      setLinks(Array.isArray(response.data) ? response.data : [])
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load dossier references'
      toast.error(message)
    }
  }

  const fetchResearch = async () => {
    try {
      const response = await api.get(`/cali/intelligence/contacts/${contactId}/research`, { params: { limit: 18 } })
      setResearch(Array.isArray(response.data?.items) ? response.data.items : [])
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load dossier research'
      toast.error(message)
    }
  }

  const handleGenerate = async () => {
    setLoading(true)
    try {
      await api.post(`/cali/contacts/${contactId}/dossier/expand`)
      await fetchLinks()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Reference generation failed'
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }

  const handleResearch = async () => {
    setResearchLoading(true)
    try {
      const response = await api.post(`/cali/intelligence/contacts/${contactId}/research`, {
        mode: 'full',
        timespan: '30d',
        max_results: 18,
        business_scope: 'all',
      })
      const items = Array.isArray(response.data?.items) ? response.data.items : []
      setResearch(items)
      const providers = Array.isArray(response.data?.providers) ? response.data.providers.join(', ') : ''
      toast.success(`Research completed · ${items.length} sources${providers ? ` · ${providers}` : ''}`)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Contact research failed'
      toast.error(message)
    } finally {
      setResearchLoading(false)
    }
  }

  const handleDelete = async (event: React.MouseEvent, id: number) => {
    event.stopPropagation()
    event.preventDefault()
    if (!window.confirm('Remove this external reference from the dossier?')) return
    try {
      await api.delete(`/cali/contacts/${contactId}/external-links/${id}`)
      await fetchLinks()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Reference removal failed'
      toast.error(message)
    }
  }

  const executeLink = (url: string) => {
    const shell = (window as Window & { electron?: { shell?: { openExternal?: (u: string) => void } } }).electron?.shell
    if (shell?.openExternal) {
      shell.openExternal(url)
      return
    }
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  useEffect(() => {
    if (!contactId) return
    void Promise.all([fetchLinks(), fetchResearch()])
  }, [contactId])

  return (
    <div className="w-full rounded border border-zinc-800 bg-zinc-950 p-3 font-mono">
      <div className="mb-2 flex items-center justify-between border-b border-zinc-800 pb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-zinc-400">External References</span>
          <span className="rounded border border-zinc-800 bg-zinc-900 px-1.5 py-0.5 text-[10px] text-zinc-500">{links.length} linked</span>
        </div>
        <Button variant="secondary" size="sm" disabled={loading} onClick={handleGenerate} className="h-7 text-[11px]">
          <RefreshCcw size={10} className={loading ? 'animate-spin' : ''} />
          Expand Dossier
        </Button>
      </div>

      {links.length === 0 ? (
        <div className="py-1 text-[11px] italic text-zinc-600">No external references are linked to this dossier. Generate references to create standard search and verification paths.</div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {links.map((link) => {
            const display = PLATFORM_ICONS[link.platform] || PLATFORM_ICONS.custom
            return (
              <div
                key={link.id}
                onClick={() => executeLink(link.url)}
                className={`group flex cursor-pointer items-center gap-2 rounded border border-zinc-800 bg-zinc-900/60 px-2 py-1 text-xs transition-all ${display.color}`}
                title={`Destination: ${link.url}\nType: ${link.link_type}\nSource: ${link.source}`}
              >
                <div className="flex items-center gap-1.5">
                  {display.icon}
                  <span className="font-medium text-zinc-300">{link.label}</span>
                </div>
                <span className={`rounded border px-1 text-[9px] uppercase tracking-tighter ${STATUS_BADGES[link.verified_status] || STATUS_BADGES.manual}`}>
                  {String(link.verified_status || 'manual').replace('_', ' ')}
                </span>
                <ExternalLink size={10} className="opacity-40 group-hover:opacity-100" />
                <button
                  onClick={(event) => handleDelete(event, link.id)}
                  className="ml-1 text-zinc-600 opacity-0 transition-opacity hover:text-rose-400 group-hover:opacity-100"
                  title="Remove reference"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            )
          })}
        </div>
      )}

      <div className="mt-3 border-t border-zinc-800 pt-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <Radar size={13} className="shrink-0 text-cyan-400" />
            <span className="text-xs font-bold uppercase tracking-wider text-zinc-400">Contact Research</span>
            <span className="rounded border border-zinc-800 bg-zinc-900 px-1.5 py-0.5 text-[10px] text-zinc-500">{research.length} sources</span>
          </div>
          <Button variant="secondary" size="sm" disabled={researchLoading} onClick={handleResearch} className="h-7 shrink-0 text-[11px]">
            <Newspaper size={11} className={researchLoading ? 'animate-pulse' : ''} />
            Research Latest
          </Button>
        </div>

        <div className="mb-2 text-[10px] leading-4 text-zinc-600">
          Searches public web, news, and event sources. Results remain unverified evidence until you review them.
        </div>

        {research.length === 0 ? (
          <div className="py-1 text-[11px] italic text-zinc-600">No public-source research is stored for this dossier yet.</div>
        ) : (
          <div className="space-y-1.5">
            {research.slice(0, 12).map((item) => (
              <button
                key={item.research_id}
                type="button"
                onClick={() => executeLink(item.url)}
                className="block w-full rounded border border-zinc-800 bg-zinc-900/45 px-2.5 py-2 text-left transition hover:border-cyan-900/60 hover:bg-cyan-950/10"
                title={item.url}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[11px] font-medium text-zinc-200">{item.title}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[9px] uppercase tracking-wide text-zinc-600">
                      <span className="text-cyan-500">{item.category}</span>
                      <span>{item.provider}</span>
                      {item.source_name ? <span className="normal-case tracking-normal">{item.source_name}</span> : null}
                      {item.published_at ? <span>{researchDate(item.published_at)}</span> : null}
                    </div>
                    {item.snippet ? <div className="mt-1 line-clamp-2 text-[10px] leading-4 text-zinc-500">{item.snippet}</div> : null}
                  </div>
                  <ExternalLink size={10} className="mt-0.5 shrink-0 text-zinc-600" />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
