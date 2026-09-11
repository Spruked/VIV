import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays,
  Check,
  ExternalLink,
  FileImage,
  FolderOpen,
  Link2,
  Mail,
  Network,
  Plus,
  RefreshCw,
  ScanSearch,
  ShieldQuestion,
  Trash2,
  Upload,
  UserRound,
  X,
} from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { DossierLinksRibbon } from '@/components/DossierLinksRibbon'
import { SectionHeader } from '@/components/SectionHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Table, Td, Th } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { updateVIVContext } from '@/lib/orb-integration'
import { compactDate, initials } from '@/lib/utils'
import { useBusinessContext } from '@/providers/BusinessContextProvider'
import type { BusinessRole, Contact, DossierMedia } from '@/types'

const relationshipTypes = [
  'personal', 'family', 'professional', 'business', 'vendor', 'partner',
  'service_provider', 'legal', 'financial', 'medical', 'community', 'other',
]

const lifecycleStages = [
  { id: 'prospect', label: 'Horizon' },
  { id: 'qualified', label: 'Evaluating' },
  { id: 'contacted', label: 'Engaged' },
  { id: 'meeting_scheduled', label: 'Active' },
  { id: 'proposal', label: 'Advancing' },
  { id: 'won', label: 'Established' },
  { id: 'lost', label: 'Archive' },
]
const mediaKinds = ['person', 'place', 'building', 'other'] as const
const vivCommunicationsUrl = String(import.meta.env.VITE_PRIME_MAIL_URL || 'http://127.0.0.1:19000').replace(/\/$/, '')

function field(value?: string | null, fallback = '—') {
  return value && String(value).trim() ? value : fallback
}

function formatPercent(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `${Math.round(Number(value) * 100)}%`
}

function lifecycleLabel(value?: string | null) {
  if (!value) return '—'
  return lifecycleStages.find((stage) => stage.id === value)?.label || value.replaceAll('_', ' ')
}

type ConnectionItem = {
  edge_id?: string
  candidate_id?: string
  other_party?: string
  other_name?: string
  predicate?: string
  confidence?: number
  edge_kind?: 'verified' | 'candidate'
  rationale?: string
}

type ConnectionsResponse = {
  party_id: string
  verified: ConnectionItem[]
  candidates: ConnectionItem[]
  latest_relevance?: {
    relevance_score?: number
    connection_strength?: number
    degrees?: number | null
    factors?: string
    rationale?: string
  } | null
}

type DossierPackage = {
  package_dir?: string
  manifest_path?: string
  inventory?: Record<string, string[]>
}

export default function Contacts() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { businessScope, activeBusiness } = useBusinessContext()
  const [query, setQuery] = useState('')
  const [relationshipType, setRelationshipType] = useState('')
  const [segment, setSegment] = useState('')
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [operationTracked, setOperationTracked] = useState(false)
  const [roleDraft, setRoleDraft] = useState('')
  const [segmentDraft, setSegmentDraft] = useState('')
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [imageDraft, setImageDraft] = useState({ media_kind: 'person', label: '', notes: '', is_primary: false })
  const [form, setForm] = useState({
    name: '', email: '', phone: '', type: 'professional', stage: '', notes: '', relationship: '', segments: '',
  })

  const contactsQuery = useQuery({
    queryKey: ['contacts-intelligence', query, relationshipType, segment, businessScope],
    queryFn: async () => {
      const response = await api.get('/cali/intelligence/contacts', {
        params: { query: query || undefined, business_scope: businessScope, segment: segment || undefined },
      })
      return response.data as { contacts: Contact[]; count: number }
    },
  })

  const segmentsQuery = useQuery({
    queryKey: ['contact-segments', businessScope],
    queryFn: async () => {
      const response = await api.get('/cali/intelligence/segments', { params: { business_scope: businessScope } })
      return response.data as { segments: Array<{ name: string; count: number }> }
    },
  })

  const contacts = useMemo(() => {
    const all = contactsQuery.data?.contacts || []
    if (!relationshipType) return all
    return all.filter((contact) => (contact.type || contact.contact_type || '').toLowerCase() === relationshipType)
  }, [contactsQuery.data?.contacts, relationshipType])

  const connectionsQuery = useQuery({
    queryKey: ['contact-connections', selectedContact?.party_id, businessScope],
    enabled: Boolean(selectedContact?.party_id),
    queryFn: async () => {
      const response = await api.get(`/cali/intelligence/parties/${encodeURIComponent(String(selectedContact?.party_id))}/connections`, {
        params: { business_scope: businessScope },
      })
      return response.data as ConnectionsResponse
    },
  })

  const mediaQuery = useQuery({
    queryKey: ['contact-media', selectedContact?.id],
    enabled: Boolean(selectedContact?.id),
    queryFn: async () => {
      const response = await api.get(`/cali/intelligence/contacts/${encodeURIComponent(String(selectedContact?.id))}/media`)
      return response.data as { media: DossierMedia[]; count: number }
    },
  })

  const packageQuery = useQuery({
    queryKey: ['dossier-package', selectedContact?.id],
    enabled: Boolean(selectedContact?.id),
    queryFn: async () => {
      const response = await api.get(`/cali/intelligence/contacts/${encodeURIComponent(String(selectedContact?.id))}/package`)
      return response.data as DossierPackage
    },
  })

  useEffect(() => {
    const requestedEmail = searchParams.get('email')?.trim().toLowerCase()
    if (!requestedEmail || selectedContact) return
    const match = contacts.find((contact) => contact.email?.trim().toLowerCase() === requestedEmail)
    if (match) {
      setSelectedContact(match)
      setShowAddForm(false)
    }
  }, [contacts, searchParams, selectedContact])

  useEffect(() => {
    if (!selectedContact || businessScope === 'all') {
      setRoleDraft('')
      setSegmentDraft('')
      return
    }
    const role = selectedContact.business_roles?.find((item) => item.business_id === businessScope)
    setRoleDraft(role?.role || '')
    setSegmentDraft((role?.segment_tags || []).join(', '))
  }, [selectedContact, businessScope])

  useEffect(() => {
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ['contacts-intelligence'] })
      void queryClient.invalidateQueries({ queryKey: ['contact-segments'] })
    }
    window.addEventListener('cali-contacts-imported', refresh)
    return () => window.removeEventListener('cali-contacts-imported', refresh)
  }, [queryClient])

  useEffect(() => {
    updateVIVContext({
      currentView: 'contacts',
      activeFilters: {
        search: query,
        type: relationshipType || 'all',
        segment: segment || 'all',
        businessScope,
      },
      selectedContact,
      lastAction: selectedContact?.id ? `dossier:${selectedContact.id}` : 'contacts_directory',
    })
  }, [query, relationshipType, segment, businessScope, selectedContact])

  const createContact = useMutation({
    mutationFn: async () => {
      const response = await api.post('/cali/contacts', {
        name: form.name,
        email: form.email || undefined,
        phone: form.phone || undefined,
        contact_type: form.type,
        crm_stage: operationTracked ? form.stage || 'prospect' : undefined,
        notes: form.notes || undefined,
        priority: 1,
        owner: 'bryan@spruked.com',
      })
      return response.data as Contact
    },
    onSuccess: async (created) => {
      const contactId = created?.id || created?.contact_id
      const createdEmail = form.email.trim().toLowerCase()
      const createdName = form.name.trim()
      if (contactId) await api.post('/cali/intelligence/dossiers/packages/ensure', { contact_ids: [String(contactId)] })
      if (businessScope !== 'all' && contactId) {
        await api.post(`/cali/intelligence/contacts/${encodeURIComponent(String(contactId))}/business-role`, {
          business_id: businessScope,
          role: form.relationship || undefined,
          segment_tags: form.segments.split(',').map((item) => item.trim()).filter(Boolean),
          visibility: 'scoped',
        })
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['contacts-intelligence'] }),
        queryClient.invalidateQueries({ queryKey: ['contact-segments'] }),
        queryClient.invalidateQueries({ queryKey: ['pipeline'] }),
      ])
      const canonicalResponse = await api.get('/cali/intelligence/contacts', {
        params: {
          query: createdEmail || createdName || undefined,
          business_scope: businessScope,
        },
      })
      const canonicalContacts = (canonicalResponse.data?.contacts || []) as Contact[]
      const canonical = canonicalContacts.find((item) =>
        (contactId && String(item.id || item.contact_id) === String(contactId)) ||
        (createdEmail && item.email?.trim().toLowerCase() === createdEmail),
      ) || canonicalContacts[0] || null
      toast.success('Dossier and package created')
      setForm({ name: '', email: '', phone: '', type: 'professional', stage: '', notes: '', relationship: '', segments: '' })
      setOperationTracked(false)
      setShowAddForm(false)
      setSelectedContact(canonical)
    },
    onError: (error) => toast.error(error.message),
  })

  const saveBusinessRole = useMutation({
    mutationFn: async () => {
      if (!selectedContact?.id || businessScope === 'all') throw new Error('Select a business context first')
      return api.post(`/cali/intelligence/contacts/${encodeURIComponent(String(selectedContact.id))}/business-role`, {
        business_id: businessScope,
        role: roleDraft || undefined,
        segment_tags: segmentDraft.split(',').map((item) => item.trim()).filter(Boolean),
        visibility: 'scoped',
      })
    },
    onSuccess: async () => {
      toast.success('Business context saved')
      await queryClient.invalidateQueries({ queryKey: ['contacts-intelligence'] })
      await queryClient.invalidateQueries({ queryKey: ['contact-segments'] })
    },
    onError: (error) => toast.error(error.message),
  })

  const scanConnections = useMutation({
    mutationFn: async () => api.post('/cali/intelligence/scan', null, { params: { business_scope: businessScope } }),
    onSuccess: async (response) => {
      const count = Number(response.data?.candidates_written || 0)
      toast.success(`Connection scan completed · ${count} candidate associations processed`)
      await queryClient.invalidateQueries({ queryKey: ['contact-connections'] })
    },
    onError: (error) => toast.error(error.message),
  })

  const recalculateRelevance = useMutation({
    mutationFn: async () => {
      if (!selectedContact?.party_id) throw new Error('Canonical party id is not available yet')
      return api.post(`/cali/intelligence/parties/${encodeURIComponent(selectedContact.party_id)}/relevance/recalculate`, {
        business_scope: businessScope,
      })
    },
    onSuccess: async (response) => {
      toast.success(`Relevance recalculated · ${Math.round(Number(response.data?.relevance_score || 0))}`)
      await queryClient.invalidateQueries({ queryKey: ['contact-connections'] })
      await queryClient.invalidateQueries({ queryKey: ['contacts-intelligence'] })
    },
    onError: (error) => toast.error(error.message),
  })

  const reviewCandidate = useMutation({
    mutationFn: async ({ candidateId, decision }: { candidateId: string; decision: 'accept' | 'reject' }) =>
      api.post(`/cali/intelligence/candidates/${encodeURIComponent(candidateId)}/review`, { decision }),
    onSuccess: async (_, variables) => {
      toast.success(variables.decision === 'accept' ? 'Relationship verified' : 'Relationship rejected')
      await queryClient.invalidateQueries({ queryKey: ['contact-connections'] })
    },
    onError: (error) => toast.error(error.message),
  })

  const uploadImage = useMutation({
    mutationFn: async () => {
      if (!selectedContact?.id) throw new Error('Select a dossier first')
      if (!imageFile) throw new Error('Choose an image first')
      const body = new FormData()
      body.append('file', imageFile)
      body.append('media_kind', imageDraft.media_kind)
      body.append('label', imageDraft.label)
      body.append('notes', imageDraft.notes)
      body.append('is_primary', String(imageDraft.is_primary))
      return api.post(`/cali/intelligence/contacts/${encodeURIComponent(String(selectedContact.id))}/images`, body, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    onSuccess: async () => {
      toast.success('Image saved to the dossier package')
      setImageFile(null)
      setImageDraft({ media_kind: 'person', label: '', notes: '', is_primary: false })
      await queryClient.invalidateQueries({ queryKey: ['contact-media', selectedContact?.id] })
      await queryClient.invalidateQueries({ queryKey: ['dossier-package', selectedContact?.id] })
    },
    onError: (error) => toast.error(error.message),
  })

  const setPrimaryMedia = useMutation({
    mutationFn: async (mediaId: string) => {
      if (!selectedContact?.id) throw new Error('Select a dossier first')
      return api.post(`/cali/intelligence/contacts/${encodeURIComponent(String(selectedContact.id))}/media/${encodeURIComponent(mediaId)}/primary`)
    },
    onSuccess: async () => {
      toast.success('Primary dossier image set')
      await queryClient.invalidateQueries({ queryKey: ['contact-media', selectedContact?.id] })
    },
    onError: (error) => toast.error(error.message),
  })

  const deleteMedia = useMutation({
    mutationFn: async (mediaId: string) => {
      if (!selectedContact?.id) throw new Error('Select a dossier first')
      return api.delete(`/cali/intelligence/contacts/${encodeURIComponent(String(selectedContact.id))}/images/${encodeURIComponent(mediaId)}`)
    },
    onSuccess: async () => {
      toast.success('Image removed from the dossier package')
      await queryClient.invalidateQueries({ queryKey: ['contact-media', selectedContact?.id] })
      await queryClient.invalidateQueries({ queryKey: ['dossier-package', selectedContact?.id] })
    },
    onError: (error) => toast.error(error.message),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    createContact.mutate()
  }

  function selectContact(contact: Contact) {
    setSelectedContact(contact)
    setShowAddForm(false)
  }

  function openVIVCommunications(contact: Contact) {
    const params = new URLSearchParams()
    if (contact.email) params.set('contact', contact.email)
    if (businessScope && businessScope !== 'all') params.set('business_scope', businessScope)
    const url = `${vivCommunicationsUrl}${params.toString() ? `/?${params}` : ''}`
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  function openCalendar(contact: Contact) {
    const params = new URLSearchParams()
    if (contact.id) params.set('contact_id', String(contact.id))
    if (contact.name) params.set('contact', contact.name)
    if (businessScope && businessScope !== 'all') params.set('business_scope', businessScope)
    navigate(`/calendar${params.toString() ? `?${params}` : ''}`)
  }

  const selectedType = selectedContact?.type || selectedContact?.contact_type || 'contact'
  const selectedStage = selectedContact?.crm_stage
  const relevance = connectionsQuery.data?.latest_relevance || selectedContact?.relevance
  const verifiedConnections = connectionsQuery.data?.verified || []
  const candidateConnections = connectionsQuery.data?.candidates || []
  const media = mediaQuery.data?.media || []
  const primaryMedia = media.find((item) => item.is_primary) || media[0]
  const selectedBusinessRole: BusinessRole | undefined = businessScope === 'all'
    ? undefined
    : selectedContact?.business_roles?.find((item) => item.business_id === businessScope)

  return (
    <div>
      <SectionHeader
        title="Dossier Vault"
        detail="Canonical subjects with contact points, relationships, business context, evidence, communications, images, and lifecycle state."
        action={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => scanConnections.mutate()} disabled={scanConnections.isPending}>
              <ScanSearch className="size-4" />Discover Connections
            </Button>
            <Button variant="primary" onClick={() => { setSelectedContact(null); setShowAddForm(true) }}>
              <Plus className="size-4" />Create Dossier
            </Button>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-blue-900/60 bg-[#0b1633]/80 px-4 py-3 text-sm">
        <span className="text-zinc-500">Business Context</span>
        <Badge>{activeBusiness?.label || 'All contexts'}</Badge>
        <span className="ml-2 text-zinc-500">Group or Segment</span>
        <Select className="h-8 w-48" value={segment} onChange={(event) => setSegment(event.target.value)}>
          <option value="">All groups</option>
          {(segmentsQuery.data?.segments || []).map((item) => <option key={item.name} value={item.name}>{item.name} ({item.count})</option>)}
        </Select>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_29rem]">
        <Card className="min-w-0">
          <CardHeader>
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div><CardTitle>Subject Directory</CardTitle><div className="mt-1 text-xs text-zinc-500">{contacts.length} subjects in the current context</div></div>
              <div className="flex flex-wrap gap-2">
                <Input className="w-72 max-w-full" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search subject, contact point, notes, or location" />
                <Select value={relationshipType} onChange={(event) => setRelationshipType(event.target.value)}>
                  <option value="">All relationships</option>
                  {relationshipTypes.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}
                </Select>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {contacts.length ? (
              <div className="overflow-x-auto">
                <Table>
                  <thead><tr><Th>Subject</Th><Th>Relationship</Th><Th>Groups</Th><Th>Email</Th><Th>Relevance</Th></tr></thead>
                  <tbody>
                    {contacts.map((contact) => {
                      const selected = selectedContact && String(selectedContact.id || selectedContact.email) === String(contact.id || contact.email)
                      const contextRole = businessScope === 'all' ? contact.business_roles?.[0] : contact.business_roles?.find((role) => role.business_id === businessScope)
                      return (
                        <tr key={contact.id || contact.email || contact.name} className={`cursor-pointer transition ${selected ? 'bg-blue-950/35 ring-1 ring-inset ring-blue-500/30' : 'hover:bg-zinc-900/40'}`} onClick={() => selectContact(contact)}>
                          <Td><div className="flex items-center gap-3"><div className={`flex size-9 items-center justify-center rounded-lg text-xs font-semibold ${selected ? 'bg-blue-600 text-white' : 'bg-zinc-900 text-zinc-300'}`}>{initials(contact.name)}</div><div className="min-w-0"><div className="truncate font-medium text-zinc-100">{contact.name}</div><div className="truncate text-xs text-zinc-500">{contact.phone || 'No phone'}</div></div></div></Td>
                          <Td><Badge>{contextRole?.role || contact.type || contact.contact_type || 'contact'}</Badge></Td>
                          <Td><div className="flex max-w-52 flex-wrap gap-1">{(contact.segments || []).slice(0, 3).map((item) => <Badge key={item} variant="muted">{item}</Badge>)}</div></Td>
                          <Td><div className="max-w-64 truncate">{contact.email || 'No email'}</div></Td>
                          <Td>{contact.relevance?.relevance_score !== undefined ? Math.round(contact.relevance.relevance_score) : '—'}</Td>
                        </tr>
                      )
                    })}
                  </tbody>
                </Table>
              </div>
            ) : <EmptyState title="No subjects found" detail="Change the business context, group, relationship, or search filters." />}
          </CardContent>
        </Card>

        <div className="min-w-0">
          {showAddForm ? (
            <Card>
              <CardHeader><CardTitle>New Dossier</CardTitle></CardHeader>
              <CardContent>
                <form className="flex flex-col gap-3" onSubmit={submit}>
                  <Input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Full name" />
                  <Input value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} placeholder="Email" type="email" />
                  <Input value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} placeholder="Phone" />
                  <Select value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value })}>{relationshipTypes.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}</Select>
                  {businessScope !== 'all' ? <><Input value={form.relationship} onChange={(event) => setForm({ ...form, relationship: event.target.value })} placeholder={`Relationship or role in ${activeBusiness?.label || businessScope}`} /><Input value={form.segments} onChange={(event) => setForm({ ...form, segments: event.target.value })} placeholder="Groups or segments, comma separated" /></> : null}
                  <Textarea value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} placeholder="Notes and verified context" />
                  <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950/40 px-3 py-2 text-sm text-zinc-300"><input type="checkbox" checked={operationTracked} onChange={(event) => setOperationTracked(event.target.checked)} />Track this dossier on the Operation Board</label>
                  {operationTracked ? <Select value={form.stage} onChange={(event) => setForm({ ...form, stage: event.target.value })}><option value="">Choose lifecycle state</option>{lifecycleStages.map((stage) => <option key={stage.id} value={stage.id}>{stage.label}</option>)}</Select> : null}
                  <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setShowAddForm(false)}>Cancel</Button><Button variant="primary" disabled={createContact.isPending}><Plus className="size-4" />Create dossier</Button></div>
                </form>
              </CardContent>
            </Card>
          ) : selectedContact ? (
            <div className="overflow-hidden rounded-xl border border-blue-500/25 bg-[#0d1528] shadow-2xl shadow-black/20">
              <div className="border-b border-blue-500/20 bg-[#111d37] px-4 py-3">
                <div className="flex items-center justify-between gap-3"><div><div className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-400">Dossier</div><div className="mt-1 text-xs text-zinc-500">Identity · contact points · relationships · context · evidence</div></div><Button size="sm" variant="secondary" onClick={() => window.open(window.location.href, '_blank', 'noopener,noreferrer')}><ExternalLink className="size-3.5" />Open separately</Button></div>
              </div>

              <div className="max-h-[calc(100vh-15rem)] overflow-y-auto p-4">
                <div className="flex items-start gap-3 rounded-xl border border-zinc-800 bg-zinc-950/55 p-4">
                  {primaryMedia?.image_url ? <img src={primaryMedia.image_url} alt={primaryMedia.label || selectedContact.name} className="size-14 shrink-0 rounded-xl object-cover" /> : <div className="flex size-14 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-cyan-500 text-lg font-bold text-white">{initials(selectedContact.name)}</div>}
                  <div className="min-w-0 flex-1"><h2 className="truncate text-xl font-semibold text-white">{selectedContact.name}</h2><div className="mt-1 truncate text-sm text-zinc-400">{field(selectedContact.email, 'No email')}</div><div className="mt-3 flex flex-wrap gap-2"><Badge>{selectedType.replaceAll('_', ' ')}</Badge>{selectedBusinessRole?.role ? <Badge variant="muted">{selectedBusinessRole.role}</Badge> : null}{(selectedContact.segments || []).map((item) => <Badge key={item} variant="muted">{item}</Badge>)}</div></div>
                </div>

                <div className="mt-4 text-[10px] font-bold uppercase tracking-[0.15em] text-blue-400">Identity & Contact Points</div>
                <div className="mt-2 overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/45 text-sm">
                  <div className="grid grid-cols-[7rem_1fr] gap-3 border-b border-zinc-800 px-3 py-2.5"><span className="text-zinc-500">Email</span><span className="break-all text-zinc-200">{field(selectedContact.email)}</span></div>
                  <div className="grid grid-cols-[7rem_1fr] gap-3 border-b border-zinc-800 px-3 py-2.5"><span className="text-zinc-500">Phone</span><span className="text-zinc-200">{field(selectedContact.phone)}</span></div>
                  <div className="grid grid-cols-[7rem_1fr] gap-3 px-3 py-2.5"><span className="text-zinc-500">Location</span><span className="text-zinc-200">{field(selectedContact.address)}</span></div>
                </div>

                <div className="mt-4 text-[10px] font-bold uppercase tracking-[0.15em] text-blue-400">Context & Follow-up</div>
                <div className="mt-2 overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/45 text-sm">
                  <div className="grid grid-cols-[7rem_1fr] gap-3 border-b border-zinc-800 px-3 py-2.5"><span className="text-zinc-500">Last contact</span><span className="text-zinc-200">{compactDate(selectedContact.last_contacted_at)}</span></div>
                  <div className="grid grid-cols-[7rem_1fr] gap-3 border-b border-zinc-800 px-3 py-2.5"><span className="text-zinc-500">Next action</span><span className="text-zinc-200">{compactDate(selectedContact.next_follow_up_at)}</span></div>
                  <div className="grid grid-cols-[7rem_1fr] gap-3 px-3 py-2.5"><span className="text-zinc-500">Contexts</span><span className="text-zinc-200">{selectedContact.business_roles?.map((item) => item.business_id).join(', ') || 'Unassigned'}</span></div>
                </div>

                {businessScope !== 'all' ? <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950/45 p-3"><div className="mb-2 text-xs font-medium text-zinc-300">{activeBusiness?.label || businessScope} business context</div><div className="grid gap-2"><Input value={roleDraft} onChange={(event) => setRoleDraft(event.target.value)} placeholder="Relationship or role" /><Input value={segmentDraft} onChange={(event) => setSegmentDraft(event.target.value)} placeholder="Groups or segments, comma separated" /><Button size="sm" variant="secondary" onClick={() => saveBusinessRole.mutate()} disabled={saveBusinessRole.isPending}><Check className="size-3.5" />Save context</Button></div></div> : null}

                <div className="mt-4 flex items-center justify-between gap-2"><div className="text-[10px] font-bold uppercase tracking-[0.15em] text-blue-400">Relationships</div><div className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => recalculateRelevance.mutate()} disabled={!selectedContact.party_id || recalculateRelevance.isPending}><RefreshCw className="size-3.5" />Recalculate</Button><Button size="sm" variant="ghost" onClick={() => void connectionsQuery.refetch()}><RefreshCw className="size-3.5" /></Button></div></div>
                <div className="mt-2 grid grid-cols-3 gap-2"><div className="rounded-lg border border-zinc-800 bg-zinc-950/45 p-3 text-center"><div className="text-xl font-semibold text-white">{relevance?.relevance_score !== undefined ? Math.round(Number(relevance.relevance_score)) : '—'}</div><div className="mt-1 text-[9px] uppercase tracking-wide text-zinc-500">Relevance</div></div><div className="rounded-lg border border-zinc-800 bg-zinc-950/45 p-3 text-center"><div className="text-xl font-semibold text-white">{formatPercent(relevance?.connection_strength)}</div><div className="mt-1 text-[9px] uppercase tracking-wide text-zinc-500">Connection</div></div><div className="rounded-lg border border-zinc-800 bg-zinc-950/45 p-3 text-center"><div className="text-xl font-semibold text-white">{verifiedConnections.length + candidateConnections.length}</div><div className="mt-1 text-[9px] uppercase tracking-wide text-zinc-500">Associations</div></div></div>
                <div className="mt-2 rounded-lg border border-zinc-800 bg-zinc-950/45 p-3 text-xs leading-5 text-zinc-400">Relevance is contextual and explainable. Proximity can support discovery but does not verify a relationship.</div>

                {verifiedConnections.length ? <div className="mt-3 space-y-2">{verifiedConnections.slice(0, 4).map((connection) => <div key={connection.edge_id} className="flex items-center gap-2 rounded-lg border border-emerald-900/40 bg-emerald-950/10 p-2.5 text-xs"><Link2 className="size-4 text-emerald-400" /><div className="min-w-0 flex-1"><div className="truncate text-zinc-200">{connection.other_name}</div><div className="text-zinc-500">{connection.predicate?.replaceAll('_', ' ')} · verified</div></div></div>)}</div> : null}

                {candidateConnections.length ? <div className="mt-3 space-y-2"><div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.12em] text-amber-400"><ShieldQuestion className="size-3.5" />Candidate Relationships</div>{candidateConnections.slice(0, 6).map((connection) => { const candidateId = connection.candidate_id || connection.edge_id; return <div key={candidateId} className="rounded-lg border border-amber-900/40 bg-amber-950/10 p-2.5 text-xs"><div className="flex items-start gap-2"><Network className="mt-0.5 size-4 shrink-0 text-amber-400" /><div className="min-w-0 flex-1"><div className="truncate text-zinc-200">{connection.other_name}</div><div className="text-zinc-500">{connection.predicate?.replaceAll('_', ' ')} · {formatPercent(connection.confidence)}</div>{connection.rationale ? <div className="mt-1 text-[10px] leading-4 text-zinc-600">{connection.rationale}</div> : null}</div></div><div className="mt-2 flex justify-end gap-1"><Button size="sm" variant="ghost" disabled={!candidateId} onClick={() => candidateId && reviewCandidate.mutate({ candidateId, decision: 'reject' })}><X className="size-3" />Dismiss</Button><Button size="sm" variant="secondary" disabled={!candidateId} onClick={() => candidateId && reviewCandidate.mutate({ candidateId, decision: 'accept' })}><Check className="size-3" />Verify</Button></div></div> })}</div> : null}

                <div className="mt-4 flex items-center justify-between"><div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-blue-400"><FileImage className="size-3.5" />Images & Dossier Package</div><Badge variant="muted">{media.length} images</Badge></div>
                <div className="mt-2 rounded-lg border border-zinc-800 bg-zinc-950/45 p-3">
                  <div className="mb-3 flex items-center gap-2 text-xs text-zinc-400"><FolderOpen className="size-4" /><span>Images · Documents · Evidence · Exports</span></div>
                  {packageQuery.data?.package_dir ? <div className="mb-3 break-all text-[10px] text-zinc-600">Package: {packageQuery.data.package_dir}</div> : null}
                  {media.length ? <div className="mb-3 grid grid-cols-3 gap-2">{media.slice(0, 9).map((item) => <div key={item.media_id} className="overflow-hidden rounded-lg border border-zinc-800 bg-black/30"><img src={item.image_url} alt={item.label || 'Dossier image'} className="aspect-square w-full object-cover" /><div className="flex items-center justify-between gap-1 p-1"><button type="button" className="truncate text-[9px] text-zinc-400" onClick={() => setPrimaryMedia.mutate(item.media_id)}>{item.is_primary ? 'Primary' : 'Set primary'}</button><button type="button" className="text-zinc-600 hover:text-rose-400" onClick={() => deleteMedia.mutate(item.media_id)}><Trash2 className="size-3" /></button></div></div>)}</div> : null}
                  <div className="grid gap-2"><Input type="file" accept="image/jpeg,image/png,image/webp,image/gif" onChange={(event) => setImageFile(event.target.files?.[0] || null)} /><div className="grid grid-cols-2 gap-2"><Select value={imageDraft.media_kind} onChange={(event) => setImageDraft({ ...imageDraft, media_kind: event.target.value })}>{mediaKinds.map((kind) => <option key={kind} value={kind}>{kind}</option>)}</Select><Input value={imageDraft.label} onChange={(event) => setImageDraft({ ...imageDraft, label: event.target.value })} placeholder="Image label" /></div><Textarea value={imageDraft.notes} onChange={(event) => setImageDraft({ ...imageDraft, notes: event.target.value })} placeholder="Image notes or provenance" /><label className="flex items-center gap-2 text-xs text-zinc-400"><input type="checkbox" checked={imageDraft.is_primary} onChange={(event) => setImageDraft({ ...imageDraft, is_primary: event.target.checked })} />Set as primary dossier image</label><Button size="sm" variant="secondary" disabled={!imageFile || uploadImage.isPending} onClick={() => uploadImage.mutate()}><Upload className="size-3.5" />Upload to Images folder</Button></div>
                </div>

                {selectedContact.notes ? <><div className="mt-4 text-[10px] font-bold uppercase tracking-[0.15em] text-blue-400">Notes</div><div className="mt-2 rounded-lg border border-zinc-800 bg-zinc-950/45 p-3 text-sm leading-6 text-zinc-300">{selectedContact.notes}</div></> : null}
                {selectedStage ? <><div className="mt-4 text-[10px] font-bold uppercase tracking-[0.15em] text-violet-400">Lifecycle</div><div className="mt-2 rounded-lg border border-violet-900/40 bg-violet-950/10 p-3 text-sm text-zinc-300">Current state: <span className="font-medium text-white">{lifecycleLabel(selectedStage)}</span></div></> : null}
                {selectedContact.id ? <div className="mt-4"><DossierLinksRibbon contactId={String(selectedContact.id)} /></div> : null}

                <div className="mt-4 text-[10px] font-bold uppercase tracking-[0.15em] text-blue-400">Actions</div>
                <div className="mt-2 grid grid-cols-2 gap-2"><Button variant="primary" onClick={() => openVIVCommunications(selectedContact)} disabled={!selectedContact.email}><Mail className="size-4" />Communications</Button><Button variant="secondary" onClick={() => openCalendar(selectedContact)}><CalendarDays className="size-4" />Event Grid</Button></div>
              </div>

              <div className="flex items-center justify-between border-t border-blue-500/20 bg-[#111d37] px-4 py-3 text-[10px] text-zinc-500"><span>Identity · relationships · communications · evidence</span><span className="flex items-center gap-1.5 font-bold text-emerald-400"><span className="size-1.5 rounded-full bg-emerald-400" />LINKED</span></div>
            </div>
          ) : <Card><CardContent><div className="flex min-h-80 flex-col items-center justify-center text-center"><div className="flex size-14 items-center justify-center rounded-xl bg-zinc-900 text-zinc-500"><UserRound className="size-6" /></div><div className="mt-4 font-medium text-zinc-200">Select a dossier</div><div className="mt-1 max-w-72 text-sm text-zinc-500">One canonical subject can participate in multiple business contexts without duplicate dossiers.</div></div></CardContent></Card>}
        </div>
      </div>
    </div>
  )
}
