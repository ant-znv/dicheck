import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Job, type Settings } from './api'
import SettingsPanel from './components/SettingsPanel'
import CheckPanel, { type CheckContext } from './components/CheckPanel'
import Results from './components/Results'
import Toast, { type ToastData } from './components/Toast'

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [toast, setToast] = useState<ToastData | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [starting, setStarting] = useState(false)
  const [noApiKey, setNoApiKey] = useState(false)
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    api
      .getSettings()
      .then(setSettings)
      .catch((e: unknown) =>
        setSettingsError(e instanceof Error ? e.message : 'Не удалось загрузить настройки'),
      )
  }, [])

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => stopPolling, [stopPolling])

  const showError = useCallback((msg: string) => setToast({ type: 'error', text: msg }), [])

  const activeProvider = settings?.providers.find((p) => p.id === settings.activeProvider)

  const startCheck = useCallback(
    async (files: File[], ctx: CheckContext) => {
      setStarting(true)
      setNoApiKey(false)
      stopPolling()
      try {
        const form = new FormData()
        files.forEach((f) => form.append('files', f))
        if (ctx.contractSubject.trim()) form.append('contractSubject', ctx.contractSubject.trim())
        if (ctx.employmentType) form.append('employmentType', ctx.employmentType)
        if (ctx.extraContext.trim()) form.append('extraContext', ctx.extraContext.trim())

        const { jobId } = await api.startCheck(form)

        const poll = async () => {
          try {
            const j = await api.getJob(jobId)
            setJob(j)
            if (j.status !== 'running') stopPolling()
          } catch (e) {
            stopPolling()
            showError(e instanceof Error ? e.message : 'Ошибка получения статуса проверки')
          }
        }
        await poll()
        pollRef.current = window.setInterval(() => void poll(), 1500)
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && e.detail === 'no_api_key') {
          setNoApiKey(true)
        } else {
          showError(e instanceof Error ? e.message : 'Не удалось запустить проверку')
        }
      } finally {
        setStarting(false)
      }
    },
    [showError, stopPolling],
  )

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-4">
      {/* Шапка */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 py-4">
        <h1 className="text-lg font-bold text-zinc-50">Проверка должностных инструкций</h1>
        <div className="flex items-center gap-3">
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
            <SettingsPanel settings={settings} onUpdated={setSettings} onError={showError} />
          </aside>
        )}

        {/* Основная зона */}
        <main className="min-w-0 flex-1 space-y-6">
          <CheckPanel
            starting={starting}
            onStart={(files, ctx) => void startCheck(files, ctx)}
            onRejected={(names) =>
              setToast({
                type: 'error',
                text: `Неподдерживаемый формат: ${names.join(', ')}`,
              })
            }
          />
          {job && <Results job={job} onError={showError} />}
        </main>
      </div>

      <footer className="border-t border-zinc-800 py-3 text-center text-xs text-zinc-600">
        DI_Check — локальная проверка ДИ через LLM
      </footer>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  )
}
