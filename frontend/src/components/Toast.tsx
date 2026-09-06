import { useEffect } from 'react'

export interface ToastData {
  type: 'error' | 'success' | 'info'
  text: string
}

const COLORS: Record<ToastData['type'], string> = {
  error: 'border-red-500/50 bg-red-950/90 text-red-200',
  success: 'border-emerald-500/50 bg-emerald-950/90 text-emerald-200',
  info: 'border-sky-500/50 bg-sky-950/90 text-sky-200',
}

export default function Toast({
  toast,
  onClose,
}: {
  toast: ToastData | null
  onClose: () => void
}) {
  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(onClose, 6000)
    return () => window.clearTimeout(t)
  }, [toast, onClose])

  if (!toast) return null

  return (
    <div
      role="alert"
      className={`fixed right-4 bottom-4 z-50 flex max-w-md items-start gap-3 rounded-xl border px-4 py-3 shadow-lg backdrop-blur ${COLORS[toast.type]}`}
    >
      <span className="flex-1 text-sm">{toast.text}</span>
      <button
        type="button"
        onClick={onClose}
        aria-label="Закрыть"
        className="shrink-0 cursor-pointer text-current opacity-60 hover:opacity-100"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M3 3l10 10M13 3L3 13" />
        </svg>
      </button>
    </div>
  )
}
