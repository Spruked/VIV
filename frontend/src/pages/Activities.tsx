import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import { SectionHeader } from '@/components/SectionHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { updateVIVContext } from '@/lib/orb-integration'
import { compactDate } from '@/lib/utils'
import type { Activity, Contact } from '@/types'

export default function Activities() {
  const queryClient = useQueryClient()
  const [contactId, setContactId] = useState('')
  const [summary, setSummary] = useState('')
  const [activityType, setActivityType] = useState('note')

  const contactsQuery = useQuery({
    queryKey: ['contacts', 'activities-picker'],
    queryFn: async () => (await api.get('/cali/contacts')).data as { contacts: Contact[]; count: number },
  })

  const contacts = useMemo(() => contactsQuery.data?.contacts || [], [contactsQuery.data?.contacts])
  const activeContactId = contactId || String(contacts[0]?.id || contacts[0]?.contact_id || '')
  const selectedContact = contacts.find((contact) => String(contact.id || contact.contact_id) === activeContactId) || null

  const activitiesQuery = useQuery({
    queryKey: ['activities', activeContactId],
    enabled: Boolean(activeContactId),
    queryFn: async () => (await api.get(`/cali/crm/activities/${activeContactId}`, { params: { limit: 80 } })).data as { activities: Activity[]; count: number },
  })

  const createActivity = useMutation({
    mutationFn: async () =>
      api.post('/cali/crm/activities', {
        contact_id: activeContactId,
        activity_type: activityType,
        summary,
        metadata: { source: 'viv_frontend' },
      }),
    onSuccess: async () => {
      toast.success('Timeline event added')
      setSummary('')
      await queryClient.invalidateQueries({ queryKey: ['activities', activeContactId] })
    },
    onError: (error) => toast.error(error.message),
  })

  useEffect(() => {
    updateVIVContext({
      currentView: 'activities',
      selectedContact,
      lastAction: activeContactId ? `activity_feed:${activeContactId}` : 'activity_feed_empty',
    })
  }, [activeContactId, selectedContact])

  return (
    <div>
      <SectionHeader title="Timeline" detail="Chronological record of observations, communications, meetings, follow-ups, signals, and milestones for each dossier." />

      <div className="grid gap-5 xl:grid-cols-[1fr_24rem]">
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <CardTitle>Intelligence Timeline</CardTitle>
              <Select value={activeContactId} onChange={(event) => setContactId(event.target.value)} className="md:w-80">
                {contacts.map((contact) => (
                  <option key={contact.id || contact.contact_id || contact.email || contact.name} value={contact.id || contact.contact_id}>
                    {contact.name}
                  </option>
                ))}
              </Select>
            </div>
          </CardHeader>
          <CardContent>
            {activitiesQuery.data?.activities?.length ? (
              <div className="flex flex-col gap-3">
                {activitiesQuery.data.activities.map((item) => (
                  <div key={item.id} className="rounded-lg border border-zinc-800 bg-black/25 p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <Badge variant="muted">{item.activity_type}</Badge>
                        <p className="mt-2 text-sm text-zinc-200">{item.summary}</p>
                      </div>
                      <span className="shrink-0 text-xs text-zinc-500">{compactDate(item.created_at)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="No timeline events yet" detail="Select a dossier or add its first observation, communication, meeting, or milestone." />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Add Timeline Event</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Select value={activityType} onChange={(event) => setActivityType(event.target.value)}>
              <option value="note">Observation</option>
              <option value="call">Call</option>
              <option value="meeting">Meeting</option>
              <option value="follow_up">Follow-up</option>
              <option value="email">Email Message</option>
              <option value="signal">Signal</option>
            </Select>
            <Textarea value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="What happened, changed, or became relevant?" />
            <Button variant="primary" disabled={!activeContactId || !summary.trim() || createActivity.isPending} onClick={() => createActivity.mutate()}>
              <Plus className="size-4" />
              Add to Timeline
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
