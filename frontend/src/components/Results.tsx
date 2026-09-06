import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, ApiError, type Edit, type Job, type JobResult, type Verdict } from '../api'

const VERDICT_META: Record<Verdict, { label: string; cls: string }> = {
  ok: { label: 'OK', cls: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' },
  risk: { label: 'Риск', cls: 'border-amber-500/40 bg-amber-500/10 text-amber-400' },
  fail: { label: 'Несоответствие', cls: 'border-red-500/40 bg-red-500/10 text-red-400' },
}

const STATUS_META: Record<JobResult['status'], { label: string; cls: string }> = {
  pending: { label: 'В очереди', cls: 'text-zinc-400' },
  running: { label: 'Проверяется…', cls: 'text-sky-400' },
  done: { label: 'Готово', cls: 'text-emerald-400' },
  error: { label: 'Ошибка', cls: 'text-red-400' },
  cancelled: { label: 'Отменено', cls: 'text-zinc-500' },
}

function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return <span className="text-xs text-zinc-600">—</span>
  const meta = VERDICT_META[verdict]
  return (
    <span className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-medium ${meta.cls}`}>
      {meta.label}
    </span>
  )
}

function Spinner() {
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

function EditsSection({
  jobId,
  resultIndex,
  filename,
  edits,
  checked,
  onToggle,
  onSelectAll,
  onClear,
  onError,
}: {
  jobId: string
  resultIndex: number
  filename: string
  edits: Edit[]
  checked: ReadonlySet<string>
  onToggle: (id: string) => void
  onSelectAll: () => void
  onClear: () => void
  onError: (msg: string) => void
}) {
  const [fixing, setFixing] = useState(false)

  const handleFix = async () => {
    setFixing(true)
    try {
      const blob = await api.fixDocument(jobId, resultIndex, [...checked])
      const base = filename.replace(/\.[^.]+$/, '')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${base}_исправленная.docx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      if (e instanceof ApiError && e.detail) onError(e.detail)
      else onError(e instanceof Error ? e.message : 'Не удалось сформировать исправленный документ')
    } finally {
      setFixing(false)
    }
  }

  return (
    <div className="mt-5 border-t border-zinc-800 pt-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h4 className="text-sm font-semibold text-zinc-100">
          Предложенные правки{' '}
          <span className="text-xs font-normal text-zinc-400">
            выбрано {checked.size} из {edits.length}
          </span>
        </h4>
        <div className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={onSelectAll}
            className="cursor-pointer rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 py-1 font-medium text-zinc-300 transition-colors hover:bg-zinc-700"
          >
            Выбрать все
          </button>
          <button
            type="button"
            onClick={onClear}
            className="cursor-pointer rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 py-1 font-medium text-zinc-300 transition-colors hover:bg-zinc-700"
          >
            Снять все
          </button>
        </div>
      </div>

      <div className="space-y-3">
        {edits.map((edit) => {
          const isChecked = checked.has(edit.id)
          return (
            <div
              key={edit.id}
              className={`rounded-xl border p-4 transition-colors ${
                isChecked
                  ? 'border-sky-500/40 bg-sky-500/5'
                  : 'border-zinc-800 bg-zinc-900/40 opacity-70'
              }`}
            >
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => onToggle(edit.id)}
                  className="mt-1 h-4 w-4 shrink-0 cursor-pointer accent-sky-500"
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-zinc-100">{edit.title}</span>
                  {edit.reason && (
                    <span className="mt-1 block text-xs text-zinc-400">{edit.reason}</span>
                  )}
                </span>
              </label>
              <div className="mt-3 grid gap-3 pl-7 sm:grid-cols-2">
                <div>
                  <div className="mb-1 text-xs font-medium tracking-wide text-zinc-500 uppercase">
                    Было
                  </div>
                  <blockquote className="rounded-lg border-l-2 border-red-500/50 bg-zinc-950/60 px-3 py-2 text-xs whitespace-pre-wrap text-zinc-300">
                    {edit.original}
                  </blockquote>
                </div>
                <div>
                  <div className="mb-1 text-xs font-medium tracking-wide text-zinc-500 uppercase">
                    Будет
                  </div>
                  <blockquote className="rounded-lg border-l-2 border-emerald-500/50 bg-zinc-950/60 px-3 py-2 text-xs whitespace-pre-wrap text-zinc-200">
                    {edit.replacement}
                  </blockquote>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void handleFix()}
          disabled={fixing || checked.size === 0}
          className="flex cursor-pointer items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {fixing && <Spinner />}
          {fixing ? 'Формируется исправленный документ…' : 'Исправить ДИ'}
        </button>
        {fixing && (
          <span className="text-xs text-zinc-500">
            Это может занять до пары минут — не закрывайте страницу.
          </span>
        )}
      </div>
    </div>
  )
}

export default function Results({ job, onError }: { job: Job; onError: (msg: string) => void }) {
  // Выбранный результат — индекс в job.results (resultIndex), а не имя файла.
  const [selected, setSelected] = useState<number | null>(null)
  // Выбор правок по файлам: resultIndex -> набор выбранных editId.
  // Отсутствующая запись = выбраны все правки файла (значение по умолчанию).
  const [selection, setSelection] = useState<Record<number, ReadonlySet<string>>>({})
  const [fixingAll, setFixingAll] = useState(false)
  const [fixAllSummary, setFixAllSummary] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)

  // Если выбранный индекс вышел за пределы результатов — сбрасываем выбор
  useEffect(() => {
    if (selected !== null && selected >= job.results.length) {
      setSelected(null)
    }
  }, [job, selected])

  const selectedIndex = selected !== null && selected < job.results.length ? selected : -1
  const selectedResult = selectedIndex >= 0 ? job.results[selectedIndex] : null
  const done = job.status !== 'running'

  // Завершённые файлы (независимо от исхода) для индикатора прогресса
  const doneCount = job.results.filter(
    (r) => r.status === 'done' || r.status === 'error' || r.status === 'cancelled',
  ).length

  const handleCancel = async () => {
    setCancelling(true)
    try {
      await api.cancelJob(job.id)
    } catch (e) {
      if (e instanceof ApiError && e.detail) onError(e.detail)
      else onError(e instanceof Error ? e.message : 'Не удалось отменить проверку')
    } finally {
      setCancelling(false)
    }
  }

  const effectiveSelected = (resultIndex: number, edits: Edit[]): ReadonlySet<string> =>
    selection[resultIndex] ?? new Set(edits.map((e) => e.id))

  const updateSelection = (resultIndex: number, next: Set<string>) =>
    setSelection((prev) => ({ ...prev, [resultIndex]: next }))

  const toggleEdit = (resultIndex: number, edits: Edit[], id: string) => {
    const next = new Set(effectiveSelected(resultIndex, edits))
    if (next.has(id)) next.delete(id)
    else next.add(id)
    updateSelection(resultIndex, next)
  }

  // Пакетное исправление: только done-файлы с ≥1 выбранной правкой
  const fixAllItems = job.results
    .map((r, resultIndex) => ({
      resultIndex,
      editIds: r.status === 'done' ? [...effectiveSelected(resultIndex, r.edits ?? [])] : [],
    }))
    .filter((item) => item.editIds.length > 0)

  const handleFixAll = async () => {
    setFixingAll(true)
    setFixAllSummary(null)
    try {
      const blob = await api.fixAll(job.id, fixAllItems)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'ispravlennye_di.zip'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setFixAllSummary(
        `Отправлено на исправление: ${fixAllItems.length} файл(ов). ` +
          'Если какие-то файлы не удалось исправить, причины перечислены в _errors.txt внутри архива.',
      )
    } catch (e) {
      if (e instanceof ApiError && e.detail) onError(e.detail)
      else onError(e instanceof Error ? e.message : 'Не удалось выполнить пакетное исправление')
    } finally {
      setFixingAll(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-zinc-100">
          Результаты проверки{' '}
          {job.status === 'running' && (
            <>
              <span className="ml-2 inline-block animate-pulse text-sm font-normal text-sky-400">
                выполняется…
              </span>
              <span className="ml-2 text-sm font-normal text-zinc-400">
                Готово {doneCount} из {job.results.length}
              </span>
            </>
          )}
          {job.status === 'error' && (
            <span className="ml-2 text-sm font-normal text-red-400">завершилась с ошибкой</span>
          )}
        </h2>
        {job.status === 'running' && (
          <button
            type="button"
            onClick={() => void handleCancel()}
            disabled={cancelling}
            className="cursor-pointer rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-sm font-medium text-zinc-100 transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {cancelling ? 'Отменяется…' : 'Отменить'}
          </button>
        )}
      </div>

      {done && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-zinc-400">Скачать общий отчёт:</span>
              <a
                href={api.exportUrl(job.id, 'docx')}
                download
                className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-sky-500"
              >
                DOCX
              </a>
              <a
                href={api.exportUrl(job.id, 'md')}
                download
                className="rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-sm font-medium text-zinc-100 transition-colors hover:bg-zinc-700"
              >
                MD
              </a>
              <a
                href={api.exportUrl(job.id, 'html')}
                download
                className="rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-sm font-medium text-zinc-100 transition-colors hover:bg-zinc-700"
              >
                HTML
              </a>
            </div>
            <button
              type="button"
              onClick={() => void handleFixAll()}
              disabled={fixingAll || fixAllItems.length === 0}
              className="flex cursor-pointer items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {fixingAll && <Spinner />}
              {fixingAll ? 'Исправляются документы…' : 'Исправить все ДИ'}
            </button>
          </div>
          {fixingAll && (
            <p className="mt-3 text-xs text-zinc-500">
              Идёт пакетное исправление — по одному обращению к модели на каждую ДИ, это может
              занять несколько минут. Не закрывайте страницу.
            </p>
          )}
          {fixAllSummary && <p className="mt-3 text-xs text-emerald-400">{fixAllSummary}</p>}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-zinc-800 bg-zinc-900/80 text-xs text-zinc-400 uppercase">
              <th className="px-4 py-2.5 font-medium">Файл</th>
              <th className="px-4 py-2.5 font-medium">Статус</th>
              <th className="px-4 py-2.5 font-medium">Вердикт</th>
              <th className="px-4 py-2.5 font-medium">Правки</th>
              <th className="px-4 py-2.5 font-medium">Отчёт</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {job.results.map((r, resultIndex) => {
              const st = STATUS_META[r.status]
              const isSelected = selected === resultIndex
              return (
                <tr
                  key={resultIndex}
                  className={isSelected ? 'bg-sky-500/5' : 'hover:bg-zinc-900/50'}
                >
                  <td className="max-w-64 truncate px-4 py-2.5 text-zinc-200" title={r.filename}>
                    {r.filename}
                    {r.status === 'error' && r.error && (
                      <span className="mt-0.5 block truncate text-xs text-red-400" title={r.error}>
                        {r.error}
                      </span>
                    )}
                  </td>
                  <td className={`px-4 py-2.5 ${st.cls}`}>{st.label}</td>
                  <td className="px-4 py-2.5">
                    <VerdictBadge verdict={r.summaryVerdict} />
                  </td>
                  <td className="px-4 py-2.5">
                    {(r.edits?.length ?? 0) > 0 ? (
                      <span className="text-zinc-300">
                        {effectiveSelected(resultIndex, r.edits).size}/{r.edits.length}
                      </span>
                    ) : (
                      <span className="text-xs text-zinc-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    {r.report ? (
                      <button
                        type="button"
                        onClick={() => setSelected(isSelected ? null : resultIndex)}
                        className="cursor-pointer rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-100 transition-colors hover:bg-zinc-700"
                      >
                        {isSelected ? 'Скрыть' : 'Отчёт'}
                      </button>
                    ) : (
                      <span className="text-xs text-zinc-600">—</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {selectedResult?.report && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-5">
          <div className="mb-3 flex items-center justify-between gap-3 border-b border-zinc-800 pb-3">
            <h3 className="truncate text-sm font-semibold text-zinc-100">
              Отчёт: {selectedResult.filename}
            </h3>
            <button
              type="button"
              onClick={() => setSelected(null)}
              aria-label="Закрыть отчёт"
              className="shrink-0 cursor-pointer text-zinc-500 transition-colors hover:text-zinc-200"
            >
              <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M3 3l10 10M13 3L3 13" />
              </svg>
            </button>
          </div>
          {selectedResult.textTruncated && (
            <p className="mb-3 text-xs text-zinc-500">
              Текст ДИ слишком длинный — проверка выполнена по первым ~120 000 символов.
            </p>
          )}
          <article className="md-report overflow-x-auto">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedResult.report}</ReactMarkdown>
          </article>
          {(selectedResult.edits?.length ?? 0) > 0 && (
            <EditsSection
              jobId={job.id}
              resultIndex={selectedIndex}
              filename={selectedResult.filename}
              edits={selectedResult.edits}
              checked={effectiveSelected(selectedIndex, selectedResult.edits)}
              onToggle={(id) => toggleEdit(selectedIndex, selectedResult.edits, id)}
              onSelectAll={() =>
                updateSelection(selectedIndex, new Set(selectedResult.edits.map((e) => e.id)))
              }
              onClear={() => updateSelection(selectedIndex, new Set<string>())}
              onError={onError}
            />
          )}
        </div>
      )}
    </div>
  )
}
