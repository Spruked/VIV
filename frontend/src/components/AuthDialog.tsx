import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { clearAuthToken, getStoredToken, saveToken, TOKEN_KEY } from '@/lib/api'

export function AuthDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [token, setToken] = useState(() => getStoredToken())

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-lg rounded-lg border border-zinc-800 bg-zinc-950 p-5 shadow-2xl shadow-black">
        <div className="mb-4">
          <h2 className="text-base font-semibold text-zinc-100">Operator Cipher</h2>
          <p className="mt-1 text-sm text-zinc-500">Stored locally under {TOKEN_KEY} and sent as Bearer auth.</p>
        </div>
        <Input
          autoFocus
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="VIV_OPERATOR_CIPHER"
          type="password"
        />
        <div className="mt-5 flex justify-between gap-3">
          <Button
            variant="ghost"
            onClick={() => {
              localStorage.removeItem(TOKEN_KEY)
              clearAuthToken()
              setToken('')
              toast.success('Cipher cleared')
            }}
          >
            Clear
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Stand Down
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                saveToken(token.trim())
                toast.success('Cipher saved')
                onClose()
              }}
              disabled={!token.trim()}
            >
              Save cipher
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
