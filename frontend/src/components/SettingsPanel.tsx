import { useMemo, useState } from 'react'
import { api, type Settings, type UpdateInfo } from '../api'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

interface Props {
  settings: Settings
  onUpdated: (s: Settings) => void
  onError: (msg: string) => void
  autoUpdateInfo?: UpdateInfo | null
}

function StatusNote({ state, errorText }: { state: SaveState; errorText?: string }) {
  if (state === 'saved') return <span className="text-xs text-emerald-400">Сохранено</span>
  if (state === 'error')
    return <span className="text-xs text-red-400">{errorText ?? 'Ошибка сохранения'}</span>
  return null
}

const inputCls =
  'w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 outline-none transition-colors focus:border-sky-500 disabled:opacity-50'
const btnCls =
  'cursor-pointer rounded-lg border border-zinc-600 bg-zinc-800 px-3 py-2 text-sm font-medium text-zinc-100 transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50'
const btnPrimaryCls =
  'cursor-pointer rounded-lg bg-sky-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50'

export default function SettingsPanel({ settings, onUpdated, onError, autoUpdateInfo }: Props) {
  const [provider, setProvider] = useState(settings.activeProvider)
  const [model, setModel] = useState(settings.activeModel)
  const [fetchedModels, setFetchedModels] = useState<string[]>([])
  const [selectionState, setSelectionState] = useState<SaveState>('idle')

  const [apiKey, setApiKey] = useState('')
  const [apiKeyState, setApiKeyState] = useState<SaveState>('idle')

  const [prompt, setPrompt] = useState(settings.systemPrompt)
  const [promptState, setPromptState] = useState<SaveState>('idle')

  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null)

  const [updateRepo, setUpdateRepo] = useState(settings.update.repo)
  const [updateRepoState, setUpdateRepoState] = useState<SaveState>('idle')
  const [updateToken, setUpdateToken] = useState('')
  const [updateTokenState, setUpdateTokenState] = useState<SaveState>('idle')
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(autoUpdateInfo ?? null)
  const [checkingUpdate, setCheckingUpdate] = useState(false)
  const [installingUpdate, setInstallingUpdate] = useState(false)
  const [installNote, setInstallNote] = useState<string | null>(null)

  const currentProvider = useMemo(
    () => settings.providers.find((p) => p.id === provider) ?? settings.providers[0],
    [settings.providers, provider],
  )

  const modelSuggestions = useMemo(() => {
    const all = [...(currentProvider?.defaultModels ?? []), ...fetchedModels]
    return [...new Set(all)]
  }, [currentProvider, fetchedModels])

  const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Неизвестная ошибка')

  const saveSelection = async () => {
    setSelectionState('saving')
    try {
      const updated = await api.putSettings({ activeProvider: provider, activeModel: model })
      onUpdated(updated)
      setSelectionState('saved')
    } catch (e) {
      setSelectionState('error')
      onError(errorText(e))
    }
  }

  const saveApiKey = async () => {
    setApiKeyState('saving')
    try {
      const res = await api.putApiKey(provider, apiKey.trim())
      onUpdated({
        ...settings,
        providers: settings.providers.map((p) =>
          p.id === provider ? { ...p, hasApiKey: res.hasApiKey } : p,
        ),
      })
      setApiKey('')
      setApiKeyState('saved')
    } catch (e) {
      setApiKeyState('error')
      onError(errorText(e))
    }
  }

  const savePrompt = async () => {
    setPromptState('saving')
    try {
      const updated = await api.putSettings({ systemPrompt: prompt })
      onUpdated(updated)
      setPromptState('saved')
    } catch (e) {
      setPromptState('error')
      onError(errorText(e))
    }
  }

  const resetPrompt = () => {
    setPrompt(settings.defaultSystemPrompt)
    setPromptState('idle')
  }

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await api.testConnection(provider, model || undefined)
      if (res.ok) {
        if (res.models && res.models.length > 0) setFetchedModels(res.models)
        setTestResult({
          ok: true,
          text: `Соединение установлено${res.models?.length ? `, моделей: ${res.models.length}` : ''}`,
        })
      } else {
        setTestResult({ ok: false, text: res.error ?? 'Проверка не удалась' })
      }
    } catch (e) {
      setTestResult({ ok: false, text: errorText(e) })
    } finally {
      setTesting(false)
    }
  }

  const saveUpdateRepo = async () => {
    setUpdateRepoState('saving')
    try {
      const updated = await api.putSettings({ updateRepo: updateRepo.trim() })
      onUpdated(updated)
      setUpdateRepoState('saved')
    } catch (e) {
      setUpdateRepoState('error')
      onError(errorText(e))
    }
  }

  const saveUpdateToken = async () => {
    setUpdateTokenState('saving')
    try {
      const res = await api.putUpdateToken(updateToken.trim())
      onUpdated({
        ...settings,
        update: { ...settings.update, hasToken: res.hasToken },
      })
      setUpdateToken('')
      setUpdateTokenState('saved')
    } catch (e) {
      setUpdateTokenState('error')
      onError(errorText(e))
    }
  }

  const runUpdateCheck = async () => {
    setCheckingUpdate(true)
    setInstallNote(null)
    try {
      setUpdateInfo(await api.checkUpdate())
    } catch (e) {
      onError(errorText(e))
    } finally {
      setCheckingUpdate(false)
    }
  }

  const runUpdateInstall = async () => {
    setInstallingUpdate(true)
    setInstallNote(null)
    try {
      const res = await api.installUpdate()
      setInstallNote(
        `Установщик версии ${res.version} запущен в фоне: он закроет приложение, обновит файлы и запустит новую версию.`,
      )
      setUpdateInfo(null)
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Не удалось запустить обновление')
    } finally {
      setInstallingUpdate(false)
    }
  }

  return (
    <div className="space-y-6 p-4">
      {/* Провайдер и модель */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-zinc-300">Провайдер и модель</h3>
        <div>
          <label htmlFor="provider" className="mb-1 block text-xs text-zinc-400">
            Провайдер
          </label>
          <select
            id="provider"
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value)
              setSelectionState('idle')
              setTestResult(null)
              setFetchedModels([])
            }}
            className={inputCls}
          >
            {settings.providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {currentProvider && (
            <p className="mt-1 text-xs text-zinc-500">{currentProvider.baseUrl}</p>
          )}
        </div>
        <div>
          <label htmlFor="model" className="mb-1 block text-xs text-zinc-400">
            Модель
          </label>
          <input
            id="model"
            list="model-suggestions"
            value={model}
            onChange={(e) => {
              setModel(e.target.value)
              setSelectionState('idle')
            }}
            placeholder="Введите или выберите модель"
            className={inputCls}
          />
          <datalist id="model-suggestions">
            {modelSuggestions.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={saveSelection}
            disabled={selectionState === 'saving'}
            className={btnPrimaryCls}
          >
            {selectionState === 'saving' ? 'Сохранение…' : 'Сохранить выбор'}
          </button>
          <button
            type="button"
            onClick={testConnection}
            disabled={testing}
            className={btnCls}
          >
            {testing ? 'Проверка…' : 'Проверить соединение'}
          </button>
          <StatusNote state={selectionState} />
        </div>
        {testResult && (
          <p className={`text-xs ${testResult.ok ? 'text-emerald-400' : 'text-red-400'}`}>
            {testResult.text}
          </p>
        )}
      </section>

      {/* API-ключ */}
      <section className="space-y-3 border-t border-zinc-800 pt-4">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-zinc-300">API-ключ</h3>
          {currentProvider?.hasApiKey && (
            <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-400">
              ключ сохранён
            </span>
          )}
        </div>
        <div>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value)
              setApiKeyState('idle')
            }}
            placeholder={
              currentProvider?.hasApiKey
                ? 'Ключ сохранён — введите новый, чтобы заменить'
                : 'Введите API-ключ'
            }
            autoComplete="off"
            className={inputCls}
          />
          <p className="mt-1 text-xs text-zinc-500">
            Ключ хранится локально в зашифрованном виде и не отображается. Пустое значение удаляет
            ключ.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={saveApiKey}
            disabled={apiKeyState === 'saving'}
            className={btnPrimaryCls}
          >
            {apiKeyState === 'saving' ? 'Сохранение…' : 'Сохранить'}
          </button>
          <StatusNote state={apiKeyState} />
        </div>
      </section>

      {/* Системный промт */}
      <section className="space-y-3 border-t border-zinc-800 pt-4">
        <h3 className="text-sm font-semibold text-zinc-300">Системный промт</h3>
        <textarea
          value={prompt}
          onChange={(e) => {
            setPrompt(e.target.value)
            setPromptState('idle')
          }}
          rows={10}
          spellCheck={false}
          className={`${inputCls} resize-y font-mono text-xs leading-relaxed`}
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={savePrompt}
            disabled={promptState === 'saving'}
            className={btnPrimaryCls}
          >
            {promptState === 'saving' ? 'Сохранение…' : 'Сохранить'}
          </button>
          <button type="button" onClick={resetPrompt} className={btnCls}>
            Сбросить к умолчанию
          </button>
          <StatusNote state={promptState} />
        </div>
      </section>

      {/* Обновления */}
      <section className="space-y-3 border-t border-zinc-800 pt-4">
        <h3 className="text-sm font-semibold text-zinc-300">
          Обновления{' '}
          <span className="text-xs font-normal text-zinc-500">версия {settings.version}</span>
        </h3>
        <div>
          <label htmlFor="updateRepo" className="mb-1 block text-xs text-zinc-400">
            Репозиторий GitHub (owner/repo)
          </label>
          <input
            id="updateRepo"
            value={updateRepo}
            onChange={(e) => {
              setUpdateRepo(e.target.value)
              setUpdateRepoState('idle')
            }}
            placeholder="ant-znv/dicheck"
            className={inputCls}
          />
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={saveUpdateRepo}
            disabled={updateRepoState === 'saving'}
            className={btnPrimaryCls}
          >
            {updateRepoState === 'saving' ? 'Сохранение…' : 'Сохранить'}
          </button>
          <StatusNote state={updateRepoState} />
        </div>
        <div>
          <input
            type="password"
            value={updateToken}
            onChange={(e) => {
              setUpdateToken(e.target.value)
              setUpdateTokenState('idle')
            }}
            placeholder={
              settings.update.hasToken
                ? 'Токен сохранён — введите новый, чтобы заменить'
                : 'Токен GitHub (только для приватного репозитория)'
            }
            autoComplete="off"
            className={inputCls}
          />
          <p className="mt-1 text-xs text-zinc-500">
            Для публичного репозитория токен не нужен. Пустое значение удаляет токен.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={saveUpdateToken}
            disabled={updateTokenState === 'saving'}
            className={btnCls}
          >
            {updateTokenState === 'saving' ? 'Сохранение…' : 'Сохранить токен'}
          </button>
          <StatusNote state={updateTokenState} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={runUpdateCheck}
            disabled={checkingUpdate}
            className={btnCls}
          >
            {checkingUpdate ? 'Проверка…' : 'Проверить обновления'}
          </button>
          {updateInfo?.updateAvailable && (
            <button
              type="button"
              onClick={runUpdateInstall}
              disabled={installingUpdate}
              className={btnPrimaryCls}
            >
              {installingUpdate ? 'Скачивание…' : `Скачать и установить ${updateInfo.latest}`}
            </button>
          )}
        </div>
        {updateInfo?.error && <p className="text-xs text-zinc-500">{updateInfo.error}</p>}
        {updateInfo && !updateInfo.error && !updateInfo.updateAvailable && (
          <p className="text-xs text-emerald-400">У вас последняя версия.</p>
        )}
        {installNote && <p className="text-xs text-amber-400">{installNote}</p>}
      </section>
    </div>
  )
}
