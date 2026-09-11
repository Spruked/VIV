import { Building2, RefreshCcw, Search, Sparkles } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ContactIOControls } from '@/components/ContactIOControls'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { API_URL } from '@/lib/api'
import { openDesktopOrb } from '@/lib/orb-integration'
import { useBusinessContext } from '@/providers/BusinessContextProvider'

export function Topbar() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { businessScope, setBusinessScope, businesses, isLoading } = useBusinessContext()

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-zinc-800 bg-zinc-950 px-5">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <div className="relative w-full max-w-xl">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-600" />
          <Input className="pl-9" placeholder="Signal scan: subjects, organizations, signals, events..." />
        </div>
        <div className="hidden items-center gap-2 lg:flex">
          <Building2 className="size-4 text-cyan-300" />
          <Select
            className="h-9 w-48"
            aria-label="Business context"
            value={businessScope}
            disabled={isLoading}
            onChange={(event) => {
              setBusinessScope(event.target.value)
              void queryClient.invalidateQueries()
            }}
          >
            <option value="all">All business contexts</option>
            {businesses.map((business) => (
              <option key={business.business_id} value={business.business_id}>{business.label}</option>
            ))}
          </Select>
        </div>
        <div className="hidden max-w-48 truncate rounded-md border border-zinc-800 px-2 py-1 text-xs text-zinc-500 xl:block">
          VIV - {API_URL}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <ContactIOControls />
        <Button variant="ghost" size="icon" onClick={() => void queryClient.invalidateQueries()}>
          <RefreshCcw className="size-4" />
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={() => {
            openDesktopOrb({ currentView: 'floating-orb', activeFilters: { businessScope } })
            navigate('/orb')
          }}
        >
          <Sparkles className="size-4" />
          ORB
        </Button>
      </div>
    </header>
  )
}
