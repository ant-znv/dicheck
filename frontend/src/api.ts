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

// --- История проверок ---

export type HistoryOrigin = 'check' | 'fix'

export interface HistoryLastCheck {
  verdict: Verdict
  checkedAt: string
  findingsCount: number
}

/** Элемент списка документов истории (GET /api/history/documents). */
export interface HistoryDocumentSummary {
  id: number
  title: string
  position: string
  department: string
  notes: string
  createdAt: string
  updatedAt: string
  versionsCount: number
  fixedCount: number
  lastCheck: HistoryLastCheck | null
}

/** Версия документа в карточке документа. */
export interface HistoryDocumentVersion {
  id: number
  origin: HistoryOrigin
  filename: string
  createdAt: string
  verdict: string | null
  findingsCount: number
  fixMethod: string | null
  appliedEditIds: string[]
  parentVersionId: number | null
  jobId: string | null
}

/** Карточка документа (GET /api/history/documents/{id}). */
export interface HistoryDocument {
  id: number
  title: string
  position: string
  department: string
  notes: string
  createdAt: string
  updatedAt: string
  versions: HistoryDocumentVersion[]
}

/** Замечание из детализации версии. */
export interface HistoryFinding {
  editId: string
  title: string
  original: string
  replacement: string
  reason: string
}

/** Детализация версии (GET /api/history/versions/{id}). */
export interface HistoryVersionDetail {
  id: number
  documentId: number
  origin: HistoryOrigin
  filename: string
  createdAt: string
  verdict: string | null
  fixMethod: string | null
  appliedEditIds: string[]
  parentVersionId: number | null
  jobId: string | null
  text: string
  textTruncated: boolean
  report: string | null
  findings: HistoryFinding[]
}

export interface HistoryPatchPayload {
  position?: string
  department?: string
  title?: string
  notes?: string
}

/** Результат автозаполнения метаданных одного документа (массовый режим). */
export interface HistoryExtractResult {
  documentId: number
  position: string
  department: string
  error: string | null
}

/** Результат извлечения обязанностей одного документа. */
export interface HistoryDutiesResult {
  documentId: number
  count: number
  duties: string[]
}

// --- Пересечения обязанностей ---

/** Документ, вошедший в отчёт о пересечениях. */
export interface OverlapDocument {
  documentId: number
  position: string
  department: string
  dutiesCount: number
}

/** Обязанность конкретного документа внутри группы пересечения. */
export interface OverlapItem {
  documentId: number
  position: string
  department: string
  duty: string
}

/** Группа пересекающихся обязанностей. */
export interface OverlapGroup {
  duty: string
  comment: string
  items: OverlapItem[]
}

/** Документ, пропущенный при построении отчёта (нет текста, ошибка LLM и т.п.). */
export interface OverlapSkipped {
  documentId: number
  position: string
  department: string
  error: string
}

/** Отчёт о пересечениях обязанностей (POST/GET /api/history/overlaps). */
export interface OverlapReport {
  id: number
  createdAt: string
  documents: OverlapDocument[]
  groups: OverlapGroup[]
  skipped: OverlapSkipped[]
}

// --- Шаблон экспорта ---

/** Статус шаблона выгрузки (GET /api/history/template). */
export interface HistoryTemplateInfo {
  exists: boolean
  /** Размер файла шаблона в байтах (когда задан). */
  size?: number
  /** Найденные в шаблоне плейсхолдеры, напр. ["ДОЛЖНОСТЬ","ТЕКСТ"]. */
  keys?: string[]
}

/** Результат загрузки шаблона (PUT /api/history/template). */
export interface HistoryTemplateUploadResult {
  ok: boolean
  size: number
  keys: string[]
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

  // --- История проверок ---

  listHistoryDocuments: (params: { search?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams()
    if (params.search) q.set('search', params.search)
    q.set('limit', String(params.limit ?? 100))
    q.set('offset', String(params.offset ?? 0))
    return request<{ total: number; items: HistoryDocumentSummary[] }>(
      `/api/history/documents?${q.toString()}`,
    )
  },

  getHistoryDocument: (id: number) => request<HistoryDocument>(`/api/history/documents/${id}`),

  getHistoryVersion: (id: number) => request<HistoryVersionDetail>(`/api/history/versions/${id}`),

  downloadHistoryVersion: (id: number) => requestBlob(`/api/history/versions/${id}/download`),

  patchHistoryDocument: (id: number, body: HistoryPatchPayload) =>
    request<HistoryDocumentSummary>(`/api/history/documents/${id}`, jsonInit('PATCH', body)),

  deleteHistoryDocument: (id: number) =>
    request<{ ok: boolean }>(`/api/history/documents/${id}`, { method: 'DELETE' }),

  extractHistoryDocumentMeta: (id: number) =>
    request<{ position: string; department: string }>(
      `/api/history/documents/${id}/extract-meta`,
      { method: 'POST' },
    ),

  extractHistoryMetaBulk: (documentIds: number[] | null) =>
    request<{ results: HistoryExtractResult[] }>(
      '/api/history/extract-meta',
      jsonInit('POST', { documentIds }),
    ),

  extractDuties: (id: number) =>
    request<HistoryDutiesResult>(`/api/history/documents/${id}/extract-duties`, {
      method: 'POST',
    }),

  /**
   * Запуск поиска пересечений обязанностей (долгая LLM-операция).
   * null — сравнить все документы.
   */
  runOverlaps: (documentIds: number[] | null) =>
    request<OverlapReport>('/api/history/overlaps', jsonInit('POST', { documentIds })),

  /** Последний сохранённый отчёт о пересечениях (404 no_report, если ещё не запускался). */
  getLatestOverlaps: () => request<OverlapReport>('/api/history/overlaps'),

  /** Загрузка шаблона выгрузки: сырые байты .docx (application/octet-stream). */
  uploadTemplate: (bytes: Blob) =>
    request<HistoryTemplateUploadResult>('/api/history/template', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: bytes,
    }),

  getTemplate: () => request<HistoryTemplateInfo>('/api/history/template'),

  deleteTemplate: () => request<{ ok: boolean }>('/api/history/template', { method: 'DELETE' }),

  /**
   * Выгрузка исправленных ДИ в ZIP. С options.template=true — по шаблону
   * (409 no_template, если шаблон не задан).
   */
  exportHistoryFixed: (documentIds?: number[], options?: { template?: boolean }) => {
    const q = new URLSearchParams()
    if (documentIds) q.set('documentIds', documentIds.join(','))
    if (options?.template) q.set('template', 'true')
    const qs = q.toString()
    return requestBlob(`/api/history/export/fixed${qs ? `?${qs}` : ''}`)
  },
}
