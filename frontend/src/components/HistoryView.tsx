import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  api,
  formatError,
  type HistoryDocumentSummary,
  type HistoryTemplateInfo,
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

/** Размер шаблона для строки статуса. */
function formatSizeKb(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  return `${(bytes / 1024).toFixed(1)} КБ`
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
  // Шаблон выгрузки: статус (null = ещё не загружен), панель, файл на загрузку
  const [tpl, setTpl] = useState<HistoryTemplateInfo | null>(null)
  const [tplOpen, setTplOpen] = useState(false)
  const [tplLoading, setTplLoading] = useState(false)
  const [tplUploading, setTplUploading] = useState(false)
  const [tplDeleting, setTplDeleting] = useState(false)
  const [tplFile, setTplFile] = useState<File | null>(null)
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

  const loadTemplate = useCallback(async () => {
    setTplLoading(true)
    try {
      setTpl(await api.getTemplate())
    } catch (e) {
      onError(formatError(e, 'Не удалось получить статус шаблона выгрузки'))
    } finally {
      setTplLoading(false)
    }
  }, [onError])

  // Статус шаблона нужен сразу: от него зависят подпись и поведение кнопки выгрузки.
  useEffect(() => {
    void loadTemplate()
  }, [loadTemplate])

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
    const useTemplate = tpl?.exists === true
    try {
      const { blob, filename } = await api.exportHistoryFixed(undefined, { template: useTemplate })
      downloadBlob(blob, filename ?? 'ispravlennye_di.zip')
    } catch (e) {
      // Шаблон могли удалить параллельно (409 no_template) — повторяем без шаблона.
      if (useTemplate && e instanceof ApiError && e.status === 409) {
        try {
          const { blob, filename } = await api.exportHistoryFixed()
          downloadBlob(blob, filename ?? 'ispravlennye_di.zip')
          setTpl({ exists: false })
          onSuccess('Шаблон не найден — выполнена обычная выгрузка без шаблона')
        } catch (e2) {
          onError(formatError(e2, 'Не удалось выгрузить исправленные документы'))
        }
      } else {
        onError(formatError(e, 'Не удалось выгрузить исправленные документы'))
      }
    } finally {
      setExporting(false)
    }
  }

  const handleUploadTemplate = async () => {
    if (!tplFile || tplUploading) return
    if (!tplFile.name.toLowerCase().endsWith('.docx')) {
      onError('Шаблон должен быть файлом .docx')
      return
    }
    setTplUploading(true)
    try {
      const res = await api.uploadTemplate(tplFile)
      setTpl({ exists: true, size: res.size, keys: res.keys })
      setTplFile(null)
      const keys = res.keys.length > 0 ? res.keys.join(', ') : 'не найдено'
      if (!res.keys.includes('ТЕКСТ')) {
        onError(
          `Шаблон загружен, но ключа ТЕКСТ в нём нет — без {{ТЕКСТ}} содержимое ДИ не вставится. Найденные ключи: ${keys}`,
        )
      } else {
        onSuccess(`Шаблон загружен. Найденные ключи: ${keys}`)
      }
    } catch (e) {
      onError(formatError(e, 'Не удалось загрузить шаблон'))
    } finally {
      setTplUploading(false)
    }
  }

  const handleDeleteTemplate = async () => {
    if (!window.confirm('Удалить шаблон выгрузки? Исправленные ДИ будут выгружаться как есть.'))
      return
    setTplDeleting(true)
    try {
      await api.deleteTemplate()
      setTpl({ exists: false })
      onSuccess('Шаблон выгрузки удалён')
    } catch (e) {
      onError(formatError(e, 'Не удалось удалить шаблон'))
    } finally {
      setTplDeleting(false)
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
            onClick={() => setTplOpen((v) => !v)}
            aria-expanded={tplOpen}
            className={historyBtnCls}
          >
            Шаблон выгрузки…
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
            {exporting
              ? 'Формируется архив…'
              : tpl?.exists
                ? 'Выгрузить исправленные (ZIP, по шаблону)'
                : 'Выгрузить исправленные (ZIP)'}
          </button>
        </div>
      </div>

      {/* Панель шаблона выгрузки */}
      {tplOpen && (
        <div className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-zinc-200">Шаблон выгрузки</h3>
            <button
              type="button"
              onClick={() => setTplOpen(false)}
              aria-label="Закрыть панель шаблона"
              className="cursor-pointer text-zinc-500 transition-colors hover:text-zinc-200"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              >
                <path d="M3 3l10 10M13 3L3 13" />
              </svg>
            </button>
          </div>

          {tplLoading ? (
            <div className="flex items-center gap-2 text-sm text-zinc-400">
              <Spinner /> Загрузка статуса шаблона…
            </div>
          ) : tpl?.exists ? (
            <div className="flex flex-wrap items-center gap-2 text-sm text-zinc-300">
              <span>Шаблон задан ({formatSizeKb(tpl.size ?? 0)})</span>
              {(tpl.keys ?? []).map((k) => (
                <span
                  key={k}
                  className="rounded-full border border-sky-500/40 bg-sky-500/10 px-2.5 py-0.5 text-xs font-medium text-sky-400"
                >
                  {k}
                </span>
              ))}
              {!(tpl.keys ?? []).includes('ТЕКСТ') && (
                <span className="text-xs text-amber-400">
                  Нет ключа ТЕКСТ — содержимое ДИ не вставится в выгрузку
                </span>
              )}
            </div>
          ) : (
            <p className="text-sm text-zinc-500">
              Шаблон не задан — исправленные ДИ выгружаются как есть.
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <input
              type="file"
              accept=".docx"
              aria-label="Файл шаблона (.docx)"
              onChange={(e) => {
                setTplFile(e.target.files?.[0] ?? null)
                e.target.value = ''
              }}
              className="text-sm text-zinc-400 file:mr-3 file:cursor-pointer file:rounded-lg file:border file:border-zinc-600 file:bg-zinc-800 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-zinc-100 file:transition-colors hover:file:bg-zinc-700"
            />
            <button
              type="button"
              onClick={() => void handleUploadTemplate()}
              disabled={!tplFile || tplUploading || tplDeleting}
              title={!tplFile ? 'Сначала выберите файл .docx' : undefined}
              className={historyBtnPrimaryCls}
            >
              {tplUploading && <Spinner />}
              {tplUploading ? 'Загружается…' : 'Загрузить'}
            </button>
            {tpl?.exists && (
              <button
                type="button"
                onClick={() => void handleDeleteTemplate()}
                disabled={tplDeleting || tplUploading}
                className={historyBtnCls}
              >
                {tplDeleting && <Spinner />}
                {tplDeleting ? 'Удаляется…' : 'Удалить шаблон'}
              </button>
            )}
          </div>

          <p className="text-xs text-zinc-500">
            Доступные ключи подстановки: {'{{ДОЛЖНОСТЬ}}'}, {'{{ПОДРАЗДЕЛЕНИЕ}}'},{' '}
            {'{{НАЗВАНИЕ}}'}, {'{{ТЕКСТ}}'} (содержимое исправленного ДИ), {'{{ДАТА}}'},{' '}
            {'{{ЗАМЕТКИ}}'}.
          </p>
        </div>
      )}

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
