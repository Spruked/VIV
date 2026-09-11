import type { ReactNode } from 'react'

export function Modal({ open, children }: { open: boolean; children: ReactNode }) {
  if (!open) return null
  return <>{children}</>
}
