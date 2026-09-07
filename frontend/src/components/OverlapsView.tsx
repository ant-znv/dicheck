import { useEffect, useState } from 'react'
import {
  ApiError,
  api,
  formatError,
  type HistoryDocumentSummary,
  type OverlapGroup,
  type OverlapReport,
  type OverlapSkipped,
} from '../api'
import {
  Spinner,
  formatDateTime,
  historyBtnPrimaryCls,
  historyBtnSmallCls,
} from './HistoryShared'

/** Лимит списка документов для выбора (ограничение выборки одним запросом). */
const DOCS_LIMIT = 500

interface Props {
  onError: (msg: string) => void
  onSuccess: (msg: string) => void
}

/** Отображаемое имя документа: должность, а если не заполнена — название файла. */
function displayName(d: HistoryDocumentSummary): string {
  return d.position.trim() || d.title
}

/** «1 документ пропущен» / «3 документа пропущено» / «5 документов пропущено». */
function skippedLabel(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return `${n} документ пропущен`
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${n} документа пропущено`
  return `${n} документов пропущено`
}

const deptBadgeCls =
  'inline-block shrink-0 rounded-full border border-sky-500/40 bg-sky-500/10 px-2.5 py-0.5 text-xs font-medium text-sky-400'

/**
 * Карточка одной группы пересечений: формулировка обязанности, комментарий LLM
 * и участники — визуально сгруппированные по документам (бейдж подразделения +
 * должность, ниже — формулировки обязанностей из этого документа).
 */
function GroupCard({ group }: { group: OverlapGroup }) {
  const byDoc = new Map<number, { position: string; department: string; duties: string[] }>()
  for (const it of group.items) {
    const cur = byDoc.get(it.documentId)
    if (cur) cur.duties.push(it.duty)
    else
      byDoc.set(it.documentId, {
        position: it.position,
        department: it.department,
        duties: [it.duty],
      })
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <h4 className="text-sm font-semibold text-zinc-100">{group.duty}</h4>
      {group.comment.trim() && <p className="mt-1 text-xs text-zinc-400">{group.comment}</p>}
      <div className="mt-3 space-y-2">
        {[...byDoc.entries()].map(([docId, doc]) => (
          <div key={docId} className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className={deptBadgeCls}>{doc.department.trim() || 'Без подразделения'}</span>
              <span className="min-w-0 truncate text-sm text-zinc-200">
                {doc.position.trim() || `Документ #${docId}`}
              </span>
            </div>
            {doc.duties.map((duty, i) => (
              <p key={i} className="mt-1 text-xs whitespace-pre-wrap text-zinc-300">
                {duty}
              </p>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Свёрнутый блок пропущенных документов: документ + причина. */
function SkippedList({ skipped }: { skipped: OverlapSkipped[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm font-medium text-zinc-300 transition-colors hover:bg-zinc-800 hover:text-zinc-100"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
        >
          <polyline points="4 6 8 10 12 6" />
        </svg>
        {open
          ? 'Скрыть пропущенные документы'
          : `Показать пропущенные документы (${skipped.length})`}
      </button>
      {open && (
        <ul className="mt-2 divide-y divide-zinc-800 rounded-lg border border-zinc-800 bg-zinc-950/40">
          {skipped.map((s) => (
            <li key={s.documentId} className="px-3 py-2">
              <span className="block text-sm text-zinc-200">
                {s.position.trim() || `Документ #${s.documentId}`}
                {s.department.trim() && <span className="text-zinc-500"> · {s.department}</span>}
              </span>
              <span className="mt-0.5 block text-xs text-amber-400">{s.error}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function OverlapsView({ onError, onSuccess }: Props) {
  const [docs, setDocs] = useState<HistoryDocumentSummary[]>([])
  const [docsTotal, setDocsTotal] = useState(0)
  const [docsLoading, setDocsLoading] = useState(true)
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set())
  const [running, setRunning] = useState(false)
  const [report, setReport] = useState<OverlapReport | null>(null)
  const [reportLoading, setReportLoading] = useState(true)

  // При открытии вкладки: список документов для выбора + последний сохранённый
  // отчёт (кэш последнего запуска). 404 (отчёта ещё не было) — норма, молчим.
  useEffect(() => {
    let cancelled = false
    api
      .listHistoryDocuments({ limit: DOCS_LIMIT })
      .then((res) => {
        if (cancelled) return
        setDocs(res.items)
        setDocsTotal(res.total)
      })
      .catch((e: unknown) => {
        if (!cancelled) onError(formatError(e, 'Не удалось загрузить список документов'))
      })
      .finally(() => {
        if (!cancelled) setDocsLoading(false)
      })
    api
      .getLatestOverlaps()
      .then((rep) => {
        if (!cancelled) setReport(rep)
      })
      .catch((e: unknown) => {
        if (!cancelled && !(e instanceof ApiError && e.status === 404)) {
          onError(formatError(e, 'Не удалось загрузить последний отчёт'))
        }
      })
      .finally(() => {
        if (!cancelled) setReportLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [onError])

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const selectAll = () => setSelected(new Set(docs.map((d) => d.id)))
  const clearAll = () => setSelected(new Set<number>())

  const handleRun = async () => {
    if (running || selected.size === 0) return
    setRunning(true)
    try {
      const rep = await api.runOverlaps([...selected])
      setReport(rep)
      onSuccess(
        rep.groups.length > 0
          ? `Готово — найдено групп пересечений: ${rep.groups.length}`
          : 'Готово — содержательных пересечений не найдено',
      )
    } catch (e) {
      onError(formatError(e, 'Не удалось найти пересечения'))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold text-zinc-100">
        Пересечения обязанностей{' '}
        <span className="ml-1 text-sm font-normal text-zinc-400">
          сравнение ДИ между подразделениями
        </span>
      </h2>

      {/* Выбор документов */}
      <section className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-zinc-200">
            Документы{' '}
            <span className="text-xs font-normal text-zinc-400">
              выбрано {selected.size} из {docs.length}
            </span>
          </h3>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={selectAll}
              disabled={docsLoading || docs.length === 0}
              className={historyBtnSmallCls}
            >
              Выбрать все
            </button>
            <button
              type="button"
              onClick={clearAll}
              disabled={selected.size === 0}
              className={historyBtnSmallCls}
            >
              Снять все
            </button>
          </div>
        </div>

        {docsLoading && (
          <div className="flex items-center gap-2 py-2 text-sm text-zinc-400">
            <Spinner /> Загрузка документов…
          </div>
        )}

        {!docsLoading && docs.length === 0 && (
          <p className="py-2 text-sm text-zinc-500">
            История пуста — сначала проверьте документы на вкладке «Проверка».
          </p>
        )}

        {docs.length > 0 && (
          <div className="max-h-72 divide-y divide-zinc-800 overflow-y-auto rounded-lg border border-zinc-800">
            {docs.map((d) => (
              <label
                key={d.id}
                className="flex cursor-pointer items-center gap-3 px-3 py-2 transition-colors hover:bg-zinc-900/60"
              >
                <input
                  type="checkbox"
                  checked={selected.has(d.id)}
                  onChange={() => toggle(d.id)}
                  className="h-4 w-4 shrink-0 cursor-pointer accent-sky-500"
                />
                <span
                  className="min-w-0 flex-1 truncate text-sm text-zinc-200"
                  title={displayName(d)}
                >
                  {displayName(d)}
                </span>
                <span
                  className="max-w-48 shrink-0 truncate text-xs text-zinc-500"
                  title={d.department}
                >
                  {d.department.trim() || '—'}
                </span>
              </label>
            ))}
          </div>
        )}

        {docsTotal > docs.length && (
          <p className="text-xs text-zinc-500">
            Показаны первые {docs.length} из {docsTotal} документов.
          </p>
        )}
      </section>

      {/* Запуск сравнения */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void handleRun()}
          disabled={running || docsLoading || selected.size === 0}
          title={
            !running && !docsLoading && selected.size === 0
              ? 'Выберите хотя бы один документ'
              : undefined
          }
          className={historyBtnPrimaryCls}
        >
          {running && <Spinner />}
          {running ? 'Сравниваю обязанности… (LLM)' : 'Найти пересечения'}
        </button>
        {running && (
          <span className="text-xs text-zinc-500">
            Длинная LLM-операция — может занять от нескольких секунд до минуты. Не закрывайте
            страницу.
          </span>
        )}
      </div>

      {/* Загрузка сохранённого отчёта */}
      {reportLoading && (
        <div className="flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-6 text-sm text-zinc-400">
          <Spinner /> Загрузка последнего отчёта…
        </div>
      )}

      {/* Отчёт */}
      {report && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-zinc-200">
              Отчёт от {formatDateTime(report.createdAt)}
            </h3>
            <span className="text-xs text-zinc-500">
              документов: {report.documents.length} · групп пересечений: {report.groups.length}
            </span>
          </div>

          {report.skipped.length > 0 && (
            <div className="rounded-xl border border-amber-500/50 bg-amber-950/60 px-4 py-3 text-sm text-amber-200">
              {skippedLabel(report.skipped.length)} — их обязанности не вошли в сравнение.
            </div>
          )}

          {report.groups.length === 0 ? (
            <div className="rounded-xl border border-emerald-500/50 bg-emerald-950/60 px-4 py-3 text-sm text-emerald-200">
              Содержательных пересечений между подразделениями не найдено.
            </div>
          ) : (
            report.groups.map((g, i) => <GroupCard key={i} group={g} />)
          )}

          {report.skipped.length > 0 && <SkippedList skipped={report.skipped} />}
        </section>
      )}
    </div>
  )
}
