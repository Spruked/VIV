import { useRef } from 'react'
import { Download, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useBusinessContext } from '@/providers/BusinessContextProvider'

type ContactFormat = 'vcf' | 'csv'
type CsvSource = 'gmail' | 'outlook' | 'generic'

function detectCsvSource(content: string): CsvSource {
  const header = String(content || '').split(/\r?\n/, 1)[0]?.toLowerCase() || ''
  const looksGoogle =
    header.includes('e-mail 1 - value') ||
    header.includes('phone 1 - value') ||
    (header.includes('given name') && header.includes('family name'))
  if (looksGoogle) return 'gmail'

  const looksOutlook =
    header.includes('e-mail address') ||
    header.includes('mobile phone') ||
    (header.includes('first name') && header.includes('last name') && header.includes('company'))
  if (looksOutlook) return 'outlook'

  return 'generic'
}

function mapCsvHeader(content: string, replacements: Array<[string, string]>) {
  const text = String(content || '')
  const match = text.match(/^([^\r\n]*)(\r?\n|$)/)
  if (!match) return text
  let header = match[1]
  for (const [from, to] of replacements) header = header.replaceAll(from, to)
  return header + match[2] + text.slice(match[0].length)
}

function isVivCsv(content: string) {
  const header = String(content || '').split(/\r?\n/, 1)[0]?.toLowerCase() || ''
  return (
    header.includes('viv business scope') ||
    header.includes('viv business context') ||
    header.includes('viv relationship') ||
    header.includes('segment tags') ||
    header.includes('group or segment') ||
    header.includes('lifecycle id')
  )
}

function normalizeVivCsv(content: string) {
  return mapCsvHeader(content, [
    ['Relationship Type', 'Type'],
    ['Role or Job Title', 'Job Title'],
    ['Lifecycle ID', 'CRM Stage'],
    ['VIV Business Context', 'VIV Business Scope'],
    ['Group or Segment', 'Segment Tags'],
  ])
}

function presentVivCsv(content: string) {
  return mapCsvHeader(content, [
    ['Type', 'Relationship Type'],
    ['CRM Stage', 'Lifecycle ID'],
    ['Lead Source', 'Source'],
    ['Business Scope', 'VIV Business Context'],
    ['Relationship', 'VIV Relationship'],
    ['Segment Tags', 'Group or Segment'],
  ])
}

function normalizeVivVcard(content: string) {
  return String(content || '')
    .replace(/^X-VIV-BUSINESS-CONTEXT:/gim, 'X-CALI-BUSINESS-SCOPE:')
    .replace(/^X-VIV-RELATIONSHIP:/gim, 'X-CALI-RELATIONSHIP:')
    .replace(/^X-VIV-SEGMENT:/gim, 'X-CALI-SEGMENT:')
}

function presentVivVcard(content: string) {
  return String(content || '')
    .replace(/^X-CALI-BUSINESS-SCOPE:/gim, 'X-VIV-BUSINESS-CONTEXT:')
    .replace(/^X-CALI-RELATIONSHIP:/gim, 'X-VIV-RELATIONSHIP:')
    .replace(/^X-CALI-SEGMENT:/gim, 'X-VIV-SEGMENT:')
}

function importedContactIds(result: any): string[] {
  const ids = new Set<string>()
  for (const item of Array.isArray(result?.merge_audit) ? result.merge_audit : []) {
    const id = String(item?.contact_id || '').trim()
    if (id) ids.add(id)
  }
  for (const id of Array.isArray(result?.contact_ids) ? result.contact_ids : []) {
    const value = String(id || '').trim()
    if (value) ids.add(value)
  }
  return Array.from(ids)
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function ContactIOControls() {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const { businessScope } = useBusinessContext()

  async function ensurePackages(ids: string[]) {
    if (!ids.length) return 0
    const response = await api.post('/cali/intelligence/dossiers/packages/ensure', { contact_ids: ids })
    return Number(response.data?.created_or_verified || 0)
  }

  async function importFile(file: File) {
    try {
      const lowerName = file.name.toLowerCase()
      const isCsv = lowerName.endsWith('.csv') || file.type.toLowerCase().includes('csv')
      const targetScope = businessScope === 'all' ? 'personal' : businessScope

      if (isCsv) {
        const content = await file.text()
        const source = detectCsvSource(content)

        if (source === 'generic' && isVivCsv(content)) {
          const response = await api.post('/cali/intelligence/dossiers/import/csv', {
            content: normalizeVivCsv(content),
            business_scope: targetScope,
            run_relationship_scan: false,
          })
          const result = response.data || {}
          const ids = importedContactIds(result)
          const packageCount = await ensurePackages(ids)
          toast.success(
            `VIV dossiers imported - ${Number(result.created || 0)} new - ${Number(result.existing_exact_email || 0)} matched - ${Number(result.phone_review_queued || 0)} review - ${packageCount} packages ready`,
          )
          window.dispatchEvent(new CustomEvent('cali-contacts-imported', { detail: result }))
          return
        }

        const form = new FormData()
        form.append('file', file)
        const response = await api.post(`/cali/contacts/import/csv/${source}`, form, {
          params: {
            default_contact_type: targetScope === 'personal' ? 'personal' : 'professional',
            default_stage: 'prospect',
          },
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        const result = response.data || {}
        const ids = importedContactIds(result)
        const dossierResponse = await api.post('/cali/intelligence/dossiers/backfill', {
          business_scope: targetScope,
          contact_ids: ids,
          only_unscoped: true,
        })
        const counts = result.counts || {}
        const dossierCount = Number(dossierResponse.data?.roles_assigned || 0)
        const packageCount = Number(dossierResponse.data?.packages_ready || 0)
        toast.success(
          `Dossiers imported (${source}) - ${Number(counts.created || 0)} new - ${Number(counts.merged || 0)} merged - ${dossierCount} contexts assigned - ${packageCount} packages ready - ${Number(counts.review_candidates || 0)} review - ${Number(counts.errors || 0)} errors`,
        )
        window.dispatchEvent(new CustomEvent('cali-contacts-imported', { detail: { ...result, dossier_backfill: dossierResponse.data } }))
        return
      }

      const content = normalizeVivVcard(await file.text())
      const response = await api.post('/cali/intelligence/vcard/import', {
        content,
        business_scope: targetScope,
        run_relationship_scan: false,
      })
      const result = response.data || {}
      const packageCount = await ensurePackages(importedContactIds(result))
      const seen = Number(result.cards_seen || 0)
      toast.success(
        `Dossiers compiled - ${seen} read - ${Number(result.created || 0)} new - ${Number(result.existing_exact_email || 0)} matched - ${Number(result.phone_review_queued || 0)} review - ${packageCount} packages ready`,
      )
      window.dispatchEvent(new CustomEvent('cali-contacts-imported', { detail: result }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Dossier import failed')
    } finally {
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function exportContacts(format: ContactFormat) {
    try {
      const endpoint = format === 'csv' ? '/cali/intelligence/csv/export' : '/cali/intelligence/vcard/export'
      const response = await api.post(
        endpoint,
        { contact_ids: [], business_scope: businessScope },
        { responseType: 'blob' },
      )
      let blob = response.data as Blob
      if (format === 'vcf') {
        blob = new Blob([presentVivVcard(await blob.text())], { type: 'text/vcard; charset=utf-8' })
      } else {
        blob = new Blob([presentVivCsv(await blob.text())], { type: 'text/csv; charset=utf-8' })
      }
      const scope = businessScope === 'all' ? 'viv-dossiers' : `viv-${businessScope}-dossiers`
      triggerDownload(blob, `${scope}.${format}`)
      toast.success(format === 'csv' ? 'VIV CSV dossier file created' : 'VIV vCard dossier file created')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Dossier export failed')
    }
  }

  async function downloadTemplate(format: ContactFormat) {
    try {
      const response = await api.get(`/cali/intelligence/dossiers/templates/${format}`, { responseType: 'blob' })
      triggerDownload(response.data as Blob, `viv-dossier-template.${format}`)
      toast.success(`${format.toUpperCase()} dossier template downloaded`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Template download failed')
    }
  }

  return (
    <div className="hidden items-center gap-1.5 2xl:flex">
      <input
        ref={inputRef}
        className="hidden"
        type="file"
        accept=".vcf,.csv,text/vcard,text/x-vcard,text/csv"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) void importFile(file)
        }}
      />
      <Button size="sm" variant="secondary" onClick={() => inputRef.current?.click()} title="Import VCF, Google CSV, Outlook CSV, or VIV CSV dossiers">
        <Upload className="size-3.5" />
        Import dossiers
      </Button>
      <Button size="sm" variant="secondary" onClick={() => void downloadTemplate('vcf')} title="Download the expanded VIV vCard template">
        <Download className="size-3.5" />
        VCF Template
      </Button>
      <Button size="sm" variant="secondary" onClick={() => void downloadTemplate('csv')} title="Download the expanded VIV CSV template">
        <Download className="size-3.5" />
        CSV Template
      </Button>
      <Button size="sm" variant="secondary" onClick={() => void exportContacts('vcf')} title="Export dossiers as VIV vCard">
        <Download className="size-3.5" />
        Export VCF
      </Button>
      <Button size="sm" variant="secondary" onClick={() => void exportContacts('csv')} title="Export dossiers as CSV">
        <Download className="size-3.5" />
        Export CSV
      </Button>
    </div>
  )
}
