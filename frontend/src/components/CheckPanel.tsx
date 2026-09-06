import { useRef, useState, type DragEvent } from 'react'

export interface CheckContext {
  contractSubject: string
  employmentType: string
  extraContext: string
}

const ACCEPTED = ['.docx', '.doc', '.pdf', '.txt', '.md', '.odt']
const ACCEPT_ATTR = ACCEPTED.join(',')

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

function isAccepted(file: File): boolean {
  const name = file.name.toLowerCase()
  return ACCEPTED.some((ext) => name.endsWith(ext))
}

interface Props {
  starting: boolean
  onStart: (files: File[], ctx: CheckContext) => void
  onRejected: (names: string[]) => void
}

const inputCls =
  'w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 outline-none transition-colors focus:border-sky-500'

export default function CheckPanel({ starting, onStart, onRejected }: Props) {
  const [files, setFiles] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [ctxOpen, setCtxOpen] = useState(false)
  const [ctx, setCtx] = useState<CheckContext>({
    contractSubject: '',
    employmentType: '',
    extraContext: '',
  })
  const inputRef = useRef<HTMLInputElement>(null)

  const addFiles = (incoming: Iterable<File>) => {
    const accepted: File[] = []
    const rejected: string[] = []
    for (const f of incoming) {
      if (isAccepted(f)) accepted.push(f)
      else rejected.push(f.name)
    }
    if (rejected.length > 0) onRejected(rejected)
    if (accepted.length > 0) {
      setFiles((prev) => {
        const existing = new Set(prev.map((f) => `${f.name}:${f.size}`))
        const fresh = accepted.filter((f) => !existing.has(`${f.name}:${f.size}`))
        return [...prev, ...fresh]
      })
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    addFiles(e.dataTransfer.files)
  }

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleStart = () => {
    if (files.length === 0 || starting) return
    onStart(files, ctx)
  }

  return (
    <div className="space-y-4">
      {/* Dropzone */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragOver
            ? 'border-sky-500 bg-sky-500/10'
            : 'border-zinc-700 bg-zinc-900/50 hover:border-zinc-500'
        }`}
      >
        <svg
          className="mx-auto mb-3 text-zinc-500"
          width="40"
          height="40"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="12" y1="18" x2="12" y2="11" />
          <polyline points="9 14 12 11 15 14" />
        </svg>
        <p className="text-sm text-zinc-300">
          Перетащите файлы сюда или{' '}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="cursor-pointer font-medium text-sky-400 underline underline-offset-2 hover:text-sky-300"
          >
            выберите на диске
          </button>
        </p>
        <p className="mt-1 text-xs text-zinc-500">
          Поддерживаются: {ACCEPTED.join(', ')}
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT_ATTR}
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      {/* Список файлов */}
      {files.length > 0 && (
        <ul className="divide-y divide-zinc-800 rounded-xl border border-zinc-800 bg-zinc-900/50">
          {files.map((f, i) => (
            <li key={`${f.name}:${f.size}`} className="flex items-center gap-3 px-4 py-2.5">
              <span className="flex-1 truncate text-sm text-zinc-200">{f.name}</span>
              <span className="text-xs text-zinc-500">{formatSize(f.size)}</span>
              <button
                type="button"
                onClick={() => removeFile(i)}
                aria-label={`Удалить ${f.name}`}
                className="cursor-pointer text-zinc-500 transition-colors hover:text-red-400"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <path d="M3 3l10 10M13 3L3 13" />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Контекст проверки */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/50">
        <button
          type="button"
          onClick={() => setCtxOpen((v) => !v)}
          className="flex w-full cursor-pointer items-center justify-between px-4 py-3 text-sm font-medium text-zinc-300 hover:text-zinc-100"
        >
          <span>Контекст госконтракта (необязательно)</span>
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={`transition-transform ${ctxOpen ? 'rotate-180' : ''}`}
          >
            <polyline points="4 6 8 10 12 6" />
          </svg>
        </button>
        {ctxOpen && (
          <div className="space-y-3 border-t border-zinc-800 p-4">
            <div>
              <label htmlFor="contractSubject" className="mb-1 block text-xs text-zinc-400">
                Предмет госконтракта
              </label>
              <input
                id="contractSubject"
                value={ctx.contractSubject}
                onChange={(e) => setCtx({ ...ctx, contractSubject: e.target.value })}
                placeholder="Например: выполнение СМР по объекту…"
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="employmentType" className="mb-1 block text-xs text-zinc-400">
                Занятость по контракту
              </label>
              <select
                id="employmentType"
                value={ctx.employmentType}
                onChange={(e) => setCtx({ ...ctx, employmentType: e.target.value })}
                className={inputCls}
              >
                <option value="">Не указано</option>
                <option value="full">Полностью</option>
                <option value="partial">Частично</option>
              </select>
            </div>
            <div>
              <label htmlFor="extraContext" className="mb-1 block text-xs text-zinc-400">
                Дополнительный контекст
              </label>
              <textarea
                id="extraContext"
                value={ctx.extraContext}
                onChange={(e) => setCtx({ ...ctx, extraContext: e.target.value })}
                rows={3}
                placeholder="Требования к персоналу, особые условия и т.п."
                className={`${inputCls} resize-y`}
              />
            </div>
          </div>
        )}
      </div>

      {/* Запуск */}
      <button
        type="button"
        onClick={handleStart}
        disabled={files.length === 0 || starting}
        className="w-full cursor-pointer rounded-xl bg-sky-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {starting
          ? 'Запуск…'
          : files.length > 0
            ? `Запустить проверку (${files.length} ${plural(files.length)})`
            : 'Запустить проверку'}
      </button>
    </div>
  )
}

function plural(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'файл'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'файла'
  return 'файлов'
}
