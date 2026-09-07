import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  api,
  formatError,
  type HistoryDocument,
  type HistoryDocumentVersion,
  type HistoryFinding,
  type HistoryVersionDetail,
} from '../api'
import {
  FixMethodBadge,
  OriginBadge,
  Spinner,
  VerdictBadge,
  downloadBlob,
  formatDateTime,
  historyBtnCls,
  historyBtnPrimaryCls,
  historyBtnSmallCls,
  historyInputCls,
} from './HistoryShared'

interface Props {
  docId: number
  onBack: () => void
  /** Данные документа изменились (сохранение/автозаполнение) — обновить список. */
  onChanged: () => void
  onError: (msg: string) => void
  onSuccess: (msg: string) => void
}

/** Карточка одного замечания — в стиле списка правок из Results. */
function FindingCard({ finding }: { finding: HistoryFinding }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <span className="block text-sm font-medium text-zinc-100">{finding.title}</span>
      {finding.reason && <span className="mt-1 block text-xs text-zinc-400">{finding.reason}</span>}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-medium tracking-wide text-zinc-500 uppercase">Было</div>
          <blockquote className="rounded-lg border-l-2 border-red-500/50 bg-zinc-950/60 px-3 py-2 text-xs whitespace-pre-wrap text-zinc-300">
            {finding.original}
          </blockquote>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium tracking-wide text-zinc-500 uppercase">
            Будет
          </div>
          <blockquote className="rounded-lg border-l-2 border-emerald-500/50 bg-zinc-950/60 px-3 py-2 text-xs whitespace-pre-wrap text-zinc-200">
            {finding.replacement}
          </blockquote>
        </div>
      </div>
    </div>
  )
}

/** Свёрнутый блок с текстом версии ДИ. */
function VersionText({ detail }: { detail: HistoryVersionDetail }) {
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
        {open ? 'Скрыть текст документа' : 'Показать текст документа'}
      </button>
      {open && (
        <div className="mt-2">
          {detail.textTruncated && (
            <p className="mb-2 text-xs text-zinc-500">
              Текст сохранён не полностью — при проверке он был обрезан лимитом ~120 000 символов.
            </p>
          )}
          <div className="max-h-96 overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-xs whitespace-pre-wrap text-zinc-300">
            {detail.text}
          </div>
        </div>
      )}
    </div>
  )
}

/** Развёрнутое содержимое check-версии: замечания + отчёт. */
function CheckVersionBody({
  detail,
  loading,
}: {
  detail: HistoryVersionDetail | undefined
  loading: boolean
}) {
  const [reportOpen, setReportOpen] = useState(false)

  if (loading || !detail) {
    return (
      <div className="flex items-center gap-2 py-2 text-sm text-zinc-400">
        <Spinner /> Загрузка версии…
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <h5 className="mb-2 text-sm font-semibold text-zinc-200">
          Замечания{' '}
          <span className="text-xs font-normal text-zinc-500">({detail.findings.length})</span>
        </h5>
        {detail.findings.length > 0 ? (
          <div className="space-y-3">
            {detail.findings.map((f) => (
              <FindingCard key={f.editId} finding={f} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-zinc-500">Замечаний не найдено.</p>
        )}
      </div>

      {detail.report && (
        <div>
          <button
            type="button"
            onClick={() => setReportOpen((v) => !v)}
            aria-expanded={reportOpen}
            className={historyBtnSmallCls}
          >
            {reportOpen ? 'Скрыть отчёт' : 'Показать отчёт'}
          </button>
          {reportOpen && (
            <article className="md-report mt-3 overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.report}</ReactMarkdown>
            </article>
          )}
        </div>
      )}

      <VersionText detail={detail} />
    </div>
  )
}

/** Развёрнутое содержимое fix-версии: применённые замечания + текст. */
function FixVersionBody({
  version,
  detail,
  parent,
  loading,
  parentLoading,
}: {
  version: HistoryDocumentVersion
  detail: HistoryVersionDetail | undefined
  parent: HistoryVersionDetail | undefined
  loading: boolean
  parentLoading: boolean
}) {
  if (loading || !detail) {
    return (
      <div className="flex items-center gap-2 py-2 text-sm text-zinc-400">
        <Spinner /> Загрузка версии…
      </div>
    )
  }

  if (version.parentVersionId !== null && !parent) {
    return (
      <div className="space-y-4">
        {parentLoading ? (
          <div className="flex items-center gap-2 py-2 text-sm text-zinc-400">
            <Spinner /> Загрузка исходной версии…
          </div>
        ) : (
          <p className="text-sm text-zinc-500">
            Исходная версия недоступна — список применённых замечаний не удалось восстановить
            (применено замечаний: {version.appliedEditIds.length}).
          </p>
        )}
        <VersionText detail={detail} />
      </div>
    )
  }

  const applied: HistoryFinding[] =
    version.parentVersionId !== null && parent
      ? version.appliedEditIds
          .map((editId) => parent.findings.find((f) => f.editId === editId))
          .filter((f): f is HistoryFinding => Boolean(f))
      : []
  const unmatched =
    version.parentVersionId !== null && parent
      ? version.appliedEditIds.length - applied.length
      : 0

  return (
    <div className="space-y-4">
      <div>
        <h5 className="mb-2 text-sm font-semibold text-zinc-200">
          Исправлено замечаний{' '}
          <span className="text-xs font-normal text-zinc-500">({applied.length})</span>
        </h5>
        {applied.length > 0 ? (
          <div className="space-y-3">
            {applied.map((f) => (
              <FindingCard key={f.editId} finding={f} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-zinc-500">
            {detail.findings.length > 0
              ? 'Список применённых замечаний доступен в исходной версии.'
              : 'Нет данных о применённых замечаниях.'}
          </p>
        )}
        {unmatched > 0 && (
          <p className="mt-2 text-xs text-zinc-500">
            Ещё {unmatched} правок не удалось сопоставить с замечаниями исходной версии.
          </p>
        )}
      </div>

      <VersionText detail={detail} />
    </div>
  )
}

export default function HistoryDocumentCard({
  docId,
  onBack,
  onChanged,
  onError,
  onSuccess,
}: Props) {
  const [doc, setDoc] = useState<HistoryDocument | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)

  // Черновик редактируемых метаданных
  const [position, setPosition] = useState('')
  const [department, setDepartment] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [autoFilling, setAutoFilling] = useState(false)

  // Аккордеон версий: раскрытые id, кэш деталей, идущие загрузки
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set())
  const [details, setDetails] = useState<Record<number, HistoryVersionDetail>>({})
  const [loadingVersions, setLoadingVersions] = useState<ReadonlySet<number>>(new Set())
  const [downloading, setDownloading] = useState<ReadonlySet<number>>(new Set())
  // Ref-копии для защиты от двойного запроса до применения state (быстрые клики).
  const detailsRef = useRef<Record<number, HistoryVersionDetail>>({})
  const inflightRef = useRef<Set<number>>(new Set())

  const resetVersionState = () => {
    setExpanded(new Set())
    setDetails({})
    detailsRef.current = {}
    inflightRef.current = new Set()
    setLoadingVersions(new Set())
    setDownloading(new Set())
  }

  // Колбэки из App стабильны (useCallback) — эффект перезапускаем только при смене документа.
  useEffect(() => {
    let cancelled = false
    setDoc(null)
    setLoadFailed(false)
    resetVersionState()
    setPosition('')
    setDepartment('')
    setNotes('')
    api
      .getHistoryDocument(docId)
      .then((d) => {
        if (cancelled) return
        setDoc(d)
        setPosition(d.position)
        setDepartment(d.department)
        setNotes(d.notes)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setLoadFailed(true)
        onError(formatError(e, 'Не удалось загрузить документ'))
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId])

  const ensureVersion = async (id: number) => {
    if (detailsRef.current[id] || inflightRef.current.has(id)) return
    inflightRef.current.add(id)
    setLoadingVersions((prev) => new Set(prev).add(id))
    try {
      const d = await api.getHistoryVersion(id)
      detailsRef.current[id] = d
      setDetails((prev) => ({ ...prev, [id]: d }))
    } catch (e) {
      onError(formatError(e, 'Не удалось загрузить версию'))
    } finally {
      inflightRef.current.delete(id)
      setLoadingVersions((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }

  const toggleVersion = (v: HistoryDocumentVersion) => {
    if (expanded.has(v.id)) {
      setExpanded((prev) => {
        const next = new Set(prev)
        next.delete(v.id)
        return next
      })
      return
    }
    setExpanded((prev) => new Set(prev).add(v.id))
    void ensureVersion(v.id)
    // Для fix-версии подтягиваем родительскую check-версию — из её findings
    // восстанавливается список применённых замечаний.
    if (v.origin === 'fix' && v.parentVersionId !== null) void ensureVersion(v.parentVersionId)
  }

  const handleSave = async () => {
    if (!doc) return
    setSaving(true)
    try {
      await api.patchHistoryDocument(doc.id, {
        position: position.trim(),
        department: department.trim(),
        notes,
      })
      setDoc((prev) =>
        prev ? { ...prev, position: position.trim(), department: department.trim(), notes } : prev,
      )
      onSuccess('Метаданные сохранены')
      onChanged()
    } catch (e) {
      onError(formatError(e, 'Не удалось сохранить метаданные'))
    } finally {
      setSaving(false)
    }
  }

  const handleAutoFill = async () => {
    if (!doc) return
    setAutoFilling(true)
    try {
      const res = await api.extractHistoryDocumentMeta(doc.id)
      setPosition(res.position)
      setDepartment(res.department)
      onSuccess('Должность и подразделение определены автоматически')
      onChanged()
    } catch (e) {
      onError(formatError(e, 'Не удалось определить метаданные автоматически'))
    } finally {
      setAutoFilling(false)
    }
  }

  const handleDownload = async (v: HistoryDocumentVersion) => {
    setDownloading((prev) => new Set(prev).add(v.id))
    try {
      const { blob, filename } = await api.downloadHistoryVersion(v.id)
      downloadBlob(blob, filename ?? v.filename)
    } catch (e) {
      onError(formatError(e, 'Не удалось скачать файл версии'))
    } finally {
      setDownloading((prev) => {
        const next = new Set(prev)
        next.delete(v.id)
        return next
      })
    }
  }

  const heading = doc ? doc.position.trim() || doc.title : ''

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" onClick={onBack} className={historyBtnCls}>
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="10 3 5 8 10 13" />
          </svg>
          Назад к списку
        </button>
        {doc && (
          <span className="text-xs text-zinc-500">
            Версий: {doc.versions.length} · Обновлено {formatDateTime(doc.updatedAt)}
          </span>
        )}
      </div>

      {!doc && !loadFailed && (
        <div className="flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-6 text-sm text-zinc-400">
          <Spinner /> Загрузка документа…
        </div>
      )}

      {!doc && loadFailed && (
        <div className="rounded-xl border border-red-500/50 bg-red-950/60 px-4 py-3 text-sm text-red-200">
          Документ недоступен. Возможно, он был удалён или сервер был перезапущен.
        </div>
      )}

      {doc && (
        <>
          {/* Шапка документа */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
            <h2 className="text-base font-semibold text-zinc-50">{heading}</h2>
            {doc.department.trim() && <p className="mt-0.5 text-sm text-zinc-400">{doc.department}</p>}
            <p className="mt-1 text-xs text-zinc-500">
              {doc.title !== heading && <span className="mr-3">{doc.title}</span>}
              Создано {formatDateTime(doc.createdAt)}
            </p>
          </div>

          {/* Метаданные: редактирование + автозаполнение */}
          <div className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
            <h3 className="text-sm font-semibold text-zinc-200">Метаданные</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="hd-position" className="mb-1 block text-xs text-zinc-400">
                  Должность
                </label>
                <input
                  id="hd-position"
                  value={position}
                  onChange={(e) => setPosition(e.target.value)}
                  className={historyInputCls}
                />
              </div>
              <div>
                <label htmlFor="hd-department" className="mb-1 block text-xs text-zinc-400">
                  Подразделение
                </label>
                <input
                  id="hd-department"
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  className={historyInputCls}
                />
              </div>
            </div>
            <div>
              <label htmlFor="hd-notes" className="mb-1 block text-xs text-zinc-400">
                Заметки
              </label>
              <textarea
                id="hd-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                placeholder="Свободные пометки по документу…"
                className={`${historyInputCls} resize-y`}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={saving || autoFilling}
                className={historyBtnPrimaryCls}
              >
                {saving && <Spinner />}
                {saving ? 'Сохраняется…' : 'Сохранить'}
              </button>
              <button
                type="button"
                onClick={() => void handleAutoFill()}
                disabled={saving || autoFilling}
                title="Определить должность и подразделение из текста ДИ с помощью LLM"
                className={historyBtnCls}
              >
                {autoFilling && <Spinner />}
                {autoFilling ? 'Определяется…' : 'Определить автоматически'}
              </button>
            </div>
          </div>

          {/* Версии */}
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-zinc-200">Версии документа</h3>
            {doc.versions.length === 0 && (
              <p className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-3 text-sm text-zinc-500">
                У документа пока нет сохранённых версий.
              </p>
            )}
            {doc.versions.map((v) => {
              const isOpen = expanded.has(v.id)
              const detail = details[v.id]
              const parent = v.parentVersionId !== null ? details[v.parentVersionId] : undefined
              const parentLoading =
                v.parentVersionId !== null && loadingVersions.has(v.parentVersionId)
              return (
                <div key={v.id} className="rounded-xl border border-zinc-800 bg-zinc-900/40">
                  <div className="flex flex-wrap items-center gap-3 p-3">
                    <button
                      type="button"
                      onClick={() => toggleVersion(v)}
                      aria-expanded={isOpen}
                      className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 text-left"
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
                        className={`shrink-0 text-zinc-500 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                      >
                        <polyline points="4 6 8 10 12 6" />
                      </svg>
                      <OriginBadge origin={v.origin} />
                      <span className="min-w-0 flex-1 truncate text-sm text-zinc-200" title={v.filename}>
                        {v.filename}
                      </span>
                      <span className="shrink-0 text-xs text-zinc-500">
                        {formatDateTime(v.createdAt)}
                      </span>
                      {v.origin === 'check' && <VerdictBadge verdict={v.verdict} />}
                      {v.origin === 'fix' && <FixMethodBadge method={v.fixMethod} />}
                      <span className="shrink-0 text-xs text-zinc-400">
                        {v.origin === 'check'
                          ? `замечаний: ${v.findingsCount}`
                          : `исправлено замечаний: ${v.appliedEditIds.length}`}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDownload(v)}
                      disabled={downloading.has(v.id)}
                      className={historyBtnSmallCls}
                    >
                      {downloading.has(v.id) ? <Spinner /> : 'Скачать'}
                    </button>
                  </div>
                  {isOpen && (
                    <div className="border-t border-zinc-800 p-4">
                      {v.origin === 'check' ? (
                        <CheckVersionBody
                          detail={detail}
                          loading={loadingVersions.has(v.id)}
                        />
                      ) : (
                        <FixVersionBody
                          version={v}
                          detail={detail}
                          parent={parent}
                          loading={loadingVersions.has(v.id)}
                          parentLoading={parentLoading}
                        />
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
