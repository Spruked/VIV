import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { SectionHeader } from '@/components/SectionHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty'
import { api } from '@/lib/api'
import { updateVIVContext } from '@/lib/orb-integration'
import { compactDate } from '@/lib/utils'

type CalendarEvent = {
  id: string
  title: string
  event_type?: string
  start_time?: string
  end_time?: string
  location?: string
  status?: string
}

export default function Calendar() {
  const upcoming = useQuery({
    queryKey: ['calendar-upcoming'],
    queryFn: async () => (await api.get('/cali/calendar/upcoming', { params: { days: 14 } })).data as { events: CalendarEvent[] },
  })

  useEffect(() => {
    updateVIVContext({
      currentView: 'calendar',
      highPriorityTasks: upcoming.data?.events?.length || 0,
      lastAction: 'calendar_loaded',
    })
  }, [upcoming.data?.events?.length])

  return (
    <div>
      <SectionHeader title="Event Grid" detail="Upcoming meetings, milestones, follow-ups, scheduled actions, and time-sensitive events." />
      <Card>
        <CardHeader>
          <CardTitle>Upcoming Events</CardTitle>
        </CardHeader>
        <CardContent>
          {upcoming.data?.events?.length ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {upcoming.data.events.map((event) => (
                <div key={event.id} className="rounded-lg border border-zinc-800 bg-black/25 p-4">
                  <div className="font-medium text-zinc-100">{event.title}</div>
                  <div className="mt-2 text-sm text-zinc-500">{compactDate(event.start_time)}</div>
                  <div className="mt-1 text-xs text-zinc-600">{event.location || event.event_type || 'VIV event'}</div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="No upcoming events" detail="Meetings, milestones, follow-ups, and scheduled actions will appear here." />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
