import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type State = {
  error: Error | null
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('VIV terminal error', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-950 p-6">
        <Card className="max-w-xl">
          <CardHeader>
            <CardTitle>VIV terminal fault</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p className="text-sm text-zinc-400">{this.state.error.message}</p>
            <Button variant="primary" onClick={() => window.location.reload()}>
              Reboot Terminal
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }
}
