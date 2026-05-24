import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'

// In dev, Vite proxies /api to localhost:8000 and strips the /api prefix.
// In production (Docker/Render same-origin), the backend serves routes at
// /auth, /chat, etc. — NOT under /api — so we call them directly.
const _devBase = import.meta.env.DEV ? '/api' : ''
const API_BASE = import.meta.env.VITE_API_URL || _devBase
const STREAM_BASE = import.meta.env.VITE_API_URL || _devBase

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 120_000,
  headers: { 'Content-Type': 'application/json' },
})

// Requests we'll automatically retry on transient failures. POST/PUT/DELETE
// are deliberately excluded because retrying them could duplicate writes
// (e.g. sending the same chat message twice, double-billing).
const SAFE_METHODS = new Set(['get', 'head', 'options'])
const MAX_RETRIES = 2
const BASE_BACKOFF_MS = 400

type RetryableConfig = InternalAxiosRequestConfig & {
  _retry?: boolean
  _retryCount?: number
}

function shouldRetry(err: AxiosError): boolean {
  const cfg = err.config as RetryableConfig | undefined
  if (!cfg) return false
  const method = (cfg.method || 'get').toLowerCase()
  if (!SAFE_METHODS.has(method)) return false
  if ((cfg._retryCount ?? 0) >= MAX_RETRIES) return false

  // Network-level failure (no response) or transient server status.
  if (!err.response) return true
  const status = err.response.status
  return status === 429 || status === 502 || status === 503 || status === 504
}

function computeBackoff(err: AxiosError, attempt: number): number {
  // Honour Retry-After when the server tells us how long to wait.
  const retryAfter = err.response?.headers?.['retry-after']
  if (retryAfter) {
    const seconds = Number(retryAfter)
    if (Number.isFinite(seconds) && seconds >= 0) {
      return Math.min(seconds * 1000, 10_000)
    }
  }
  // Exponential backoff with full jitter to avoid thundering herds.
  const exp = BASE_BACKOFF_MS * 2 ** attempt
  return Math.min(exp, 8_000) * (0.5 + Math.random() * 0.5)
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('id_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  async (err: AxiosError) => {
    const original = err.config as RetryableConfig

    // Don't bother retrying explicit cancellations.
    if (axios.isCancel?.(err) || err.code === 'ERR_CANCELED') {
      return Promise.reject(err)
    }

    // 401 → refresh token once and replay (existing behaviour).
    if (err.response?.status === 401 && original && !original._retry) {
      original._retry = true
      const newToken = await _refreshTokenIfNeeded()
      if (newToken) {
        original.headers.Authorization = `Bearer ${newToken}`
        return api(original)
      }
    }

    // Transient-failure retry with exponential backoff for safe requests.
    if (original && shouldRetry(err)) {
      const attempt = original._retryCount ?? 0
      original._retryCount = attempt + 1
      const delay = computeBackoff(err, attempt)
      await new Promise((resolve) => setTimeout(resolve, delay))
      return api(original)
    }

    return Promise.reject(err)
  },
)

/**
 * Attempt to refresh the id_token using the stored refresh_token.
 * Returns the new id_token on success, or null on failure (and
 * redirects to /login). Shared by both the axios interceptor and
 * the raw-fetch streaming helpers.
 */
async function _refreshTokenIfNeeded(): Promise<string | null> {
  const refresh = localStorage.getItem('refresh_token')
  if (!refresh) {
    localStorage.removeItem('id_token')
    window.location.href = '/login'
    return null
  }
  try {
    const { data } = await axios.post(`${API_BASE}/auth/refresh`, { refresh_token: refresh })
    localStorage.setItem('id_token', data.id_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    return data.id_token as string
  } catch {
    localStorage.removeItem('id_token')
    localStorage.removeItem('refresh_token')
    window.location.href = '/login'
    return null
  }
}

// Auth
export const authApi = {
  signIn: (email: string, password: string) =>
    api.post('/auth/signin', { email, password }),
  signUp: (email: string, password: string, name?: string) =>
    api.post('/auth/signup', { email, password, name }),
  verifyOtp: (email: string, password: string, otp: string) =>
    api.post('/auth/verify-otp', { email, password, otp }),
  forgotPassword: (email: string) =>
    api.post('/auth/reset', { email }),
  resendVerification: (email: string, password: string) =>
    api.post('/auth/resend-verification', { email, password }),
  verifyResetCode: (oob_code: string) =>
    api.post('/auth/verify-reset', { oob_code }),
  confirmReset: (oob_code: string, new_password: string) =>
    api.post('/auth/confirm-reset', { oob_code, new_password }),
  me: () => api.get('/auth/me'),
  refresh: (refresh_token: string) =>
    api.post('/auth/refresh', { refresh_token }),
  getPreferences: () => api.get('/auth/preferences'),
  updatePreferences: (prefs: { instructions: string; about_me: string; response_mode: string; emoji_frequency: string }) => 
    api.post('/auth/preferences', prefs),
}

// Chat
//
// `modeOrModel` accepts either a product mode ('Fast' | 'Think') or a legacy
// model_choice token. The backend's mode_routing translates 'Fast' / 'Think'
// to the appropriate internal model. Anything else is passed through as
// `model_choice` for backward compatibility.
type ChatModeArg = 'Fast' | 'Think' | string
function _splitModeArg(arg: ChatModeArg): { mode: 'Fast' | 'Think' | null; model_choice: string } {
  if (arg === 'Fast' || arg === 'Think') {
    return { mode: arg, model_choice: 'Llama' }
  }
  return { mode: null, model_choice: arg }
}

// Minimal chat-history shape the backend expects. Drop client-side metadata
// (ids, timestamps, etc.) at the API boundary so the wire payload stays lean.
export interface ChatHistoryEntry {
  role: 'user' | 'assistant'
  content: string
}

export const chatApi = {
  send: (
    query: string,
    modeOrModel: ChatModeArg = 'Fast',
    temperature = 0.2,
    web_search = false,
    research = false,
    history: ChatHistoryEntry[] = [],
  ) => {
    const { mode, model_choice } = _splitModeArg(modeOrModel)
    return api.post('/chat', {
      query,
      mode,
      model_choice,
      temperature,
      web_search,
      research,
      history,
    })
  },

  /** Initiate a streaming POST and return the raw Response body reader.
   *  Caller must parse SSE events from the stream. */
  stream: async (
    query: string,
    modeOrModel: ChatModeArg = 'Fast',
    temperature = 0.2,
    web_search = false,
    research = false,
    signal?: AbortSignal,
    history: ChatHistoryEntry[] = [],
  ): Promise<ReadableStreamDefaultReader<Uint8Array>> => {
    const { mode, model_choice } = _splitModeArg(modeOrModel)
    const token = localStorage.getItem('id_token')
    const res = await fetch(
      `${STREAM_BASE}/chat/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          query,
          mode,
          model_choice,
          temperature,
          web_search,
          research,
          history,
        }),
        signal,
      }
    )
    // Handle 401 by refreshing token and retrying once
    if (res.status === 401) {
      const newToken = await _refreshTokenIfNeeded()
      if (newToken) {
        const retryRes = await fetch(
          `${STREAM_BASE}/chat/stream`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${newToken}`,
            },
            body: JSON.stringify({
              query,
              mode,
              model_choice,
              temperature,
              web_search,
              research,
              history,
            }),
            signal,
          }
        )
        if (!retryRes.ok) {
          const text = await retryRes.text()
          throw new Error(`Stream failed: ${retryRes.status} ${text}`)
        }
        if (!retryRes.body) throw new Error('No response body')
        return retryRes.body.getReader()
      }
      throw new Error('Session expired. Please sign in again.')
    }
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`Stream failed: ${res.status} ${text}`)
    }
    if (!res.body) throw new Error('No response body')
    return res.body.getReader()
  },
  history: {
    list: () => api.get('/chat/history'),
    get: (id: string) => api.get(`/chat/history/${id}`),
    save: (conv: {
      id: string
      title: string
      createdAt: number
      updatedAt: number
      messages: any[]
    }) => api.post('/chat/history', conv),
    delete: (id: string) => api.delete(`/chat/history/${id}`),
    clear: () => api.delete('/chat/history'),
  },
}

// Images
export interface GenerateImagePayload {
  prompt: string
  model: string
  width: number
  height: number
  seed: number
}

// Rate limits
export const limitsApi = {
  get: () => api.get('/limits'),
}

export interface ImageHistoryEntry {
  id: number
  prompt: string
  model: string
  width: number
  height: number
  seed: number
  created_at: number
}

export const imagesApi = {
  status: () => api.get('/images/status'),
  generate: async (payload: GenerateImagePayload) => {
    const res = await api.post('/images/generate', payload, {
      responseType: 'blob',
    })
    const ct = (res.headers['content-type'] as string) || 'image/png'
    const blob = new Blob([res.data], { type: ct })
    return { blob, url: URL.createObjectURL(blob), model: payload.model, seed: payload.seed }
  },
  testModel: (model: string) => api.get(`/images/test-model/${model}`),
  getHistory: () => api.get<ImageHistoryEntry[]>('/images/history'),
  saveHistory: (payload: { prompt: string; model: string; width: number; height: number; seed: number }) =>
    api.post<ImageHistoryEntry>('/images/history', payload),
  deleteHistory: (id: number) => api.delete(`/images/history/${id}`),
  clearHistory: () => api.delete('/images/history'),
}

// File Upload
export const uploadApi = {
  upload: async (chatId: string, files: File[]) => {
    const formData = new FormData()
    formData.append('chat_id', chatId)
    files.forEach((f) => formData.append('files', f))
    return api.post('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300_000,
    })
  },
  status: (chatId: string) => api.get(`/upload/status/${chatId}`),
  listFiles: (chatId: string) => api.get(`/upload/files/${chatId}`),
  deleteFile: (chatId: string, filename: string) =>
    api.delete(`/upload/${chatId}/${filename}`),
}

// Multimodal Chat
export interface MultimodalResponse {
  answer: string
  pipeline: string
  citations?: Array<{ ref?: number; source?: string; page?: number; score?: number; excerpt?: string }>
  chart?: {
    type: string
    x?: string
    y?: string
    labels?: string
    values?: string
    title?: string
  }
  analytics_result?: {
    sql?: string
    columns?: string[]
    rows?: Record<string, any>[]
    row_count?: number
  }
}

export const multimodalApi = {
  /**
   * Send a query to the multimodal pipeline (non-streaming, JSON response).
   *
   * @param currentFiles Filenames of files attached **with this specific
   *   turn**. The backend uses this to tell the LLM which file(s) the user
   *   is actually asking about right now, vs. older files still in the chat.
   */
  chat: (
    query: string,
    chatId: string,
    modeOrModel: ChatModeArg = 'Fast',
    temperature = 0.2,
    currentFiles: string[] = [],
    signal?: AbortSignal,
  ) => {
    const { model_choice } = _splitModeArg(modeOrModel)
    return api.post<MultimodalResponse>('/chat/multimodal', {
      query,
      chat_id: chatId,
      model_choice,
      temperature,
      current_files: currentFiles,
    }, { signal })
  },

  /**
   * Stream the multimodal pipeline response as SSE.
   * Caller must parse `data:` lines from the stream.
   */
  stream: async (
    query: string,
    chatId: string,
    modeOrModel: ChatModeArg = 'Fast',
    temperature = 0.2,
    currentFiles: string[] = [],
    signal?: AbortSignal,
  ): Promise<ReadableStreamDefaultReader<Uint8Array>> => {
    const { model_choice } = _splitModeArg(modeOrModel)
    const token = localStorage.getItem('id_token')
    const res = await fetch(
      `${STREAM_BASE}/chat/multimodal/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          query,
          chat_id: chatId,
          model_choice,
          temperature,
          current_files: currentFiles,
        }),
        signal,
      },
    )
    // Handle 401 by refreshing token and retrying once
    if (res.status === 401) {
      const newToken = await _refreshTokenIfNeeded()
      if (newToken) {
        const retryRes = await fetch(
          `${STREAM_BASE}/chat/multimodal/stream`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${newToken}`,
            },
            body: JSON.stringify({
              query,
              chat_id: chatId,
              model_choice,
              temperature,
              current_files: currentFiles,
            }),
            signal,
          },
        )
        if (!retryRes.ok) {
          const text = await retryRes.text()
          throw new Error(`Multimodal stream failed: ${retryRes.status} ${text}`)
        }
        if (!retryRes.body) throw new Error('No response body')
        return retryRes.body.getReader()
      }
      throw new Error('Session expired. Please sign in again.')
    }
    if (!res.ok) {
      const text = await res.text()
      throw new Error(`Multimodal stream failed: ${res.status} ${text}`)
    }
    if (!res.body) throw new Error('No response body')
    return res.body.getReader()
  },
}

// ── Sheets (natural-language Excel querying) ─────────────────────

export interface SheetColumn {
  column: string
  dtype: string
  non_null_count: number
  null_count: number
}

export interface SheetStats {
  min: number
  max: number
  mean: number
  median: number
  std: number
}

export interface SheetMeta {
  filename: string
  row_count: number
  column_count: number
  columns: string[]
  schema: SheetColumn[]
  statistics: Record<string, SheetStats>
  sample_rows: Record<string, unknown>[]
}

export interface SheetQueryResponse {
  sql: string
  columns: string[]
  rows: Record<string, unknown>[]
  row_count: number
  truncated: boolean
  summary: string | null
  chart: { type: string; title?: string; x?: string; y?: string; labels?: string; values?: string; series?: { key: string; name: string }[] } | null
}

export const sheetsApi = {
  /** Replace the user's active spreadsheet. Returns parsed schema + stats. */
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<SheetMeta>('/sheets/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300_000,
    })
  },
  /** Returns `null` data if the user has no active sheet. */
  current: () => api.get<SheetMeta | null>('/sheets/current'),
  /** LLM-generated contextual suggestion queries for the current sheet. */
  suggestions: () => api.get<{ suggestions: string[] }>('/sheets/suggestions'),
  /** Natural-language query → SQL → preview rows. */
  query: (question: string, modelChoice: ChatModeArg = 'Fast') => {
    const { model_choice } = _splitModeArg(modelChoice)
    return api.post<SheetQueryResponse>('/sheets/query', {
      question,
      model_choice,
    })
  },
  /**
   * Re-run a query (or pre-built SQL) and stream the result back as an
   * .xlsx file. Returns the raw Blob so the caller can trigger a download.
   */
  exportXlsx: async (opts: { question?: string; sql?: string; modelChoice?: ChatModeArg }) => {
    const { model_choice } = _splitModeArg(opts.modelChoice ?? 'Fast')
    const res = await api.post(
      '/sheets/export',
      {
        question: opts.question,
        sql: opts.sql,
        model_choice,
      },
      { responseType: 'blob' },
    )
    const ct =
      (res.headers['content-type'] as string) ||
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    const blob = new Blob([res.data], { type: ct })
    // The browser doesn't expose Content-Disposition reliably across origins,
    // so we fall back to deriving a name on the caller side.
    return {
      blob,
      url: URL.createObjectURL(blob),
      rows: Number(res.headers['x-sheet-rows'] || 0),
      columns: Number(res.headers['x-sheet-columns'] || 0),
      sql: (res.headers['x-sheet-sql'] as string) || '',
    }
  },
  delete: () => api.delete('/sheets/current'),
  /** Re-run a query and stream back as CSV. */
  exportCsv: async (opts: { question?: string; sql?: string; modelChoice?: ChatModeArg }) => {
    const { model_choice } = _splitModeArg(opts.modelChoice ?? 'Fast')
    const res = await api.post('/sheets/export-csv', {
      question: opts.question,
      sql: opts.sql,
      model_choice,
    }, { responseType: 'blob' })
    const blob = new Blob([res.data], { type: 'text/csv' })
    return { blob, url: URL.createObjectURL(blob) }
  },
}

// ── Usage dashboard ───────────────────────────────────────────────

export interface UsageResponse {
  storage: {
    used_bytes: number
    quota_bytes: number
    used_mb: number
    quota_mb: number
  }
  limits: {
    deep_research_remaining: number
  }
}

export const usageApi = {
  getUsage: () => api.get<UsageResponse>('/auth/me/usage'),
}

export const transcribeApi = {
  transcribe: (blob: Blob) => {
    const formData = new FormData()
    formData.append('file', blob, 'recording.webm')
    return api.post<{ transcript: string }>('/transcribe', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 30_000,
    })
  },
}

// ── Diagram & Architecture Studio API ──────────────────────────────

export interface DiagramGeneratePayload {
  prompt: string
  diagram_type?: string
  file_content?: string
  file_name?: string
  existing_mermaid?: string
}

export interface DiagramAnalyzePayload {
  mermaid_code: string
  nodes?: any[]
  edges?: any[]
}

export interface DiagramResponse {
  id: string
  title: string
  diagramType: string
  createdAt: number
  updatedAt: number
  nodes: any[]
  edges: any[]
  mermaidCode: string
  metadata: any
}

export const diagramApi = {
  generate: (payload: DiagramGeneratePayload) =>
    api.post('/diagram/generate', payload),
  analyze: (payload: DiagramAnalyzePayload) =>
    api.post('/diagram/analyze', payload),
  history: {
    list: () => api.get<DiagramResponse[]>('/diagram/history'),
    get: (id: string) => api.get<DiagramResponse>(`/diagram/history/${id}`),
    save: (diagram: DiagramResponse) => api.post('/diagram/history', diagram),
    delete: (id: string) => api.delete(`/diagram/history/${id}`),
  },
}

