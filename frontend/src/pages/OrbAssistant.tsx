import { type FormEvent, useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Bot, Send } from 'lucide-react'
import { toast } from 'sonner'
import { SectionHeader } from '@/components/SectionHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { updateVIVContext } from '@/lib/orb-integration'

type ChatMessage = {
  role: 'operator' | 'orb'
  text: string
  meta?: string
}

export default function OrbAssistant() {
  const [prompt, setPrompt] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'orb', text: 'VIV Command Node online. Ask about dossiers, relationships, signals, timelines, events, or current system state.', meta: 'local' },
  ])

  const askOrb = useMutation({
    mutationFn: async (text: string) =>
      api.post('/cali/orb/respond', {
        prompt: text,
        context: { surface: 'viv_frontend', current_path: '/orb' },
        emotion: 'operator_clear',
      }),
    onSuccess: (response) => {
      const text = response.data.response_text || response.data.response || 'No response text.'
      const core = response.data.metadata?.llm_core || response.data.metadata?.provider || 'cali'
      setMessages((current) => [...current, { role: 'orb', text, meta: core }])
    },
    onError: (error) => toast.error(error.message),
  })

  useEffect(() => {
    updateVIVContext({
      currentView: 'orb',
      lastAction: 'orb_chat_open',
    })
  }, [])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = prompt.trim()
    if (!text) return
    setMessages((current) => [...current, { role: 'operator', text }])
    setPrompt('')
    askOrb.mutate(text)
  }

  return (
    <div>
      <SectionHeader title="Command Node" detail="Conversational access to VIV context and the local ORB reasoning endpoint." />

      <Card className="mx-auto flex h-[calc(100vh-10rem)] max-w-5xl flex-col">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Bot className="size-5" />
              VIV Command Node
            </CardTitle>
            <Badge variant="success">/cali/orb/respond</Badge>
          </div>
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col gap-4">
          <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-zinc-800 bg-black/30 p-4">
            <div className="flex flex-col gap-3">
              {messages.map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  className={
                    message.role === 'operator'
                      ? 'ml-auto max-w-[80%] rounded-lg bg-white p-3 text-sm text-zinc-950'
                      : 'mr-auto max-w-[80%] rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm text-zinc-200'
                  }
                >
                  <p>{message.text}</p>
                  {message.meta ? <p className="mt-2 text-xs opacity-60">{message.meta}</p> : null}
                </div>
              ))}
              {askOrb.isPending ? <div className="mr-auto rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm text-zinc-500">Thinking...</div> : null}
            </div>
          </div>
          <form className="flex gap-3" onSubmit={submit}>
            <Textarea className="min-h-16 flex-1" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Ask VIV about a dossier, relationship, signal, timeline, event, or system state..." />
            <Button variant="primary" className="h-16" disabled={askOrb.isPending || !prompt.trim()}>
              <Send className="size-4" />
              Send
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
