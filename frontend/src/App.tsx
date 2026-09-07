import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, formatError, type Job, type Settings, type UpdateInfo } from './api'
import SettingsPanel from './components/SettingsPanel'
import CheckPanel, { type CheckContext } from './components/CheckPanel'
import Results from './components/Results'
import HistoryView from './components/HistoryView'
import OverlapsView from './components/OverlapsView'
import Toast, { type ToastData } from './components/Toast'

const JOB_ID_KEY = 'di_check_job_id'

type View = 'check' | 'history' | 'overlaps'

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

export default function App() {
  const [view, setView] = useState<View>('check')
  const [settings, setSettings] = useState<Settings | null>(null)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [toast, setToast] = useState<ToastData | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [starting, setStarting] = useState(false)
  const [noApiKey, setNoApiKey] = useState(false)
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null)
  const [installingUpdate, setInstallingUpdate] = useState(false)
  const [pollingStopped, setPollingStopped] = useState(false)
  const pollRef = useRef<number | null>(null)
  const pollFailuresRef = useRef(0)
  // Поколение поллинга: не даёт устаревшему in-flight ответу перезаписать новую джобу.
  const pollGenRef = useRef(0)

  useEffect(() => {
    api
      .getSettings()
      .then(setSettings)
      .catch((e: unknown) =>
        setSettingsError(e instanceof Error ? e.message : 'Не удалось загрузить настройки'),
      )
    // тихая автопроверка обновлений: результат виден в настройках
    api
      .checkUpdate()
      .then((info) => {
        if (!info.error && info.updateAvailable) setUpdateInfo(info)
      })
      .catch(() => {})
  }, [])

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => stopPolling, [stopPolling])

  const showError = useCallback((msg: string) => setToast({ type: 'error', text: msg }), [])
  const showSuccess = useCallback((msg: string) => setToast({ type: 'success', text: msg }), [])

  // Поллинг статуса джобы: одиночные сбои сети переживаем молча,
  // останавливаемся после 3 неудач подряд — тогда показываем баннер с «Возобновить».
  // Каждый запрос фиксирует своё поколение: если поллинг перезапущен (новая джоба
  // или возобновление), ответ устаревшего запроса отбрасывается, а не перезаписывает
  // актуальное состояние.
  const startPolling = useCallback(
    async (jobId: string) => {
      stopPolling()
      pollGenRef.current += 1
      const gen = pollGenRef.current
      pollFailuresRef.current = 0
      setPollingStopped(false)
      const poll = async (): Promise<boolean> => {
        const reqGen = pollGenRef.current
        try {
          const j = await api.getJob(jobId)
          if (pollGenRef.current !== reqGen || j.id !== jobId) return false
          pollFailuresRef.current = 0
          setJob(j)
          return j.status === 'running'
        } catch (e) {
          if (pollGenRef.current !== reqGen) return false
          pollFailuresRef.current += 1
          if (pollFailuresRef.current >= 3) {
            stopPolling()
            setPollingStopped(true)
            showError(formatError(e, 'Ошибка получения статуса проверки'))
            return false
          }
          return true
        }
      }
      const keepGoing = await poll()
      if (keepGoing && pollGenRef.current === gen) {
        pollRef.current = window.setInterval(() => void poll(), 1500)
      }
    },
    [showError, stopPolling],
  )

  // Восстановление джобы после перезагрузки страницы.
  // Если джоба не найдена (например, истекла после перезапуска сервера) —
  // тихо удаляем ключ, без показа ошибки пользователю.
  useEffect(() => {
    const saved = localStorage.getItem(JOB_ID_KEY)
    if (!saved) return
    let cancelled = false
    api
      .getJob(saved)
      .then((j) => {
        if (cancelled) return
        setJob(j)
        if (j.status === 'running') void startPolling(saved)
      })
      .catch(() => {
        if (!cancelled) localStorage.removeItem(JOB_ID_KEY)
      })
    return () => {
      cancelled = true
    }
  }, [startPolling])

  const activeProvider = settings?.providers.find((p) => p.id === settings.activeProvider)

  const startCheck = useCallback(
    async (files: File[], ctx: CheckContext) => {
      setStarting(true)
      setNoApiKey(false)
      setPollingStopped(false)
      stopPolling()
      try {
        const form = new FormData()
        files.forEach((f) => form.append('files', f))
        if (ctx.contractSubject.trim()) form.append('contractSubject', ctx.contractSubject.trim())
        if (ctx.employmentType) form.append('employmentType', ctx.employmentType)
        if (ctx.extraContext.trim()) form.append('extraContext', ctx.extraContext.trim())

        const { jobId } = await api.startCheck(form)
        localStorage.setItem(JOB_ID_KEY, jobId)
        await startPolling(jobId)
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && e.detail === 'no_api_key') {
          setNoApiKey(true)
        } else {
          showError(formatError(e, 'Не удалось запустить проверку'))
        }
      } finally {
        setStarting(false)
      }
    },
    [showError, startPolling, stopPolling],
  )

  // Установка обновления из баннера в шапке
  const runUpdateInstall = async () => {
    setInstallingUpdate(true)
    try {
      const res = await api.installUpdate()
      setUpdateInfo(null)
      setToast({
        type: 'success',
        text: `Установка версии ${res.version} запущена: приложение закроется и перезапустится автоматически.`,
      })
    } catch (e) {
      setToast({ type: 'error', text: formatError(e, 'Не удалось запустить обновление') })
    } finally {
      setInstallingUpdate(false)
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-4">
      {/* Шапка */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 py-4">
        <h1 className="text-lg font-bold text-zinc-50">Проверка должностных инструкций</h1>
        <div className="flex items-center gap-3">
          {/* Переключатель разделов: Проверка / История / Пересечения */}
          <div
            role="tablist"
            aria-label="Разделы"
            className="flex items-center gap-1 rounded-lg border border-zinc-700 bg-zinc-900 p-1"
          >
            {(
              [
                ['check', 'Проверка'],
                ['history', 'История'],
                ['overlaps', 'Пересечения'],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={view === key}
                onClick={() => setView(key)}
                className={`cursor-pointer rounded-md px-3 py-1 text-sm font-medium transition-colors ${
                  view === key
                    ? 'bg-sky-600 text-white'
                    : 'text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {settings && (
            <span className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-300">
              {activeProvider?.name ?? settings.activeProvider}
              <span className="mx-1.5 text-zinc-600">·</span>
              <span className="text-sky-400">{settings.activeModel || 'модель не выбрана'}</span>
            </span>
          )}
          <button
            type="button"
            onClick={() => setSettingsOpen((v) => !v)}
            className="cursor-pointer rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-sm font-medium text-zinc-100 transition-colors hover:bg-zinc-700"
          >
            {settingsOpen ? 'Скрыть настройки' : 'Настройки'}
          </button>
        </div>
      </header>

      {/* Баннер: доступно обновление */}
      {updateInfo?.updateAvailable && updateInfo.latest && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-sky-500/50 bg-sky-950/60 px-4 py-3">
          <span className="flex-1 text-sm text-sky-200">
            Доступна новая версия {updateInfo.latest} (у вас {updateInfo.current}).
          </span>
          <button
            type="button"
            onClick={() => void runUpdateInstall()}
            disabled={installingUpdate}
            className="flex cursor-pointer items-center gap-2 rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {installingUpdate && <Spinner />}
            {installingUpdate ? 'Установка…' : 'Обновить'}
          </button>
        </div>
      )}

      {/* Баннер: нет API-ключа */}
      {noApiKey && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-amber-500/50 bg-amber-950/60 px-4 py-3">
          <span className="flex-1 text-sm text-amber-200">
            У активного провайдера не сохранён API-ключ. Сохраните ключ в настройках и повторите
            проверку.
          </span>
          <button
            type="button"
            onClick={() => {
              setSettingsOpen(true)
              setNoApiKey(false)
            }}
            className="cursor-pointer rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-amber-500"
          >
            Открыть настройки
          </button>
        </div>
      )}

      {/* Ошибка загрузки настроек */}
      {settingsError && (
        <div className="mt-4 rounded-xl border border-red-500/50 bg-red-950/60 px-4 py-3 text-sm text-red-200">
          Не удалось подключиться к серверу: {settingsError}. Убедитесь, что бэкенд запущен на
          127.0.0.1:8787.
        </div>
      )}

      <div className="flex flex-1 flex-col gap-6 py-6 lg:flex-row">
        {/* Настройки */}
        {settingsOpen && settings && (
          <aside className="w-full shrink-0 rounded-xl border border-zinc-800 bg-zinc-900/30 lg:w-96">
            <h2 className="border-b border-zinc-800 px-4 py-3 text-sm font-semibold text-zinc-200">
              Настройки
            </h2>
            <SettingsPanel
              settings={settings}
              onUpdated={setSettings}
              onError={showError}
              autoUpdateInfo={updateInfo}
            />
          </aside>
        )}

        {/* Основная зона */}
        <main className="min-w-0 flex-1 space-y-6">
          {view === 'history' ? (
            <HistoryView onError={showError} onSuccess={showSuccess} />
          ) : view === 'overlaps' ? (
            <OverlapsView onError={showError} onSuccess={showSuccess} />
          ) : (
            <>
              <CheckPanel
                starting={starting}
                checking={job?.status === 'running'}
                onStart={(files, ctx) => void startCheck(files, ctx)}
                onRejected={(message) => setToast({ type: 'error', text: message })}
              />
              {/* Баннер: поллинг остановлен после сетевых сбоев */}
              {job && pollingStopped && job.status === 'running' && (
                <div className="flex flex-wrap items-center gap-3 rounded-xl border border-amber-500/50 bg-amber-950/60 px-4 py-3">
                  <span className="flex-1 text-sm text-amber-200">
                    Связь с сервером потеряна — статус проверки не обновляется. Возобновите
                    наблюдение, чтобы получить результат.
                  </span>
                  <button
                    type="button"
                    onClick={() => void startPolling(job.id)}
                    className="cursor-pointer rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-amber-500"
                  >
                    Возобновить
                  </button>
                </div>
              )}
              {job && <Results key={job.id} job={job} onError={showError} />}
            </>
          )}
        </main>
      </div>

      <footer className="border-t border-zinc-800 py-3 text-center text-xs text-zinc-600">
        DI_Check — локальная проверка ДИ через LLM
      </footer>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  )
}
