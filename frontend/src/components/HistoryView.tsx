import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  formatError,
  type HistoryDocumentSummary,
} from '../api'
import {
  Spinner,
  VerdictBadge,
  downloadBlob,
  formatDateTime,
  historyBtnCls,
  historyBtnPrimaryCls,
  historyBtnSmallCls,
  historyInputCls,
} from './HistoryShared'
import HistoryDocumentCard from './HistoryDocumentCard'

const PAGE_SIZE = 50
const SEARCH_DEBOUNCE_MS = 300

interface Props {
  onError: (msg: string) => void
  onSuccess: (msg: string) => void
}

/** Отображаемое имя документа: должность, а если не заполнена — title. */
function displayName(d: HistoryDocumentSummary): string {
  return d.position.trim() || d.title
}

export default function HistoryView({ onError, onSuccess }: Props) {
  const [items, setItems] = useState<HistoryDocumentSummary[]>([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  // Поиск после дебаунса: перезагружает список
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [reloadTick, setReloadTick] = useState(0)
  const [openDocId, setOpenDocId] = useState<number | null>(null)
  const [bulkFilling, setBulkFilling] = useState(false)
  const [exporting, setExporting] = useState(false)
  // Занятые строки (скачивание/удаление), чтобы дублировать клики
  const [busyRows, setBusyRows] = useState<ReadonlySet<number>>(new Set())

  // Актуальная длина списка для offset «Показать ещё» (без пересоздания load).
  const itemsCountRef = useRef(0)
  itemsCountRef.current = items.length
  // Поколение запроса: устаревший in-flight ответ (после смены поиска) отбрасывается.
  const reqGenRef = useRef(0)

  // Дебаунс поисковой строки — 300 мс.
  useEffect(() => {
    const t = window.setTimeout(() => setQuery(search.trim()), SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(t)
  }, [search])

  const load = useCallback(
    async (replace: boolean) => {
      const gen = ++reqGenRef.current
      if (replace) setLoading(true)
      else setLoadingMore(true)
      try {
        const offset = replace ? 0 : itemsCountRef.current
        const res = await api.listHistoryDocuments({
          search: query || undefined,
          limit: PAGE_SIZE,
          offset,
        })
        if (reqGenRef.current !== gen) return
        setTotal(res.total)
        setItems((prev) => (replace ? res.items : [...prev, ...res.items]))
      } catch (e) {
        if (reqGenRef.current !== gen) return
        onError(formatError(e, 'Не удалось загрузить историю'))
      } finally {
        if (reqGenRef.current === gen) {
          setLoading(false)
          setLoadingMore(false)
        }
      }
    },
    [query, onError],
  )

  // Первичная загрузка, смена поиска и ручное обновление.
  useEffect(() => {
    void load(true)
  }, [load, reloadTick])

  const refresh = () => setReloadTick((t) => t + 1)

  const markBusy = (id: number, busy: boolean) =>
    setBusyRows((prev) => {
      const next = new Set(prev)
      if (busy) next.add(id)
      else next.delete(id)
      return next
    })

  const handleDownloadFixed = async (d: HistoryDocumentSummary) => {
    markBusy(d.id, true)
    try {
      const { blob, filename } = await api.exportHistoryFixed([d.id])
      downloadBlob(blob, filename ?? `${displayName(d)}.zip`)
    } catch (e) {
      onError(formatError(e, 'Не удалось скачать исправленный документ'))
    } finally {
      markBusy(d.id, false)
    }
  }

  const handleDelete = async (d: HistoryDocumentSummary) => {
    const name = displayName(d)
    if (!window.confirm(`Удалить «${name}» из истории вместе со всеми версиями?`)) return
    markBusy(d.id, true)
    try {
      await api.deleteHistoryDocument(d.id)
      setItems((prev) => prev.filter((x) => x.id !== d.id))
      setTotal((t) => Math.max(0, t - 1))
      onSuccess(`Документ «${name}» удалён из истории`)
    } catch (e) {
      onError(formatError(e, 'Не удалось удалить документ'))
    } finally {
      markBusy(d.id, false)
    }
  }

  const handleBulkFill = async () => {
    setBulkFilling(true)
    try {
      const res = await api.extractHistoryMetaBulk(null)
      const filled = res.results.filter((r) => !r.error && (r.position.trim() || r.department.trim()))
      const failed = res.results.filter((r) => r.error)
      const tail =
        failed.length > 0 && failed[0].error ? ` Первая ошибка: ${failed[0].error}` : ''
      onSuccess(`Заполнено ${filled.length}, ошибок ${failed.length}.${tail}`)
      refresh()
    } catch (e) {
      onError(formatError(e, 'Не удалось заполнить пропуски'))
    } finally {
      setBulkFilling(false)
    }
  }

  const handleExportFixed = async () => {
    setExporting(true)
    try {
      const { blob, filename } = await api.exportHistoryFixed()
      downloadBlob(blob, filename ?? 'ispravlennye_di.zip')
    } catch (e) {
      onError(formatError(e, 'Не удалось выгрузить исправленные документы'))
    } finally {
      setExporting(false)
    }
  }

  const fixedTotal = items.reduce((sum, d) => sum + d.fixedCount, 0)
  const hasMore = items.length < total

  if (openDocId !== null) {
    return (
      <HistoryDocumentCard
        docId={openDocId}
        onBack={() => setOpenDocId(null)}
        onChanged={refresh}
        onError={onError}
        onSuccess={onSuccess}
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-zinc-100">
          История проверок{' '}
          <span className="ml-1 text-sm font-normal text-zinc-400">документов: {total}</span>
        </h2>
      </div>

      {/* Панель действий */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Поиск по должности, подразделению, названию…"
          className={`${historyInputCls} min-w-56 max-w-sm flex-1`}
        />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button type="button" onClick={refresh} disabled={loading} className={historyBtnCls}>
            {loading && <Spinner />}
            Обновить
          </button>
          <button
            type="button"
            onClick={() => void handleBulkFill()}
            disabled={bulkFilling || loading}
            title="Определить должность и подразделение у всех документов с пустыми полями"
            className={historyBtnCls}
          >
            {bulkFilling && <Spinner />}
            {bulkFilling ? 'Заполняется…' : 'Заполнить пропуски (LLM)'}
          </button>
          <button
            type="button"
            onClick={() => void handleExportFixed()}
            disabled={exporting || fixedTotal === 0}
            title={
              fixedTotal === 0 ? 'Нет исправленных версий для выгрузки' : undefined
            }
            className={historyBtnPrimaryCls}
          >
            {exporting && <Spinner />}
            {exporting ? 'Формируется архив…' : 'Выгрузить исправленные (ZIP)'}
          </button>
        </div>
      </div>

      {/* Загрузка / пустые состояния */}
      {loading && items.length === 0 && (
        <div className="flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-6 text-sm text-zinc-400">
          <Spinner /> Загрузка истории…
        </div>
      )}

      {!loading && items.length === 0 && query && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-6 text-center text-sm text-zinc-400">
          По запросу «{query}» ничего не найдено.
        </div>
      )}

      {!loading && items.length === 0 && !query && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-10 text-center">
          <p className="text-sm text-zinc-300">История пуста — запустите первую проверку.</p>
          <p className="mt-1 text-xs text-zinc-500">
            Проверенные документы появятся здесь вместе со своими версиями.
          </p>
        </div>
      )}

      {/* Таблица документов */}
      {items.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-800 bg-zinc-900/80 text-xs text-zinc-400 uppercase">
                <th className="px-4 py-2.5 font-medium">Должность</th>
                <th className="px-4 py-2.5 font-medium">Подразделение</th>
                <th className="px-4 py-2.5 font-medium">Вердикт</th>
                <th className="px-4 py-2.5 font-medium">Замечаний</th>
                <th className="px-4 py-2.5 font-medium">Проверена</th>
                <th className="px-4 py-2.5 font-medium">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {items.map((d) => {
                const subName = d.position.trim() && d.title !== d.position.trim() ? d.title : null
                return (
                  <tr key={d.id} className="hover:bg-zinc-900/50">
                    <td className="max-w-56 px-4 py-2.5 text-zinc-200">
                      <span className="block truncate" title={displayName(d)}>
                        {displayName(d)}
                      </span>
                      {subName && (
                        <span className="block truncate text-xs text-zinc-500" title={subName}>
                          {subName}
                        </span>
                      )}
                    </td>
                    <td className="max-w-48 truncate px-4 py-2.5 text-zinc-300" title={d.department}>
                      {d.department.trim() || <span className="text-xs text-zinc-600">—</span>}
                    </td>
                    <td className="px-4 py-2.5">
                      <VerdictBadge verdict={d.lastCheck?.verdict ?? null} />
                    </td>
                    <td className="px-4 py-2.5 text-zinc-300">
                      {d.lastCheck ? (
                        d.lastCheck.findingsCount
                      ) : (
                        <span className="text-xs text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-zinc-300">
                      {d.lastCheck ? (
                        formatDateTime(d.lastCheck.checkedAt)
                      ) : (
                        <span className="text-xs text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setOpenDocId(d.id)}
                          className={historyBtnSmallCls}
                        >
                          Открыть
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDownloadFixed(d)}
                          disabled={d.fixedCount === 0 || busyRows.has(d.id)}
                          title={
                            d.fixedCount === 0 ? 'Нет исправленных версий' : undefined
                          }
                          className={historyBtnSmallCls}
                        >
                          {busyRows.has(d.id) ? <Spinner /> : 'Скачать исправл.'}
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDelete(d)}
                          disabled={busyRows.has(d.id)}
                          className="cursor-pointer rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-100 transition-colors hover:border-red-500/50 hover:bg-red-950/40 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          Удалить
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Пагинация */}
      {hasMore && (
        <div className="text-center">
          <button
            type="button"
            onClick={() => void load(false)}
            disabled={loadingMore || loading}
            className={historyBtnCls}
          >
            {loadingMore && <Spinner />}
            {loadingMore
              ? 'Загружается…'
              : `Показать ещё (осталось ${total - items.length})`}
          </button>
        </div>
      )}
    </div>
  )
}
