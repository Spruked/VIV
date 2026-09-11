'use client';

import { useEffect, useState } from 'react';

type HubTab = 'overview' | 'personal' | 'leads' | 'contacts' | 'financial' | 'calendar' | 'verification' | 'tasks';

type CaliOperationsHubProps = { adminToken: string };

type AnyRecord = Record<string, any>;

async function callCali<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
    cache: 'no-store',
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data?.detail || data?.error || data?.message || `Request failed: ${response.status}`);
  }
  return data as T;
}

function iso(value: string): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

export default function CaliOperationsHub({ adminToken }: CaliOperationsHubProps) {
  const [tab, setTab] = useState<HubTab>('overview');
  const [status, setStatus] = useState<string>('');
  const [stats, setStats] = useState<AnyRecord | null>(null);
  const [briefing, setBriefing] = useState<AnyRecord | null>(null);

  const [contacts, setContacts] = useState<AnyRecord[]>([]);
  const [financial, setFinancial] = useState<AnyRecord | null>(null);
  const [events, setEvents] = useState<AnyRecord[]>([]);
  const [calls, setCalls] = useState<AnyRecord[]>([]);
  const [tasks, setTasks] = useState<AnyRecord[]>([]);
  const [crmPipeline, setCrmPipeline] = useState<AnyRecord | null>(null);
  const [emailConnectorStatus, setEmailConnectorStatus] = useState<AnyRecord | null>(null);
  const [assistantQuery, setAssistantQuery] = useState('');
  const [assistantReply, setAssistantReply] = useState('');

  const [name, setName] = useState('');
  const [contactType, setContactType] = useState('personal');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');

  const [institution, setInstitution] = useState('');
  const [accountType, setAccountType] = useState('checking');
  const [accountNumber, setAccountNumber] = useState('');
  const [balance, setBalance] = useState('0');

  const [eventTitle, setEventTitle] = useState('');
  const [eventType, setEventType] = useState('meeting');
  const [eventStart, setEventStart] = useState('');

  const [callerNumber, setCallerNumber] = useState('');
  const [callerName, setCallerName] = useState('');

  const [taskTitle, setTaskTitle] = useState('');
  const [taskPriority, setTaskPriority] = useState('1');
  const [personalTaskTitle, setPersonalTaskTitle] = useState('');
  const [personalTaskDueAt, setPersonalTaskDueAt] = useState('');
  const [personalTaskPriority, setPersonalTaskPriority] = useState('2');

  const [leadContactId, setLeadContactId] = useState('');
  const [leadStage, setLeadStage] = useState('prospect');
  const [leadFollowUpAt, setLeadFollowUpAt] = useState('');
  const [leadOwner, setLeadOwner] = useState('bryan@spruked.com');
  const [leadStageNote, setLeadStageNote] = useState('');

  const [appointmentContactId, setAppointmentContactId] = useState('');
  const [appointmentTitle, setAppointmentTitle] = useState('Lead Appointment');
  const [appointmentStart, setAppointmentStart] = useState('');
  const [appointmentEnd, setAppointmentEnd] = useState('');
  const [appointmentLocation, setAppointmentLocation] = useState('');
  const [appointmentNotes, setAppointmentNotes] = useState('');

  const [mailProvider, setMailProvider] = useState('imap_smtp');
  const [businessEmail, setBusinessEmail] = useState('bryan@spruked.com');
  const [imapHost, setImapHost] = useState('imap.gmail.com');
  const [imapPort, setImapPort] = useState('993');
  const [smtpHost, setSmtpHost] = useState('smtp.gmail.com');
  const [smtpPort, setSmtpPort] = useState('587');
  const [calendarProvider, setCalendarProvider] = useState('local');
  const [connectorNotes, setConnectorNotes] = useState('Primary business mailbox for CRM follow-up.');
  const [mailPollSummary, setMailPollSummary] = useState('');
  const [externalMailStats, setExternalMailStats] = useState<AnyRecord | null>(null);
  const [showExternalInbox, setShowExternalInbox] = useState(false);
  const [externalInbox, setExternalInbox] = useState<AnyRecord[]>([]);

  const leadContacts = contacts.filter((contact) => isLeadType(contact));
  const personalContacts = contacts.filter((contact) => isPersonalType(contact));
  const personalTasks = tasks.filter((task) => normalizeTaskCategory(task) === 'personal');
  const workTasks = tasks.filter((task) => normalizeTaskCategory(task) !== 'personal');
  const crmLeads = (crmPipeline?.leads || leadContacts) as AnyRecord[];
  const crmStageCounts = (crmPipeline?.stages || {}) as Record<string, number>;
  const promoterContacts = crmLeads.filter((contact) => normalizeType(contact) === 'promoter');
  const investorContacts = crmLeads.filter((contact) => normalizeType(contact) === 'investor');
  const marketingContacts = crmLeads.filter((contact) => normalizeType(contact) === 'marketing');

  const loadOverview = async () => {
    if (!adminToken.trim()) return;
    try {
      const [s, b] = await Promise.all([
        callCali<{ stats: AnyRecord }>('/api/cali/status', adminToken),
        callCali<AnyRecord>('/api/cali/calendar/today', adminToken),
      ]);
      setStats(s.stats);
      setBriefing(b);
      setStatus('Cali hub loaded.');
    } catch (error) {
      setStatus((error as Error).message);
    }
  };

  const loadAll = async () => {
    if (!adminToken.trim()) return;
    try {
      const [c, f, e, v, t, p, m] = await Promise.all([
        callCali<{ contacts: AnyRecord[] }>('/api/cali/contacts', adminToken),
        callCali<AnyRecord>('/api/cali/financial/summary', adminToken),
        callCali<{ events: AnyRecord[] }>('/api/cali/calendar/upcoming?days=30', adminToken),
        callCali<{ calls: AnyRecord[] }>('/api/cali/verification/queue', adminToken),
        callCali<{ tasks: AnyRecord[] }>('/api/cali/tasks', adminToken),
        callCali<AnyRecord>('/api/cali/crm/pipeline', adminToken),
        callCali<AnyRecord>('/api/cali/crm/email/status', adminToken),
      ]);
      setContacts(c.contacts || []);
      setFinancial(f);
      setEvents(e.events || []);
      setCalls(v.calls || []);
      setTasks(t.tasks || []);
      setCrmPipeline(p);
      setEmailConnectorStatus(m);
      void callCali<AnyRecord>('/api/cali/crm/external-email/stats', adminToken)
        .then((statsPayload) => setExternalMailStats(statsPayload?.stats || statsPayload))
        .catch(() => setExternalMailStats(null));
      if (showExternalInbox) {
        void callCali<AnyRecord>('/api/cali/crm/external-email/messages?folder=inbox&limit=20&offset=0', adminToken)
          .then((payload) => setExternalInbox(payload?.emails || []))
          .catch(() => setExternalInbox([]));
      }

      const firstLead = (p?.leads || [])[0];
      if (firstLead && !leadContactId) setLeadContactId(String(firstLead.id || ''));
      if (firstLead && !appointmentContactId) setAppointmentContactId(String(firstLead.id || ''));
    } catch (error) {
      setStatus((error as Error).message);
    }
  };

  useEffect(() => {
    void Promise.all([loadOverview(), loadAll()]);
    // loadOverview/loadAll intentionally re-evaluate with current token only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminToken]);

  if (!adminToken.trim()) {
    return (
      <section className="rounded-2xl border border-gray-900 bg-black/70 p-6">
        <h2 className="text-2xl font-semibold text-light">Cali Operations Hub</h2>
        <p className="mt-2 text-sm text-gray-400">Enter Admin Token above to unlock Cali personal assistant workflows.</p>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-gray-900 bg-black/70 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold text-light">Cali Operations Hub</h2>
          <p className="text-sm text-gray-400">KayGee cognition personal assistant controls.</p>
        </div>
        <button
          type="button"
          onClick={() => void Promise.all([loadOverview(), loadAll()])}
          className="rounded-full border border-gray-700 px-4 py-2 text-xs uppercase tracking-widest text-gray-300 hover:border-light hover:text-light"
        >
          Refresh
        </button>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {(['overview', 'personal', 'leads', 'contacts', 'financial', 'calendar', 'verification', 'tasks'] as HubTab[]).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={`rounded-full px-4 py-2 text-xs uppercase tracking-widest ${
              tab === value ? 'bg-emerald-500/20 text-emerald-300' : 'border border-gray-700 text-gray-400 hover:text-light'
            }`}
          >
            {value}
          </button>
        ))}
      </div>

      {status ? <p className="mt-3 text-sm text-gray-400">{status}</p> : null}

      <form
        className="mt-4 rounded-lg border border-gray-900 bg-[#050505] p-4"
        onSubmit={(event) => {
          event.preventDefault();
          const prompt = assistantQuery.trim();
          if (!prompt) return;
          setStatus('Cali is thinking...');
          void fetch('/api/orb', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'x-cali-context': 'admin',
            },
            body: JSON.stringify({
              action: 'query',
              prompt,
              context: { source: 'admin', currentPath: '/admin' },
            }),
          })
            .then(async (response) => {
              const data = await response.json();
              if (!response.ok) {
                throw new Error(data?.message || 'Cali query failed.');
              }
              setAssistantReply(String(data?.response || 'Cali is online.'));
              setAssistantQuery('');
              setStatus('Cali responded.');
            })
            .catch((error) => setStatus((error as Error).message));
        }}
      >
        <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Ask Cali (ORB Admin Mode)</p>
        <div className="mt-2 flex flex-col gap-2 md:flex-row">
          <input
            id="cali-assistant-query"
            name="caliAssistantQuery"
            value={assistantQuery}
            onChange={(event) => setAssistantQuery(event.target.value)}
            placeholder="Cali, help me prioritize today."
            className="flex-1 rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light"
          />
          <button
            type="submit"
            className="rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black"
          >
            Ask
          </button>
        </div>
        {assistantReply ? <p className="mt-3 text-sm text-gray-200">{assistantReply}</p> : null}
      </form>

      {tab === 'overview' ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Card label="Lead Contacts" value={leadContacts.length} />
          <Card label="Personal Contacts" value={personalContacts.length} />
          <Card label="Promoters" value={promoterContacts.length} />
          <Card label="Investors" value={investorContacts.length} />
          <Card label="Marketing" value={marketingContacts.length} />
          <Card label="Prospects" value={Number(crmStageCounts.prospect || 0)} />
          <Card label="Meeting Scheduled" value={Number(crmStageCounts.meeting_scheduled || 0)} />
          <Card label="Contacts" value={stats?.contacts || 0} />
          <Card label="Financial Accounts" value={stats?.financial_accounts || 0} />
          <Card label="Events" value={stats?.events || 0} />
          <Card label="Work Tasks" value={workTasks.length} />
          <Card label="Personal Tasks" value={personalTasks.length} />
          <Card label="Verification Calls" value={stats?.verification_calls || 0} />
          <Card label="Learning Queue" value={stats?.unanswered_questions || 0} />
          {briefing?.briefing_text ? (
            <article className="sm:col-span-2 lg:col-span-3 rounded-lg border border-emerald-900/50 bg-emerald-500/5 p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-emerald-300">Daily Briefing</p>
              <p className="mt-2 whitespace-pre-line text-sm text-gray-200">{briefing.briefing_text}</p>
            </article>
          ) : null}
          <article className="sm:col-span-2 lg:col-span-3 rounded-lg border border-blue-900/50 bg-blue-500/5 p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-blue-300">Today Plan</p>
            <div className="mt-3 grid gap-4 md:grid-cols-3">
              <div>
                <p className="text-xs uppercase tracking-[0.15em] text-gray-400">Personal Top 3</p>
                <div className="mt-2 space-y-2">
                  {personalTasks.slice(0, 3).length === 0 ? (
                    <p className="text-xs text-gray-500">No personal reminders due.</p>
                  ) : (
                    personalTasks.slice(0, 3).map((task) => (
                      <div key={task.id} className="flex items-center justify-between gap-2">
                        <p className="text-xs text-gray-200">{task.title}</p>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            className="rounded-full border border-gray-700 px-2 py-1 text-[10px] uppercase tracking-widest text-gray-300 hover:text-light"
                            onClick={() => {
                              const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
                              void callCali('/api/cali/tasks', adminToken, {
                                method: 'POST',
                                body: JSON.stringify({
                                  title: `${task.title} (Snoozed)`,
                                  priority: Number(task.priority || 2),
                                  category: 'personal',
                                  due_date: tomorrow,
                                }),
                              })
                                .then(() => callCali(`/api/cali/tasks/${encodeURIComponent(task.id)}/complete`, adminToken, { method: 'POST' }))
                                .then(() => {
                                  setStatus('Task snoozed to tomorrow.');
                                  return loadAll();
                                })
                                .catch((error) => setStatus((error as Error).message));
                            }}
                          >
                            Snooze 1d
                          </button>
                          <button
                            type="button"
                            className="rounded-full border border-emerald-800 px-2 py-1 text-[10px] uppercase tracking-widest text-emerald-300 hover:border-emerald-500"
                            onClick={() => {
                              void callCali(`/api/cali/tasks/${encodeURIComponent(task.id)}/complete`, adminToken, { method: 'POST' })
                                .then(() => {
                                  setStatus('Personal task completed.');
                                  return loadAll();
                                })
                                .catch((error) => setStatus((error as Error).message));
                            }}
                          >
                            Complete
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.15em] text-gray-400">Lead Follow-ups Top 3</p>
                <div className="mt-2 space-y-2">
                  {crmLeads.slice(0, 3).length === 0 ? (
                    <p className="text-xs text-gray-500">No active leads.</p>
                  ) : (
                    crmLeads.slice(0, 3).map((lead) => (
                      <div key={lead.id} className="flex items-center justify-between gap-2">
                        <p className="text-xs text-gray-200">
                          {lead.name} <span className="text-gray-500">({String(lead.crm_stage || 'prospect')})</span>
                        </p>
                        <button
                          type="button"
                          className="rounded-full border border-blue-800 px-2 py-1 text-[10px] uppercase tracking-widest text-blue-300 hover:border-blue-500"
                          onClick={() => {
                            const next = nextLeadStage(String(lead.crm_stage || 'prospect'));
                            void callCali('/api/cali/crm/leads/stage', adminToken, {
                              method: 'PATCH',
                              body: JSON.stringify({
                                contact_id: lead.id,
                                stage: next,
                                owner: leadOwner || null,
                                notes: `Quick action: advanced from ${String(lead.crm_stage || 'prospect')} to ${next}`,
                              }),
                            })
                              .then(() => {
                                setStatus(`Lead advanced to ${next}.`);
                                return loadAll();
                              })
                              .catch((error) => setStatus((error as Error).message));
                          }}
                        >
                          Advance
                        </button>
                        <button
                          type="button"
                          className="rounded-full border border-gray-700 px-2 py-1 text-[10px] uppercase tracking-widest text-gray-300 hover:text-light"
                          onClick={() => {
                            const previous = previousLeadStage(String(lead.crm_stage || 'prospect'));
                            void callCali('/api/cali/crm/leads/stage', adminToken, {
                              method: 'PATCH',
                              body: JSON.stringify({
                                contact_id: lead.id,
                                stage: previous,
                                owner: leadOwner || null,
                                notes: `Quick action: reverted from ${String(lead.crm_stage || 'prospect')} to ${previous}`,
                              }),
                            })
                              .then(() => {
                                setStatus(`Lead reverted to ${previous}.`);
                                return loadAll();
                              })
                              .catch((error) => setStatus((error as Error).message));
                          }}
                        >
                          Revert
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.15em] text-gray-400">External Inbox Signal</p>
                <div className="mt-2 space-y-2 text-xs text-gray-200">
                  <p>Unread: {Number(externalMailStats?.unread_count || externalMailStats?.unread || 0)}</p>
                  <p>Total: {Number(externalMailStats?.total_count || externalMailStats?.total || 0)}</p>
                  <p>Source: Prime Mail</p>
                  <button
                    type="button"
                    className="rounded-full border border-gray-700 px-3 py-1 text-[10px] uppercase tracking-widest text-gray-300 hover:text-light"
                    onClick={() => {
                      setShowExternalInbox((prev) => !prev);
                      if (!showExternalInbox) {
                        void callCali<AnyRecord>('/api/cali/crm/external-email/messages?folder=inbox&limit=20&offset=0', adminToken)
                          .then((payload) => setExternalInbox(payload?.emails || []))
                          .catch((error) => setStatus((error as Error).message));
                      }
                    }}
                  >
                    {showExternalInbox ? 'Hide Inbox' : 'Open Inbox'}
                  </button>
                </div>
              </div>
            </div>
            {showExternalInbox ? (
              <div className="mt-4 rounded border border-gray-900 bg-black/40 p-3">
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">External Inbox (Prime Mail)</p>
                <div className="mt-2 space-y-2">
                  {externalInbox.length === 0 ? (
                    <p className="text-xs text-gray-500">No messages loaded.</p>
                  ) : (
                    externalInbox.slice(0, 10).map((msg) => (
                      <article key={String(msg.id)} className="rounded-lg border border-gray-900 bg-[#050505] p-3">
                        <p className="text-sm font-semibold text-light">{String(msg.subject || '(no subject)')}</p>
                        <p className="mt-1 text-xs text-gray-400">{`${String(msg.sender || 'unknown sender')} • ${String(msg.date || '')}`}</p>
                        <div className="mt-2 flex justify-end">
                          <button
                            type="button"
                            className="rounded-full border border-gray-700 px-3 py-1 text-[10px] uppercase tracking-widest text-gray-300 hover:text-light"
                            onClick={() => {
                              const sender = String(msg.sender || '').trim();
                              const subject = String(msg.subject || '(no subject)').trim();
                              const followUpTitle = sender
                                ? `Follow up: ${subject} (${sender})`
                                : `Follow up: ${subject}`;
                              void callCali('/api/cali/tasks', adminToken, {
                                method: 'POST',
                                body: JSON.stringify({
                                  title: followUpTitle,
                                  priority: 3,
                                  category: 'business',
                                  description: `Generated from inbox message ${String(msg.id || '')}`,
                                }),
                              })
                                .then(() => {
                                  setStatus('Follow-up task created from email.');
                                  return loadAll();
                                })
                                .catch((error) => setStatus((error as Error).message));
                            }}
                          >
                            Create Follow-up
                          </button>
                        </div>
                      </article>
                    ))
                  )}
                </div>
              </div>
            ) : null}
          </article>
        </div>
      ) : null}

      {tab === 'personal' ? (
        <div className="mt-4 space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <form
              className="rounded-lg border border-gray-900 bg-[#050505] p-4"
              onSubmit={(event) => {
                event.preventDefault();
                void callCali('/api/cali/contacts', adminToken, {
                  method: 'POST',
                  body: JSON.stringify({
                    name,
                    contact_type: contactType || 'personal',
                    phone: phone || null,
                    email: email || null,
                  }),
                })
                  .then(() => {
                    setName('');
                    setPhone('');
                    setEmail('');
                    setStatus('Personal contact saved.');
                    return loadAll();
                  })
                  .catch((error) => setStatus((error as Error).message));
              }}
            >
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Personal Contacts</p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <input required value={name} onChange={(event) => setName(event.target.value)} placeholder="Name" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <select value={contactType} onChange={(event) => setContactType(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light">
                  <option value="personal">Personal</option>
                  <option value="family">Family</option>
                  <option value="business">Business</option>
                </select>
                <input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="Phone" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Email" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <button type="submit" className="md:col-span-2 rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black">Save Personal Contact</button>
              </div>
            </form>

            <form
              className="rounded-lg border border-gray-900 bg-[#050505] p-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (!personalTaskTitle.trim()) {
                  setStatus('Enter a personal reminder title.');
                  return;
                }
                void callCali('/api/cali/tasks', adminToken, {
                  method: 'POST',
                  body: JSON.stringify({
                    title: personalTaskTitle,
                    priority: Number(personalTaskPriority || '2'),
                    category: 'personal',
                    due_date: iso(personalTaskDueAt),
                  }),
                })
                  .then(() => {
                    setPersonalTaskTitle('');
                    setPersonalTaskDueAt('');
                    setStatus('Personal reminder added.');
                    return loadAll();
                  })
                  .catch((error) => setStatus((error as Error).message));
              }}
            >
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Personal Reminders</p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <input value={personalTaskTitle} onChange={(event) => setPersonalTaskTitle(event.target.value)} placeholder="Reminder title" className="md:col-span-2 rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <input type="datetime-local" value={personalTaskDueAt} onChange={(event) => setPersonalTaskDueAt(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <input type="number" min={1} max={5} value={personalTaskPriority} onChange={(event) => setPersonalTaskPriority(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <button type="submit" className="md:col-span-2 rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black">Add Personal Reminder</button>
              </div>
            </form>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <article className="rounded-lg border border-gray-900 bg-[#050505] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Personal Contacts List</p>
              <div className="mt-3 space-y-2">
                {personalContacts.length === 0 ? (
                  <p className="text-xs text-gray-500">No personal/family contacts yet.</p>
                ) : (
                  personalContacts.map((contact) => (
                    <Item key={contact.id} title={contact.name} subtitle={`${normalizeType(contact)} • ${contact.phone || contact.email || 'No contact info'}`} />
                  ))
                )}
              </div>
            </article>

            <article className="rounded-lg border border-gray-900 bg-[#050505] p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Personal Tasks</p>
              <div className="mt-3 space-y-2">
                {personalTasks.length === 0 ? (
                  <p className="text-xs text-gray-500">No personal tasks yet.</p>
                ) : (
                  personalTasks.map((task) => (
                    <Item key={task.id} title={task.title} subtitle={`${normalizeTaskCategory(task)} • priority ${task.priority}${task.due_date ? ` • due ${task.due_date}` : ''}`} />
                  ))
                )}
              </div>
            </article>
          </div>
        </div>
      ) : null}

      {tab === 'leads' ? (
        <div className="mt-4 space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <form
              className="rounded-lg border border-gray-900 bg-[#050505] p-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (!leadContactId) {
                  setStatus('Select a lead first.');
                  return;
                }
                void callCali('/api/cali/crm/leads/stage', adminToken, {
                  method: 'PATCH',
                  body: JSON.stringify({
                    contact_id: leadContactId,
                    stage: leadStage,
                    next_follow_up_at: iso(leadFollowUpAt),
                    owner: leadOwner || null,
                    notes: leadStageNote || null,
                  }),
                })
                  .then(() => {
                    setLeadStageNote('');
                    setStatus('Lead stage updated.');
                    return loadAll();
                  })
                  .catch((error) => setStatus((error as Error).message));
              }}
            >
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">CRM Stage Management</p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <select value={leadContactId} onChange={(event) => setLeadContactId(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light">
                  <option value="">Select lead</option>
                  {crmLeads.map((contact) => (
                    <option key={contact.id} value={contact.id}>{contact.name}</option>
                  ))}
                </select>
                <select value={leadStage} onChange={(event) => setLeadStage(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light">
                  <option value="prospect">Prospect</option>
                  <option value="qualified">Qualified</option>
                  <option value="contacted">Contacted</option>
                  <option value="meeting_scheduled">Meeting Scheduled</option>
                  <option value="proposal">Proposal</option>
                  <option value="won">Won</option>
                  <option value="lost">Lost</option>
                </select>
                <input type="datetime-local" value={leadFollowUpAt} onChange={(event) => setLeadFollowUpAt(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <input value={leadOwner} onChange={(event) => setLeadOwner(event.target.value)} placeholder="Owner" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <input value={leadStageNote} onChange={(event) => setLeadStageNote(event.target.value)} placeholder="Stage update note" className="md:col-span-2 rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <button type="submit" className="md:col-span-2 rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black">Update Lead Stage</button>
              </div>
            </form>

            <form
              className="rounded-lg border border-gray-900 bg-[#050505] p-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (!appointmentContactId) {
                  setStatus('Select a lead for the appointment.');
                  return;
                }
                if (!appointmentStart) {
                  setStatus('Pick an appointment start date/time.');
                  return;
                }
                void callCali('/api/cali/crm/appointments', adminToken, {
                  method: 'POST',
                  body: JSON.stringify({
                    contact_id: appointmentContactId,
                    title: appointmentTitle || 'Lead Appointment',
                    start_time: iso(appointmentStart),
                    end_time: iso(appointmentEnd),
                    location: appointmentLocation || null,
                    notes: appointmentNotes || null,
                  }),
                })
                  .then(() => {
                    setAppointmentNotes('');
                    setStatus('Appointment scheduled and linked to CRM + calendar.');
                    return loadAll();
                  })
                  .catch((error) => setStatus((error as Error).message));
              }}
            >
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">CRM Appointment Scheduler</p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <select value={appointmentContactId} onChange={(event) => setAppointmentContactId(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light">
                  <option value="">Select lead</option>
                  {crmLeads.map((contact) => (
                    <option key={contact.id} value={contact.id}>{contact.name}</option>
                  ))}
                </select>
                <input value={appointmentTitle} onChange={(event) => setAppointmentTitle(event.target.value)} placeholder="Appointment title" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <input type="datetime-local" value={appointmentStart} onChange={(event) => setAppointmentStart(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <input type="datetime-local" value={appointmentEnd} onChange={(event) => setAppointmentEnd(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <input value={appointmentLocation} onChange={(event) => setAppointmentLocation(event.target.value)} placeholder="Location / meeting link" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <input value={appointmentNotes} onChange={(event) => setAppointmentNotes(event.target.value)} placeholder="Appointment notes" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
                <button type="submit" className="md:col-span-2 rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black">Schedule Appointment</button>
              </div>
            </form>
          </div>

          <form
            className="rounded-lg border border-gray-900 bg-[#050505] p-4"
            onSubmit={(event) => {
              event.preventDefault();
              void callCali('/api/cali/crm/email/connect', adminToken, {
                method: 'POST',
                body: JSON.stringify({
                  provider: mailProvider,
                  email: businessEmail,
                  imap_host: imapHost || null,
                  imap_port: Number(imapPort || '993'),
                  smtp_host: smtpHost || null,
                  smtp_port: Number(smtpPort || '587'),
                  calendar_provider: calendarProvider,
                  notes: connectorNotes || null,
                }),
              })
                .then(() => {
                  setStatus('Email connector saved.');
                  return loadAll();
                })
                .catch((error) => setStatus((error as Error).message));
            }}
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Business Email + Calendar Connector</p>
              <p className="text-xs text-gray-400">Status: {String(emailConnectorStatus?.status || 'not_configured')}</p>
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <input value={businessEmail} onChange={(event) => setBusinessEmail(event.target.value)} placeholder="Business email" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
              <select value={mailProvider} onChange={(event) => setMailProvider(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light"><option value="imap_smtp">IMAP/SMTP</option></select>
              <select value={calendarProvider} onChange={(event) => setCalendarProvider(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light"><option value="local">Local CRM Calendar</option><option value="google">Google Calendar (metadata)</option><option value="microsoft">Microsoft 365 (metadata)</option></select>
              <input value={imapHost} onChange={(event) => setImapHost(event.target.value)} placeholder="IMAP host" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
              <input value={imapPort} onChange={(event) => setImapPort(event.target.value)} placeholder="IMAP port" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
              <input value={smtpHost} onChange={(event) => setSmtpHost(event.target.value)} placeholder="SMTP host" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
              <input value={smtpPort} onChange={(event) => setSmtpPort(event.target.value)} placeholder="SMTP port" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
              <input value={connectorNotes} onChange={(event) => setConnectorNotes(event.target.value)} placeholder="Connector notes" className="md:col-span-2 rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
              <button type="submit" className="rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black">Save Connector</button>
              <button
                type="button"
                className="rounded-full border border-emerald-700 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-emerald-200 hover:border-emerald-500"
                onClick={() => {
                  setMailPollSummary('Polling inbox...');
                  void callCali<AnyRecord>('/api/cali/crm/email/poll', adminToken, {
                    method: 'POST',
                    body: JSON.stringify({ mailbox: 'INBOX', limit: 25, since_hours: 72, unseen_only: true }),
                  })
                    .then((result) => {
                      setMailPollSummary(
                        `Processed ${Number(result?.processed || 0)} messages. ` +
                          `Activities: ${Number(result?.created_activities || 0)}, ` +
                          `New contacts: ${Number(result?.created_contacts || 0)}, ` +
                          `Duplicates: ${Number(result?.duplicates || 0)}.`
                      );
                      return loadAll();
                    })
                    .catch((error) => {
                      setMailPollSummary(`Poll failed: ${(error as Error).message}`);
                    });
                }}
              >
                Poll Inbound Mailbox
              </button>
            </div>
            <p className="mt-2 text-xs text-gray-500">Set BUSINESS_EMAIL_APP_PASSWORD in environment to enable authenticated mailbox login checks.</p>
            {mailPollSummary ? <p className="mt-2 text-xs text-gray-400">{mailPollSummary}</p> : null}
          </form>

          <div className="grid gap-4 lg:grid-cols-3">
            <LeadColumn title="Promoters" count={promoterContacts.length} contacts={promoterContacts} />
            <LeadColumn title="Investors" count={investorContacts.length} contacts={investorContacts} />
            <LeadColumn title="Marketing" count={marketingContacts.length} contacts={marketingContacts} />
          </div>
        </div>
      ) : null}

      {tab === 'contacts' ? (
        <div className="mt-4 space-y-3">
          <form
            className="grid gap-3 rounded-lg border border-gray-900 bg-[#050505] p-4 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              void callCali('/api/cali/contacts', adminToken, {
                method: 'POST',
                body: JSON.stringify({ name, contact_type: contactType, phone: phone || null, email: email || null }),
              })
                .then(() => {
                  setName('');
                  setPhone('');
                  setEmail('');
                  return loadAll();
                })
                .catch((error) => setStatus((error as Error).message));
            }}
          >
            <input id="cali-name" name="caliName" required value={name} onChange={(event) => setName(event.target.value)} placeholder="Name" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <select id="cali-contact-type" name="caliContactType" value={contactType} onChange={(event) => setContactType(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light"><option value="personal">Personal</option><option value="financial">Financial</option><option value="business">Business</option><option value="family">Family</option><option value="marketing">Marketing</option><option value="promoter">Promoter</option><option value="investor">Investor</option></select>
            <input id="cali-phone" name="caliPhone" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="Phone" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <input id="cali-email" name="caliEmail" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Email" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <button type="submit" className="md:col-span-2 rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black">Add Contact</button>
          </form>

          <div className="space-y-2">{contacts.map((contact) => <Item key={contact.id} title={contact.name} subtitle={`${contact.type} • ${contact.phone || contact.email || 'No contact info'}`} />)}</div>
        </div>
      ) : null}

      {tab === 'financial' ? (
        <div className="mt-4 space-y-3">
          <form
            className="grid gap-3 rounded-lg border border-gray-900 bg-[#050505] p-4 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              void callCali('/api/cali/financial/accounts', adminToken, {
                method: 'POST',
                body: JSON.stringify({ institution, account_type: accountType, account_number: accountNumber, balance: Number(balance || '0') }),
              })
                .then(() => {
                  setInstitution('');
                  setAccountNumber('');
                  setBalance('0');
                  return loadAll();
                })
                .catch((error) => setStatus((error as Error).message));
            }}
          >
            <input id="cali-institution" name="caliInstitution" required value={institution} onChange={(event) => setInstitution(event.target.value)} placeholder="Institution" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <select id="cali-account-type" name="caliAccountType" value={accountType} onChange={(event) => setAccountType(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light"><option value="checking">Checking</option><option value="savings">Savings</option><option value="investment">Investment</option><option value="credit">Credit</option><option value="loan">Loan</option></select>
            <input id="cali-account-number" name="caliAccountNumber" required value={accountNumber} onChange={(event) => setAccountNumber(event.target.value)} placeholder="Account Number" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <input id="cali-balance" name="caliBalance" type="number" step="0.01" value={balance} onChange={(event) => setBalance(event.target.value)} placeholder="Balance" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <button type="submit" className="md:col-span-2 rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black">Add Account</button>
          </form>

          <article className="rounded-lg border border-gray-900 bg-[#050505] p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Total Balance</p>
            <p className="mt-2 text-3xl font-semibold text-light">{financial?.currency || 'USD'} {Number(financial?.total_balance || 0).toFixed(2)}</p>
          </article>
        </div>
      ) : null}

      {tab === 'calendar' ? (
        <div className="mt-4 space-y-3">
          <form
            className="grid gap-3 rounded-lg border border-gray-900 bg-[#050505] p-4 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              void callCali('/api/cali/calendar/events', adminToken, {
                method: 'POST',
                body: JSON.stringify({ title: eventTitle, event_type: eventType, start_time: iso(eventStart) }),
              })
                .then(() => {
                  setEventTitle('');
                  setEventStart('');
                  return loadAll();
                })
                .catch((error) => setStatus((error as Error).message));
            }}
          >
            <input id="cali-event-title" name="caliEventTitle" required value={eventTitle} onChange={(event) => setEventTitle(event.target.value)} placeholder="Event title" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <select id="cali-event-type" name="caliEventType" value={eventType} onChange={(event) => setEventType(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light"><option value="meeting">Meeting</option><option value="deadline">Deadline</option><option value="reminder">Reminder</option><option value="personal">Personal</option></select>
            <input id="cali-event-start" name="caliEventStart" type="datetime-local" value={eventStart} onChange={(event) => setEventStart(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <button type="submit" className="rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black">Add Event</button>
          </form>

          <div className="space-y-2">{events.map((event) => <Item key={event.id} title={event.title} subtitle={`${event.event_type} • ${event.start_time || 'TBD'}`} />)}</div>
        </div>
      ) : null}

      {tab === 'verification' ? (
        <div className="mt-4 space-y-3">
          <form
            className="grid gap-3 rounded-lg border border-gray-900 bg-[#050505] p-4 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              void callCali('/api/cali/verification/call', adminToken, {
                method: 'POST',
                body: JSON.stringify({ caller_number: callerNumber, caller_name: callerName || null }),
              })
                .then(() => {
                  setCallerNumber('');
                  setCallerName('');
                  return loadAll();
                })
                .catch((error) => setStatus((error as Error).message));
            }}
          >
            <input id="cali-caller-number" name="caliCallerNumber" required value={callerNumber} onChange={(event) => setCallerNumber(event.target.value)} placeholder="Caller number" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <input id="cali-caller-name" name="caliCallerName" value={callerName} onChange={(event) => setCallerName(event.target.value)} placeholder="Caller name" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <button type="submit" className="md:col-span-2 rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black">Log Call</button>
          </form>

          <div className="space-y-2">{calls.map((call) => <Item key={call.id} title={call.caller_name || 'Unknown caller'} subtitle={`${call.caller_number} • ${call.verification_status}`} />)}</div>
        </div>
      ) : null}

      {tab === 'tasks' ? (
        <div className="mt-4 space-y-3">
          <form
            className="grid gap-3 rounded-lg border border-gray-900 bg-[#050505] p-4 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              void callCali('/api/cali/tasks', adminToken, {
                method: 'POST',
                body: JSON.stringify({ title: taskTitle, priority: Number(taskPriority || '1') }),
              })
                .then(() => {
                  setTaskTitle('');
                  setTaskPriority('1');
                  return loadAll();
                })
                .catch((error) => setStatus((error as Error).message));
            }}
          >
            <input id="cali-task-title" name="caliTaskTitle" required value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} placeholder="Task title" className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <input id="cali-task-priority" name="caliTaskPriority" type="number" min={1} max={5} value={taskPriority} onChange={(event) => setTaskPriority(event.target.value)} className="rounded border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-light" />
            <button type="submit" className="md:col-span-2 rounded-full bg-emerald-500 px-5 py-2 text-xs font-semibold uppercase tracking-widest text-black">Add Task</button>
          </form>

          <div className="space-y-2">
            {tasks.map((task) => (
              <article key={task.id} className="rounded-lg border border-gray-900 bg-[#050505] p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-light">{task.title}</p>
                    <p className="text-xs uppercase tracking-[0.2em] text-gray-500">{task.category} • priority {task.priority}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      void callCali(`/api/cali/tasks/${encodeURIComponent(task.id)}/complete`, adminToken, { method: 'POST' })
                        .then(() => loadAll())
                        .catch((error) => setStatus((error as Error).message));
                    }}
                    className="rounded-full border border-emerald-800 px-3 py-1 text-xs uppercase tracking-widest text-emerald-300 hover:border-emerald-500"
                  >
                    Done
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Card({ label, value }: { label: string; value: number }) {
  return (
    <article className="rounded-lg border border-gray-900 bg-[#050505] p-4">
      <p className="text-xs uppercase tracking-[0.2em] text-gray-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-light">{value}</p>
    </article>
  );
}

function Item({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <article className="rounded-lg border border-gray-900 bg-[#050505] p-3">
      <p className="text-sm font-semibold text-light">{title}</p>
      <p className="mt-1 text-xs text-gray-400">{subtitle}</p>
    </article>
  );
}

function normalizeType(contact: AnyRecord): string {
  return String(contact.type || contact.contact_type || '').trim().toLowerCase();
}

function isLeadType(contact: AnyRecord): boolean {
  const type = normalizeType(contact);
  return type === 'promoter' || type === 'investor' || type === 'marketing' || type === 'business';
}

function isPersonalType(contact: AnyRecord): boolean {
  const type = normalizeType(contact);
  return type === 'personal' || type === 'family';
}

function normalizeTaskCategory(task: AnyRecord): string {
  return String(task.category || 'general').trim().toLowerCase();
}

function nextLeadStage(stage: string): string {
  const ordered = ['prospect', 'qualified', 'contacted', 'meeting_scheduled', 'proposal', 'won'];
  const normalized = String(stage || 'prospect').trim().toLowerCase();
  const idx = ordered.indexOf(normalized);
  if (idx < 0) return 'prospect';
  if (idx >= ordered.length - 1) return ordered[ordered.length - 1];
  return ordered[idx + 1];
}

function previousLeadStage(stage: string): string {
  const ordered = ['prospect', 'qualified', 'contacted', 'meeting_scheduled', 'proposal', 'won'];
  const normalized = String(stage || 'prospect').trim().toLowerCase();
  const idx = ordered.indexOf(normalized);
  if (idx <= 0) return ordered[0];
  return ordered[idx - 1];
}

function contactSubtitle(contact: AnyRecord): string {
  const type = normalizeType(contact) || 'unknown';
  return `${type} • ${contact.phone || contact.email || 'No contact info'}`;
}

function contactNotes(contact: AnyRecord): string {
  const raw = String(contact.notes || '').trim();
  if (!raw) return 'No notes yet.';
  return raw;
}

function LeadColumn({ title, count, contacts }: { title: string; count: number; contacts: AnyRecord[] }) {
  return (
    <article className="rounded-lg border border-gray-900 bg-[#050505] p-4">
      <div className="mb-3 flex items-center justify-between gap-3 border-b border-gray-900 pb-2">
        <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-light">{title}</h3>
        <span className="rounded-full border border-emerald-900/50 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300">{count}</span>
      </div>

      {contacts.length === 0 ? (
        <p className="text-xs text-gray-500">No contacts in this category.</p>
      ) : (
        <div className="space-y-2">
          {contacts.map((contact) => (
            <article key={contact.id} className="rounded border border-gray-900 bg-black/50 p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-light">{contact.name || 'Unnamed Contact'}</p>
                <span className="rounded-full border border-gray-800 px-2 py-1 text-[10px] uppercase tracking-[0.15em] text-gray-400">{String(contact.crm_stage || 'prospect')}</span>
              </div>
              <p className="mt-1 text-xs text-gray-400">{contactSubtitle(contact)}</p>
              <p className="mt-2 text-xs text-gray-500">{contactNotes(contact)}</p>
            </article>
          ))}
        </div>
      )}
    </article>
  );
}
