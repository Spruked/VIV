import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { updateVIVContext } from '@/lib/orb-integration'

export type BusinessContextRecord = {
  business_id: string
  label: string
  isolation?: 'scoped' | 'strict'
  status?: string
}

type BusinessContextValue = {
  businessScope: string
  setBusinessScope: (value: string) => void
  businesses: BusinessContextRecord[]
  activeBusiness: BusinessContextRecord | null
  isLoading: boolean
}

const STORAGE_KEY = 'viv_business_scope'
const LEGACY_STORAGE_KEY = 'cali_business_scope'
const BusinessContext = createContext<BusinessContextValue | null>(null)

function initialBusinessScope() {
  const fromUrl = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('business_scope')?.trim() : ''
  return fromUrl || localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY) || 'all'
}

export function BusinessContextProvider({ children }: { children: ReactNode }) {
  const [businessScope, setBusinessScopeState] = useState(initialBusinessScope)

  const businessesQuery = useQuery({
    queryKey: ['business-contexts'],
    queryFn: async () => {
      const response = await api.get('/cali/intelligence/businesses')
      return (response.data?.businesses || []) as BusinessContextRecord[]
    },
    staleTime: 60_000,
  })

  const businesses = businessesQuery.data || []
  const activeBusiness = useMemo(
    () => businesses.find((item) => item.business_id === businessScope) || null,
    [businesses, businessScope],
  )

  function setBusinessScope(value: string) {
    const next = value || 'all'
    setBusinessScopeState(next)
    localStorage.setItem(STORAGE_KEY, next)
    localStorage.setItem(LEGACY_STORAGE_KEY, next)
  }

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, businessScope)
    localStorage.setItem(LEGACY_STORAGE_KEY, businessScope)
    updateVIVContext({
      activeFilters: {
        businessScope,
        businessLabel: activeBusiness?.label || 'All',
      },
      lastAction: `business_context:${businessScope}`,
    })
  }, [businessScope, activeBusiness?.label])

  const value = useMemo<BusinessContextValue>(
    () => ({
      businessScope,
      setBusinessScope,
      businesses,
      activeBusiness,
      isLoading: businessesQuery.isLoading,
    }),
    [businessScope, businesses, activeBusiness, businessesQuery.isLoading],
  )

  return <BusinessContext.Provider value={value}>{children}</BusinessContext.Provider>
}

export function useBusinessContext() {
  const context = useContext(BusinessContext)
  if (!context) throw new Error('useBusinessContext must be used inside BusinessContextProvider')
  return context
}
