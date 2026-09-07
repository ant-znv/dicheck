export interface ProviderDescriptor {
  id: string
  name: string
  baseUrl: string
  defaultModels: string[]
  hasApiKey: boolean
}

export interface Settings {
  providers: ProviderDescriptor[]
  activeProvider: string
  activeModel: string
  systemPrompt: string
  defaultSystemPrompt: string
  version: string
  update: {
    repo: string
    hasToken: boolean
  }
}

export interface UpdateInfo {
  current: string
  latest: string | null
  updateAvailable: boolean
  error: string | null
}

export interface TestConnectionResult {
  ok: boolean
  models?: string[]
  error?: string
}

export type Verdict = 'ok' | 'risk' | 'fail'

export interface Edit {
  id: string
  title: string
  original: string
  replacement: string
  reason: string
}

export interface JobResult {
  filename: string
  status: 'pending' | 'running' | 'done' | 'error' | 'cancelled'
  error: string | null
  report: string | null
  summaryVerdict: Verdict | null
  edits: Edit[]
  textTruncated?: boolean
}

export interface Job {
  id: string
  status: 'running' | 'done' | 'error' | 'cancelled'
  results: JobResult[]
}

export interface FixAllItem {
  resultIndex: number
  editIds: string[]
}

export class ApiError extends Error {
  status: number
  detail: string | null

  constructor(status: number, detail: string | null, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function parseErrorDetail(res: Response): Promise<string | null> {
  try {
    const body: unknown = await res.json()
    if (body && typeof body === 'object' && 'detail' in body) {
      const d = (body as { detail: unknown }).detail
      return typeof d === 'string' ? d : JSON.stringify(d)
    }
  } catch {
    // тело ответа не JSON — игнорируем
  }
  return null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError(0, null, 'Нет соединения с сервером')
  }
  if (!res.ok) {
    const detail = await parseErrorDetail(res)
    throw new ApiError(res.status, detail, `Ошибка сервера (${res.status})`)
  }
  return (await res.json()) as T
}

/** Единый текст ошибки для тостов: message + detail (если сервер его прислал). */
export function formatError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.detail ? `${e.message}: ${e.detail}` : e.message
  if (e instanceof Error) return e.message
  return fallback
}

/** Имя файла из заголовка Content-Disposition (RFC 5987 filename* и обычный filename=). */
function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const star = /filename\*\s*=\s*(?:utf-8|UTF-8)''([^;]+)/i.exec(header)
  if (star) {
    const raw = star[1].trim().replace(/^"|"$/g, '')
    try {
      return decodeURIComponent(raw)
    } catch {
      return raw
    }
  }
  const plain = /filename\s*=\s*(?:"([^"]*)"|([^;]+))/i.exec(header)
  if (plain) {
    const raw = (plain[1] ?? plain[2]).trim()
    try {
      return decodeURIComponent(raw)
    } catch {
      return raw
    }
  }
  return null
}

export interface DownloadedFile {
  blob: Blob
  /** Имя файла из Content-Disposition, если сервер его прислал. */
  filename: string | null
}

async function requestBlob(path: string, init?: RequestInit): Promise<DownloadedFile> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError(0, null, 'Нет соединения с сервером')
  }
  if (!res.ok) {
    const detail = await parseErrorDetail(res)
    throw new ApiError(res.status, detail, `Ошибка сервера (${res.status})`)
  }
  const blob = await res.blob()
  return { blob, filename: filenameFromDisposition(res.headers.get('Content-Disposition')) }
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export const api = {
  getSettings: () => request<Settings>('/api/settings'),

  putSettings: (body: {
    activeProvider?: string
    activeModel?: string
    systemPrompt?: string
    updateRepo?: string
  }) => request<Settings>('/api/settings', jsonInit('PUT', body)),

  putUpdateToken: (token: string) =>
    request<{ ok: boolean; hasToken: boolean }>(
      '/api/settings/update-token',
      jsonInit('PUT', { token }),
    ),

  checkUpdate: () => request<UpdateInfo>('/api/update/check'),

  installUpdate: () =>
    request<{ ok: boolean; version: string }>('/api/update/install', { method: 'POST' }),

  putApiKey: (provider: string, apiKey: string) =>
    request<{ ok: boolean; hasApiKey: boolean }>(
      '/api/settings/apikey',
      jsonInit('PUT', { provider, apiKey }),
    ),

  testConnection: (provider: string, model?: string) =>
    request<TestConnectionResult>(
      '/api/settings/test',
      jsonInit('POST', model ? { provider, model } : { provider }),
    ),

  startCheck: (form: FormData) =>
    request<{ jobId: string }>('/api/check', { method: 'POST', body: form }),

  getJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),

  cancelJob: (jobId: string) =>
    request<{ ok: boolean }>(`/api/jobs/${jobId}/cancel`, { method: 'POST' }),

  fixDocument: (jobId: string, resultIndex: number, editIds: string[]) =>
    requestBlob(`/api/jobs/${jobId}/fix`, jsonInit('POST', { resultIndex, editIds })),

  fixAll: (jobId: string, items: FixAllItem[]) =>
    requestBlob(`/api/jobs/${jobId}/fix-all`, jsonInit('POST', { items })),

  exportBlob: (jobId: string, format: 'md' | 'html' | 'docx') =>
    requestBlob(`/api/jobs/${jobId}/export?format=${format}`),
}
