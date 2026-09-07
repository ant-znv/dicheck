import type { Verdict } from '../api'

/** Скачивание blob как файла (создаём временную ссылку и сразу освобождаем). */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function Spinner() {
  return (
    <svg
      className="animate-spin"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    >
      <path d="M8 1.5a6.5 6.5 0 1 1-6.5 6.5" />
    </svg>
  )
}

const VERDICT_META: Record<Verdict, { label: string; cls: string }> = {
  ok: { label: 'OK', cls: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' },
  risk: { label: 'Риск', cls: 'border-amber-500/40 bg-amber-500/10 text-amber-400' },
  fail: { label: 'Несоответствие', cls: 'border-red-500/40 bg-red-500/10 text-red-400' },
}

/**
 * Бейдж вердикта в цветах результатов проверки.
 * Для неизвестного значения (или null) — тихий прочерк/сырой текст.
 */
export function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return <span className="text-xs text-zinc-600">—</span>
  const meta = VERDICT_META[verdict as Verdict]
  if (!meta) return <span className="text-xs text-zinc-400">{verdict}</span>
  return (
    <span className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-medium ${meta.cls}`}>
      {meta.label}
    </span>
  )
}

/** «До» (исходная проверка) / «После» (исправленная версия). */
export function OriginBadge({ origin }: { origin: 'check' | 'fix' }) {
  const meta =
    origin === 'fix'
      ? { label: 'После', cls: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' }
      : { label: 'До', cls: 'border-zinc-600 bg-zinc-800 text-zinc-300' }
  return (
    <span className={`inline-block shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-medium ${meta.cls}`}>
      {meta.label}
    </span>
  )
}

/** Метод исправления fix-версии: docx / text / llm. */
export function FixMethodBadge({ method }: { method: string | null }) {
  if (!method) return null
  const label = method === 'docx' ? 'docx' : method === 'text' ? 'текст' : method === 'llm' ? 'LLM' : method
  return (
    <span className="inline-block shrink-0 rounded-full border border-sky-500/40 bg-sky-500/10 px-2.5 py-0.5 text-xs font-medium text-sky-400">
      {label}
    </span>
  )
}

/** Дата-время в компактном формате «ДД.ММ.ГГГГ ЧЧ:ММ»; при непарсируемом значении — как есть. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export const historyInputCls =
  'w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 outline-none transition-colors focus:border-sky-500 disabled:opacity-50'

export const historyBtnCls =
  'flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-sm font-medium text-zinc-100 transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50'

export const historyBtnPrimaryCls =
  'flex cursor-pointer items-center gap-2 rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50'

export const historyBtnSmallCls =
  'cursor-pointer rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-100 transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50'
