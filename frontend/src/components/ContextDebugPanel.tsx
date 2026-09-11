import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getVIVContext, type VIVContextPayload } from '@/lib/orb-integration'

export function ContextDebugPanel() {
  const [context, setContext] = useState<VIVContextPayload>(() => getVIVContext())

  useEffect(() => {
    const handler = (event: Event) => {
      const custom = event as CustomEvent<VIVContextPayload>
      setContext(custom.detail)
    }
    window.addEventListener('viv-context-update', handler)
    return () => window.removeEventListener('viv-context-update', handler)
  }, [])

  return (
    <Card>
      <CardHeader>
        <CardTitle>ORB Command Bridge</CardTitle>
        <CardDescription>
          Shares the current VIV command context with the ORB node. It is not a dossier store or signal sync.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center justify-between rounded-lg border border-zinc-800 p-3">
          <span className="text-sm text-zinc-400">Terminal</span>
          <Badge>{context.currentView}</Badge>
        </div>
        <div className="flex items-center justify-between rounded-lg border border-zinc-800 p-3">
          <span className="text-sm text-zinc-400">Path</span>
          <span className="text-sm text-zinc-300">{context.currentPath}</span>
        </div>
        <pre className="max-h-72 overflow-auto rounded-lg border border-zinc-800 bg-black/40 p-3 text-xs text-zinc-400">
          {JSON.stringify(context, null, 2)}
        </pre>
      </CardContent>
    </Card>
  )
}
