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
  status: 'pending' | 'running' | 'done' | 'error'
  error: string | null
  report: string | null
  summaryVerdict: Verdict | null
  edits: Edit[]
}

export interface Job {
  id: string
  status: 'running' | 'done' | 'error'
  results: JobResult[]
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

async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
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
  return res.blob()
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
  }) => request<Settings>('/api/settings', jsonInit('PUT', body)),

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

  fixDocument: (jobId: string, resultIndex: number, editIds: string[]) =>
    requestBlob(`/api/jobs/${jobId}/fix`, jsonInit('POST', { resultIndex, editIds })),

  exportUrl: (jobId: string, format: 'md' | 'html') =>
    `/api/jobs/${jobId}/export?format=${format}`,
}
