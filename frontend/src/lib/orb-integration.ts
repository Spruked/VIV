import type { Contact, PipelineItem } from '@/types'

export interface VIVContextPayload {
  currentPath: string
  currentView: string
  user: string
  timestamp: string
  selectedContact?: Contact | null
  selectedPipelineItem?: PipelineItem | null
  pipelineSummary?: {
    total: number
    byStage: Record<string, number>
  }
  activeFilters?: Record<string, unknown>
  unreadEmails?: number
  highPriorityTasks?: number
  lastAction?: string
}

declare global {
  interface Window {
    __VIV_CONTEXT?: VIVContextPayload
    __CALI_CRM_CONTEXT?: VIVContextPayload
  }
}

export const vivContext = {
  current: {
    currentPath: '/',
    currentView: 'dashboard',
    user: 'bryan@spruked.com',
    timestamp: new Date().toISOString(),
  } as VIVContextPayload,
}

export function updateVIVContext(payload: Partial<VIVContextPayload>) {
  const nextContext: VIVContextPayload = {
    ...vivContext.current,
    ...payload,
    timestamp: new Date().toISOString(),
  }

  vivContext.current = nextContext
  window.__VIV_CONTEXT = nextContext

  // Compatibility mirror for older ORB and integration surfaces while VIV naming becomes canonical.
  window.__CALI_CRM_CONTEXT = nextContext

  window.dispatchEvent(new CustomEvent('viv-context-update', { detail: nextContext }))
  window.dispatchEvent(new CustomEvent('cali-crm-context-update', { detail: nextContext }))
  window.postMessage({ type: 'VIV_CONTEXT_UPDATE', payload: nextContext }, '*')
  window.postMessage({ type: 'CALI_CRM_CONTEXT_UPDATE', payload: nextContext }, '*')
}

export function openDesktopOrb(payload: Partial<VIVContextPayload> = {}) {
  updateVIVContext({
    ...payload,
    lastAction: 'open_desktop_orb',
  })
  window.dispatchEvent(new CustomEvent('viv-open-orb', { detail: vivContext.current }))
  window.dispatchEvent(new CustomEvent('cali-crm-open-orb', { detail: vivContext.current }))
  window.postMessage({ type: 'OPEN_ORB', payload: vivContext.current }, '*')
}

export function getVIVContext() {
  return vivContext.current
}

// Backward-compatible exports for older modules. New code should use the VIV names above.
export type CRMContextPayload = VIVContextPayload
export const crmContext = vivContext
export const updateCRMContext = updateVIVContext
export const getCRMContext = getVIVContext
