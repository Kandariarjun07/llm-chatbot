import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { chatApi, limitsApi, uploadApi, multimodalApi, transcribeApi } from '../lib/api'
import { useChatStore, type ChatMessage } from '../store/chatStore'
import {
  PaperPlaneRight,
  Spinner,
  Sparkle,
  User,
  Plus,
  Globe,
  Flask,
  ImageSquare,
  FileText,
  X,
  Paperclip,
  Stop,
  Copy,
  ArrowCounterClockwise,
  Article,
  Microphone,
} from '@phosphor-icons/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const SUGGESTIONS = [
  'Explain quantum computing in one paragraph.',
  'Write a Python function to reverse a string in place.',
  'Outline best practices for REST API design.',
  'Draft a short story about a cartographer of dreams.',
]

/**
 * Ask the LLM for a short 3-6 word title for a new conversation.
 * Returns null on failure so the caller keeps the auto-derived fallback.
 */
async function generateTitle(userMessage: string): Promise<string | null> {
  try {
    const prompt =
      `Generate a concise 3-6 word title for a conversation that begins with the ` +
      `following user message. Respond with ONLY the title text — no quotes, no ` +
      `trailing punctuation, no prefix like "Title:".\n\n` +
      `User message: ${userMessage}`

    const res = await chatApi.send(prompt)
    const raw = (res.data?.answer || '').trim()
    if (!raw) return null

    // Take first line only, strip quotes/backticks, collapse whitespace, drop trailing punct
    const cleaned = raw
      .split('\n')[0]
      .replace(/^["'`*_\s]+|["'`*_\s]+$/g, '')
      .replace(/^(title\s*[:\-])\s*/i, '')
      .replace(/\s+/g, ' ')
      .replace(/[.!?,;:]+$/g, '')
      .trim()

    if (!cleaned) return null
    return cleaned.length > 60 ? cleaned.slice(0, 60) + '…' : cleaned
  } catch {
    return null
  }
}

export default function Chat() {
  const {
    conversations,
    activeId,
    loaded,
    ensureActive,
    appendMessage,
    updateMessage,
    renameConversation,
    createConversation,
  } = useChatStore()
  const { id: urlId } = useParams<{ id?: string }>()
  const navigate = useNavigate()

  // Persist input across reloads and loading transitions
  const [input, setInputRaw] = useState(() => {
    return sessionStorage.getItem('chat_draft_input') || ''
  })
  const setInput = (value: string | ((prev: string) => string)) => {
    if (typeof value === 'function') {
      setInputRaw((prev) => {
        const next = value(prev)
        if (next) sessionStorage.setItem('chat_draft_input', next)
        else sessionStorage.removeItem('chat_draft_input')
        return next
      })
    } else {
      setInputRaw(value)
      if (value) sessionStorage.setItem('chat_draft_input', value)
      else sessionStorage.removeItem('chat_draft_input')
    }
  }
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Voice recording
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  // Composer tools
  const [webSearch, setWebSearch] = useState(false)
  const [research, setResearch] = useState(false)
  const [deepResearchRemaining, setDeepResearchRemaining] = useState<number | null>(null)
  const [mode, setMode] = useState<'Fast' | 'Think'>('Fast')
  // Drives the typewriter status indicator while waiting for the first delta.
  // Set per-turn from the active flags (research > search > uploading > thinking).
  const [streamingMode, setStreamingMode] = useState<'thinking' | 'search' | 'research' | 'uploading'>('thinking')
  // Live phase text emitted from the backend SSE stream (e.g. "found 8 sources").
  // Overrides the cycling default messages while it's set.
  const [phaseMessage, setPhaseMessage] = useState<string | null>(null)
  const [plusOpen, setPlusOpen] = useState(false)
  const [attached, setAttached] = useState<Array<{ id: string; name: string; size: number; kind: 'image' | 'file' }>>([])
  const [uploading, setUploading] = useState(false)
  const [chatHasFiles, setChatHasFiles] = useState(false)
  // Filenames uploaded *since the last user turn* — sent to the multimodal
  // backend so the LLM knows which file(s) the current question is about.
  const [pendingFiles, setPendingFiles] = useState<string[]>([])
  const plusRef = useRef<HTMLDivElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Close "+" menu on outside click / Escape
  useEffect(() => {
    if (!plusOpen) return
    const onDown = (e: MouseEvent) => {
      if (!plusRef.current?.contains(e.target as Node)) setPlusOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPlusOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [plusOpen])

  // Fetch remaining deep-research uses on mount
  useEffect(() => {
    limitsApi.get()
      .then((res) => setDeepResearchRemaining(res.data.deep_research_remaining))
      .catch(() => setDeepResearchRemaining(null))
  }, [])

  // Abort any in-flight streaming request on unmount. Without this, a user
  // who navigates away mid-stream keeps a fetch open in the background and
  // — worse — its onChunk handlers will call setState on an unmounted
  // component, producing the classic React warning and (occasionally)
  // stale state updates if the user returns to the page.
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
      abortRef.current = null
    }
  }, [])

  const handleFiles = async (files: FileList | null, kind: 'image' | 'file') => {
    if (!files || files.length === 0) return
    const fileArr = Array.from(files)
    const picked = fileArr.map((f) => ({
      id: `${f.name}-${f.size}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      name: f.name,
      size: f.size,
      kind,
    }))
    setAttached((prev) => [...prev, ...picked])
    setPlusOpen(false)

    // Upload files to backend (returns instantly, processing happens in background)
    const convId = ensureActive()
    setUploading(true)
    try {
      const res = await uploadApi.upload(convId, fileArr)
      const uploadedFiles = res.data?.files || []

      // Track filenames that were successfully accepted by the backend. We
      // ship this list with the *next* user turn so the LLM knows which
      // file(s) the question is about.
      const acceptedNames: string[] = uploadedFiles
        .filter((f: any) => f.status === 'uploaded' || f.status === 'processing')
        .map((f: any) => f.filename)
      if (acceptedNames.length > 0) {
        setPendingFiles((prev) => Array.from(new Set([...prev, ...acceptedNames])))
      }

      // Check if any file needs processing (PDF, spreadsheet)
      const needsProcessing = uploadedFiles.some(
        (f: any) => f.status === 'processing'
      )
      const isImage = uploadedFiles.every((f: any) => f.status === 'uploaded')

      if (isImage) {
        // Images don't need processing — inject context immediately
        const names = fileArr.map((f) => `🖼️ ${f.name}`).join('\n')
        appendMessage(convId, {
          role: 'assistant',
          content: `**Files uploaded:**\n${names}\n\n_You can now ask me about these images._`,
        })
        setChatHasFiles(true)
        setUploading(false)
        return
      }

      if (needsProcessing) {
        // Poll for background processing completion
        let contextInjected = false
        const pollInterval = setInterval(async () => {
          try {
            const statusRes = await uploadApi.status(convId)
            if (statusRes.data?.all_done && !contextInjected) {
              contextInjected = true
              clearInterval(pollInterval)
              setChatHasFiles(true)
              setUploading(false)

              // Build context message from processing results
              const fileStatuses = statusRes.data.files || {}
              let contextMsg = '**Files processed & ready:**\n'
              for (const [fname, info] of Object.entries(fileStatuses) as any) {
                if (info.status === 'done' && info.summary) {
                  contextMsg += `\n${info.summary}\n`
                } else if (info.status === 'done') {
                  contextMsg += `\n✅ ${fname} — ready\n`
                } else if (info.status === 'error') {
                  contextMsg += `\n⚠️ ${fname} — processing failed: ${info.error}\n`
                }
              }
              contextMsg += '\n_Ask me anything about your uploaded files._'
              appendMessage(convId, { role: 'assistant', content: contextMsg })
            }
          } catch {
            clearInterval(pollInterval)
            setUploading(false)
          }
        }, 1500)

        // Safety timeout: stop polling after 120s
        setTimeout(() => {
          clearInterval(pollInterval)
          setChatHasFiles(true)
          setUploading(false)
        }, 120_000)
      } else {
        setChatHasFiles(true)
        setUploading(false)
      }
    } catch (err) {
      console.error('Upload failed:', err)
      setUploading(false)
    }
  }

  const removeAttached = (id: string) => {
    setAttached((prev) => prev.filter((a) => a.id !== id))
  }

  // Load persisted conversations from backend on first mount only.
  // Re-mounts (e.g. navigating away and back) skip the network call.
  useEffect(() => {
    const { loadFromApi, loaded } = useChatStore.getState()
    if (!loaded) {
      void loadFromApi()
    }
  }, [])

  // ── URL ↔ activeId sync ─────────────────────────────────────────
  //
  // The URL is the source of truth. Resolution order on every URL change:
  //   1. /chat/:id where :id exists in conversations → setActive(id)
  //   2. /chat/:id where :id is unknown → wait for load, then redirect
  //      to most-recent conv (or create new if user has none).
  //   3. /chat (no id) → resolve activeId via ensureActive(), then
  //      replace URL with /chat/<id> so back/forward works.
  //
  // Dep array is intentionally MINIMAL. We only re-run when the URL or
  // the load flag changes — NOT when conversations or activeId change.
  // Including those would cause the effect to fire on every token during
  // streaming (since each token mutates conversations), wasting work and
  // causing potential render churn. Current store values are read fresh
  // inside the effect via useChatStore.getState().
  useEffect(() => {
    if (!loaded) return
    const state = useChatStore.getState()

    if (urlId) {
      // Known conv → make it active
      if (state.conversations[urlId]) {
        if (state.activeId !== urlId) state.setActive(urlId)
        return
      }
      // Unknown id → fall through to auto-resolve below
    }

    // No id (or unknown id) → pick the right conv and update URL
    const resolvedId = state.ensureActive()
    if (resolvedId !== urlId) {
      navigate(`/chat/${resolvedId}`, { replace: true })
    }
  }, [loaded, urlId, navigate])

  // When the active conversation changes, reset per-chat upload state and
  // re-derive `chatHasFiles` from the backend for the new chat. Also fetch
  // full messages on-demand if the conversation metadata has an empty messages
  // array (lazy loading optimization).
  useEffect(() => {
    if (!activeId) return
    setPendingFiles([])
    setAttached([])
    setChatHasFiles(false)
    let cancelled = false

    // On-demand message loading: if the conversation exists but has no
    // messages loaded (metadata-only from the list endpoint), fetch the
    // full conversation detail in the background.
    const conv = useChatStore.getState().conversations[activeId]
    if (conv && conv.messages.length === 0) {
      chatApi.history
        .get(activeId)
        .then((res) => {
          if (cancelled) return
          const fullConv = res.data
          if (fullConv?.messages?.length > 0) {
            const { conversations } = useChatStore.getState()
            const existing = conversations[activeId]
            if (existing && existing.messages.length === 0) {
              // Hydrate the store with the fetched messages
              useChatStore.setState({
                conversations: {
                  ...useChatStore.getState().conversations,
                  [activeId]: {
                    ...existing,
                    messages: fullConv.messages.map((m: any) => ({
                      id: m.id || `${m.role}-${m.createdAt || Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
                      role: m.role,
                      content: m.content,
                      createdAt: m.createdAt || Date.now(),
                    })),
                  },
                },
              })
            }
          }
        })
        .catch(() => { /* silent — messages will load when user sends */ })
    }

    uploadApi
      .listFiles(activeId)
      .then((res) => {
        if (cancelled) return
        const files = res.data?.files || []
        if (files.length > 0) setChatHasFiles(true)
      })
      .catch(() => { /* ignore — treat as no files */ })
    return () => {
      cancelled = true
    }
  }, [activeId])

  const active = useMemo(
    () => (activeId ? conversations[activeId] : undefined),
    [activeId, conversations]
  )
  const messages: ChatMessage[] = active?.messages ?? []

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length])

  // Auto-resize textarea
  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }, [input])

  // Focus textarea when switching to a new/empty conversation
  useEffect(() => {
    if (activeId && messages.length === 0) {
      // Small delay to ensure DOM is ready after navigation
      const timer = setTimeout(() => {
        taRef.current?.focus()
      }, 50)
      return () => clearTimeout(timer)
    }
  }, [activeId, messages.length])

  const handleStop = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setSending(false)
  }

  const IN_DEPTH_SUFFIX =
    '\n\n---\nProvide a much more comprehensive, detailed, and in-depth answer. Include specific examples, edge cases, implementation details, and best practices where applicable. Expand on every point thoroughly.'

  const handleRetry = (query: string) => {
    setInput(query)
    setTimeout(() => {
      const el = taRef.current
      if (!el) return
      el.focus()
      const len = query.length
      el.setSelectionRange(len, len)
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 200) + 'px'
    }, 0)
  }
  const handleInDepth = (query: string) => handleSend(query + IN_DEPTH_SUFFIX)

  const toggleRecording = useCallback(async () => {
    if (recording) {
      mediaRecorderRef.current?.stop()
      setRecording(false)
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' })
      const chunks: Blob[] = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }
      recorder.onstop = async () => {
        const blob = new Blob(chunks, { type: 'audio/webm' })
        stream.getTracks().forEach((t) => t.stop())
        try {
          setTranscribing(true)
          const res = await transcribeApi.transcribe(blob)
          const text = res.data?.transcript?.trim()
          if (text) {
            setInput((prev) => (prev ? prev + ' ' + text : text))
          }
        } catch (err) {
          console.error('Transcription failed:', err)
        } finally {
          setTranscribing(false)
        }
      }
      mediaRecorderRef.current = recorder
      chunksRef.current = chunks
      recorder.start()
      setRecording(true)
    } catch (err) {
      console.error('Mic access denied or error:', err)
    }
  }, [recording])

  const handleSend = async (overrideQuery?: string) => {
    const query = (overrideQuery ?? input).trim()
    if (!query || sending) return
    // If activeId is missing (URL has no id and ensureActive hasn't run yet),
    // create a fresh conv. Otherwise reuse the resolved active id.
    const convId =
      (activeId && conversations[activeId]) ? activeId : createConversation()
    // Keep the URL in sync with the conversation we're about to send to.
    if (urlId !== convId) {
      navigate(`/chat/${convId}`, { replace: true })
    }
    // Snapshot the conversation BEFORE appending the new user message so
    // we can ship prior turns to the backend as multi-turn context. Filter
    // out empty assistant placeholders left behind by aborted streams.
    const prevMessages = useChatStore.getState().conversations[convId]?.messages ?? []
    const isFirstMessage = prevMessages.length === 0
    const historyForBackend = prevMessages
      .filter((m) => (m.content ?? '').trim().length > 0)
      .map((m) => ({ role: m.role, content: m.content }))

    // Snapshot & clear the per-turn file list before the await so a
    // concurrent upload after this point starts a fresh batch.
    const turnFiles = overrideQuery ? [] : pendingFiles
    if (!overrideQuery) {
      setPendingFiles([])
      setInput('')  // This also clears sessionStorage
      setAttached([])
    }
    setSending(true)

    // Mention the freshly-attached files in the user's visible message so
    // the turn is self-explanatory in the chat history. The backend now
    // also receives the prior turns as `history` (see chatApi.stream call).
    const displayQuery =
      turnFiles.length > 0
        ? `${query}\n\n_Attached this turn: ${turnFiles.join(', ')}_`
        : query
    appendMessage(convId, { role: 'user', content: displayQuery })
    // Pick the most-specific status track. Research wins over plain search
    // because deep research takes the most time and benefits most from a
    // descriptive progress indicator.
    setStreamingMode(
      uploading ? 'uploading' : research ? 'research' : webSearch ? 'search' : 'thinking',
    )
    setPhaseMessage(null)  // clear any stale phase from the previous turn
    const placeholder = appendMessage(convId, {
      role: 'assistant',
      content: '',
    })

    // Non-blocking: ask the LLM for a short title for new conversations.
    // The store already set a truncated title on first-append; this replaces it.
    if (isFirstMessage) {
      generateTitle(query)
        .then((title) => { if (title) renameConversation(convId, title) })
        .catch(() => { /* keep the auto-derived fallback */ })
    }

    // Route to the multimodal pipeline whenever the chat has files OR the
    // user just attached files this turn (covers the race where a PDF is
    // still being processed when the user hits send).
    if (chatHasFiles || turnFiles.length > 0) {
      // Abort any previous in-flight stream before starting a new one.
      if (abortRef.current) {
        abortRef.current.abort()
      }
      const controller = new AbortController()
      abortRef.current = controller
      let fullText = ''
      try {
        const reader = await multimodalApi.stream(query, convId, mode, 0.2, turnFiles, controller.signal)
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          if (controller.signal.aborted) break
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed.startsWith('data: ')) continue
            const payload = trimmed.slice(6).trim()
            if (!payload || payload === '[DONE]') continue

            try {
              const event = JSON.parse(payload)
              if (event.event === 'delta' && event.delta) {
                fullText += event.delta
                updateMessage(convId, placeholder.id, { content: fullText })
              }
              if (event.event === 'error') {
                updateMessage(convId, placeholder.id, { content: `⚠ ${event.message}` })
              }
              if (event.event === 'done') {
                // Append any structured metadata from the final event
                let extra = ''
                if (event.citations && event.citations.length > 0) {
                  extra += '\n\n---\n📄 **Sources:**\n'
                  event.citations.forEach((c: any) => {
                    extra += `- [${c.ref}] ${c.source || 'Document'}, Page ${c.page || '?'} (relevance: ${((c.score || 0) * 100).toFixed(0)}%)\n`
                  })
                }
                if (event.chart && event.chart.type !== 'none') {
                  extra += `\n\n📊 **Chart:** ${event.chart.title || ''} (${event.chart.type})\n`
                }
                if (event.analytics_result?.sql) {
                  extra += `\n\n\`\`\`sql\n${event.analytics_result.sql}\n\`\`\`\n`
                  const rows = event.analytics_result.rows
                  if (rows && rows.length > 0) {
                    const cols = event.analytics_result.columns || Object.keys(rows[0])
                    extra += '\n| ' + cols.join(' | ') + ' |\n'
                    extra += '| ' + cols.map(() => '---').join(' | ') + ' |\n'
                    rows.slice(0, 20).forEach((row: any) => {
                      extra += '| ' + cols.map((c: string) => String(row[c] ?? '')).join(' | ') + ' |\n'
                    })
                    if (event.analytics_result.row_count && event.analytics_result.row_count > 20) {
                      extra += `\n*...and ${event.analytics_result.row_count - 20} more rows*\n`
                    }
                  }
                }
                updateMessage(convId, placeholder.id, { content: fullText + extra })
              }
            } catch {
              // ignore malformed JSON
            }
          }
        }
      } catch (err: any) {
        if (err.name === 'AbortError') {
          updateMessage(convId, placeholder.id, { content: fullText || '⛔ Stopped by user.' })
        } else {
          const msg = err.message || 'Multimodal pipeline error'
          updateMessage(convId, placeholder.id, { content: `⚠ ${msg}` })
        }
      } finally {
        abortRef.current = null
        setSending(false)
      }
      return
    }

    // ── Streaming response (standard text pipeline) ──
    //
    // Before starting a new stream, abort any previous in-flight one.
    // Without this, switching conversations mid-stream would leave the
    // old stream running in the background, queueing rAF/setTimeout
    // callbacks that fire AFTER the new stream starts.
    if (abortRef.current) {
      abortRef.current.abort()
    }
    const controller = new AbortController()
    abortRef.current = controller
    // Timing instrumentation — visible in browser console.
    // Helps diagnose where latency lives (request init / TTFB / rendering).
    const t0 = performance.now()
    console.log('[chat] send:start', { convId, query: query.slice(0, 40) })
    let fullText = ''
    // Throttle streaming updates for smoother UI (max ~60fps).
    let pendingText = ''
    let updateQueued = false
    const flushUpdate = () => {
      updateQueued = false
      // Hard guard: if the user cancelled or moved on, don't write
      // stale deltas into the message. Without this, a callback that
      // was queued JUST before abort fires later and overwrites the
      // "Stopped by user" message — or worse, writes into a placeholder
      // belonging to a different conversation.
      if (controller.signal.aborted) return
      // Always write if we have text — even when the done event already
      // set fullText, this guarantees the store reflects the final state.
      if (pendingText) {
        fullText = pendingText
        console.log('[chat] flushUpdate', { len: pendingText.length, preview: pendingText.slice(0, 60) })
        updateMessage(convId, placeholder.id, { content: fullText })
      }
    }
    const queueUpdate = (text: string) => {
      pendingText = text
      if (!updateQueued) {
        updateQueued = true
        requestAnimationFrame(() => {
          setTimeout(flushUpdate, 16) // ~60fps max
        })
      }
    }
    try {
      const reader = await chatApi.stream(
        query,
        mode,
        0.2,
        webSearch,
        research,
        controller.signal,
        historyForBackend,
      )
      console.log('[chat] reader:open', { ms: (performance.now() - t0).toFixed(0) })
      const decoder = new TextDecoder()
      let buffer = ''
      let firstEventLogged = false

      while (true) {
        if (controller.signal.aborted) break
        const { done, value } = await reader.read()
        if (done) break

        if (!firstEventLogged) {
          firstEventLogged = true
          console.log('[chat] first:byte', { ms: (performance.now() - t0).toFixed(0), bytes: value?.byteLength ?? 0 })
        }

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // keep incomplete line in buffer

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue
          const payload = trimmed.slice(6).trim()
          if (!payload || payload === '[DONE]') continue

          try {
            const event = JSON.parse(payload)
            if (event.event === 'delta' && event.delta) {
              pendingText += event.delta
              queueUpdate(pendingText)
            }
            if (event.event === 'phase') {
              setPhaseMessage(formatPhaseMessage(event))
            }
            if (event.event === 'error') {
              console.error('[chat] event:error', event.message)
              updateMessage(convId, placeholder.id, { content: `⚠ ${event.message}` })
            }
            if (event.event === 'done' && event.answer) {
              // Capture the final answer inside the loop — if the done
              // event lands in the same chunk as the last deltas it is
              // consumed here and never reaches the post-loop parser.
              fullText = event.answer
              updateMessage(convId, placeholder.id, { content: event.answer })
            }
          } catch (parseErr) {
            console.warn('[chat] parse:fail', { payload: payload.slice(0, 100), err: parseErr })
          }
        }
      }
      console.log('[chat] stream:end', { ms: (performance.now() - t0).toFixed(0), len: pendingText.length })

      // Flush any remaining buffer
      // Flush any pending updates before finalizing
      flushUpdate()
      if (!controller.signal.aborted && buffer.trim().startsWith('data: ')) {
        const payload = buffer.trim().slice(6).trim()
        try {
          const event = JSON.parse(payload)
          if (event.event === 'done' && event.answer) {
            updateMessage(convId, placeholder.id, { content: event.answer })
          }
        } catch {
          // ignore
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        updateMessage(convId, placeholder.id, { content: fullText || '⛔ Stopped by user.' })
      } else {
        const msg = err.message || 'Failed to get a response. Please try again.'
        updateMessage(convId, placeholder.id, { content: `⚠ ${msg}` })
      }
    } finally {
      abortRef.current = null
      setSending(false)
      setPhaseMessage(null)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Stream */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-5 sm:px-6 sm:py-8 space-y-6 sm:space-y-8">
          {/* Skeleton bubbles while chats are loading. We only show
              skeletons if the current active conv has no messages yet —
              otherwise the user is looking at a real conv and we don't
              want to overwrite it with placeholders. */}
          {!loaded && messages.length === 0 && (
            <div className="py-16 animate-fade-up space-y-6">
              <p
                className="text-[11px] uppercase tracking-[0.22em] mb-3"
                style={{ color: 'var(--text-subtle)' }}
              >
                — loading your chats
              </p>
              <SkeletonBubble role="user" widthPct={45} />
              <SkeletonBubble role="assistant" widthPct={78} lines={3} />
              <SkeletonBubble role="user" widthPct={32} />
              <SkeletonBubble role="assistant" widthPct={70} lines={2} />
            </div>
          )}

          {loaded && messages.length === 0 && (
            <div className="py-16 animate-fade-up">
              <p
                className="text-[11px] uppercase tracking-[0.22em] mb-3"
                style={{ color: 'var(--accent)' }}
              >
                — ask anything
              </p>
              <h1
                className="font-display text-[40px] sm:text-5xl md:text-6xl leading-[1.02] tracking-tight"
                style={{ color: 'var(--text)' }}
              >
                how can I <span className="mark">help</span> you,
                <br />
                today?
              </h1>
              <p
                className="mt-6 text-[13px] leading-relaxed max-w-md"
                style={{ color: 'var(--text-muted)' }}
              >
                Ask for code, explanations, research, or a spark of creative writing.
                Each conversation is saved to your account and synced across devices.
              </p>

              <div className="mt-10 grid grid-cols-1 md:grid-cols-2 gap-3">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => setInput(s)}
                    className="text-left p-4 rounded-xl transition-all duration-200 group"
                    style={{
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-muted)',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = 'var(--accent)'
                      e.currentTarget.style.color = 'var(--text)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = 'var(--border)'
                      e.currentTarget.style.color = 'var(--text-muted)'
                    }}
                  >
                    <div className="flex items-start gap-3">
                      <Sparkle size={14} style={{ color: 'var(--accent)' }} className="mt-0.5 shrink-0" />
                      <span className="text-[13px] leading-relaxed">{s}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, idx) => {
            const prev = messages[idx - 1]
            const userQuery = m.role === 'assistant' && prev?.role === 'user' ? prev.content : undefined
            const isLast = idx === messages.length - 1
            return (
              <MessageBubble
                key={m.id}
                message={m}
                sending={sending}
                isLast={isLast}
                userQuery={userQuery}
                streamingMode={streamingMode}
                phaseMessage={isLast ? phaseMessage : null}
                onRetry={handleRetry}
                onInDepth={handleInDepth}
              />
            )
          })}

          <div ref={scrollRef} />
        </div>
      </div>

      {/* Composer */}
      <div
        className="shrink-0 pt-2 pb-3 sm:pt-3 sm:pb-5"
        style={{ borderTop: '1px solid var(--border)', background: 'var(--bg)' }}
      >
        <div className="max-w-3xl mx-auto px-3 sm:px-6">
          <div className="composer-glass-dock rounded-2xl p-2.5 sm:p-3">
            {/* Attachment chips */}
            {attached.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {attached.map((a) => (
                  <div key={a.id} className="attachment-pill-card">
                    {a.kind === 'image'
                      ? <ImageSquare size={13} className="pill-icon" />
                      : <FileText size={13} className="pill-icon" />}
                    <span className="pill-name">{a.name}</span>
                    <span className="pill-size">
                      {formatBytes(a.size)}
                    </span>
                    {uploading && (
                      <Spinner className="animate-spin pill-icon" size={11} />
                    )}
                    <button
                      onClick={() => removeAttached(a.id)}
                      className="pill-close"
                      aria-label={`Remove ${a.name}`}
                    >
                      <X size={11} weight="bold" />
                    </button>
                  </div>
                ))}
                {uploading && (
                  <div className="flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--accent)' }}>
                    <Spinner className="animate-spin" size={12} />
                    <span>Processing & indexing…</span>
                  </div>
                )}
              </div>
            )}

            {/* Textarea — stays interactive during initial load. The
                user's draft persists in sessionStorage and the chatStore
                merges (rather than overwrites) so a message typed
                during load is preserved. */}
            <textarea
              ref={taRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder={loaded ? 'Message snti…' : 'Message snti… (loading your chats)'}
              rows={1}
              disabled={sending}
              className="w-full px-1 py-1 bg-transparent outline-none resize-none text-[14px] leading-relaxed"
              style={{ color: 'var(--text)' }}
            />

            {/* Toolbar: + / Web / Research / Send */}
            <div className="flex items-center gap-1 sm:gap-1.5 mt-2 flex-wrap">
              {/* "+" attachment menu */}
              <div className="relative" ref={plusRef}>
                <ToolButton
                  active={plusOpen}
                  onClick={() => setPlusOpen((v) => !v)}
                  aria-label="Attach"
                  title="Attach files or images"
                >
                  <Plus size={15} weight="bold" />
                </ToolButton>
                {plusOpen && (
                  <div
                    className="absolute bottom-full left-0 mb-2 z-20 min-w-[200px] rounded-xl p-1 shadow-xl"
                    style={{
                      background: 'var(--bg-elevated)',
                      border: '1px solid var(--border-strong)',
                    }}
                  >
                    <PlusMenuItem
                      icon={<ImageSquare size={14} />}
                      label="Upload image"
                      hint="png · jpg · webp"
                      onClick={() => {
                        imageInputRef.current?.click()
                        setPlusOpen(false)
                      }}
                    />
                    <PlusMenuItem
                      icon={<FileText size={14} />}
                      label="Upload file"
                      hint="pdf · txt · md · csv"
                      onClick={() => {
                        fileInputRef.current?.click()
                        setPlusOpen(false)
                      }}
                    />
                    <div className="rule my-1" />
                    <PlusMenuItem
                      icon={<Paperclip size={14} />}
                      label="From URL"
                      hint="coming soon"
                      disabled
                    />

                    {/* Mobile-only: surface Web search & Research here
                        because the toolbar can't fit them on small
                        screens. Each item shows a checkmark when active
                        so the user can see the toggle state at a glance. */}
                    <div className="md:hidden">
                      <div className="rule my-1" />
                      <PlusMenuItem
                        icon={<Globe size={14} />}
                        label="Web search"
                        hint={webSearch ? 'on' : 'off'}
                        active={webSearch}
                        onClick={() => setWebSearch((v) => !v)}
                      />
                      <PlusMenuItem
                        icon={<Flask size={14} />}
                        label="Deep research"
                        hint={
                          deepResearchRemaining !== null
                            ? `${research ? 'on' : 'off'} · ${deepResearchRemaining} left`
                            : research ? 'on' : 'off'
                        }
                        active={research}
                        onClick={() => setResearch((v) => !v)}
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Desktop-only standalone toggles. On mobile these live
                  inside the plus menu (above) to save horizontal space. */}
              <div className="hidden md:flex items-center gap-1.5">
                <ToolButton
                  active={webSearch}
                  onClick={() => setWebSearch((v) => !v)}
                  aria-label="Toggle web search"
                  title="Search the web for up-to-date info"
                >
                  <Globe size={13} weight={webSearch ? 'fill' : 'regular'} />
                  <span>Web search</span>
                </ToolButton>

                <ToolButton
                  active={research}
                  onClick={() => setResearch((v) => !v)}
                  aria-label="Toggle research mode"
                  title="Deeper, multi-step research"
                >
                  <Flask size={13} weight={research ? 'fill' : 'regular'} />
                  <span>Research</span>
                  {deepResearchRemaining !== null && (
                    <span
                      className="ml-1 px-1 rounded text-[10px] font-bold"
                      style={{
                        background: deepResearchRemaining > 0 ? 'var(--accent)' : 'var(--border-strong)',
                        color: deepResearchRemaining > 0 ? 'var(--bg)' : 'var(--text-muted)',
                      }}
                    >
                      {deepResearchRemaining}
                    </span>
                  )}
                </ToolButton>
              </div>

              <div className="flex-1" />

              {/* Mode selector: Fast / Think */}
              <div
                role="tablist"
                aria-label="Response mode"
                className="flex items-center rounded-lg p-[2px]"
                style={{
                  background: 'var(--bg-sunken)',
                  border: '1px solid var(--border-strong)',
                }}
              >
                {(['Fast', 'Think'] as const).map((m) => {
                  const active = mode === m
                  return (
                    <button
                      key={m}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      onClick={() => setMode(m)}
                      title={m === 'Fast' ? 'Quick answers, low latency' : 'Stronger reasoning, higher quality'}
                      className="px-2.5 py-1 rounded-md text-[12px] transition-colors"
                      style={{
                        background: active ? 'var(--accent)' : 'transparent',
                        color: active ? 'var(--bg)' : 'var(--text-muted)',
                        fontWeight: active ? 600 : 400,
                      }}
                    >
                      {m.toLowerCase()}
                    </button>
                  )
                })}
              </div>

              {/* Mic / Transcribe */}
              {transcribing ? (
                <button
                  className="btn-primary !px-3 !py-2"
                  style={{ background: 'var(--accent)' }}
                  disabled
                  aria-label="Transcribing"
                  title="Transcribing…"
                >
                  <Spinner className="animate-spin" size={14} />
                </button>
              ) : (
                <button
                  onClick={toggleRecording}
                  className="btn-primary !px-3 !py-2"
                  style={{
                    background: recording ? 'var(--danger)' : 'var(--bg-sunken)',
                    color: recording ? '#fff' : 'var(--text-muted)',
                  }}
                  aria-label={recording ? 'Stop recording' : 'Start voice input'}
                  title={recording ? 'Stop recording' : 'Start voice input'}
                >
                  {recording ? (
                    <span className="flex items-end gap-[2px] h-[14px]">
                      <span className="w-[2px] rounded-full bg-white animate-wave1" style={{ height: '60%' }} />
                      <span className="w-[2px] rounded-full bg-white animate-wave2" style={{ height: '100%' }} />
                      <span className="w-[2px] rounded-full bg-white animate-wave3" style={{ height: '80%' }} />
                    </span>
                  ) : (
                    <Microphone size={14} weight="regular" />
                  )}
                </button>
              )}

              {sending ? (
                <button
                  onClick={handleStop}
                  className="btn-primary !px-3 !py-2"
                  style={{ background: 'var(--danger)' }}
                  aria-label="Stop generation"
                  title="Stop generation"
                >
                  <Stop size={14} weight="fill" />
                </button>
              ) : (
                <button
                  onClick={() => handleSend()}
                  disabled={!input.trim()}
                  className="btn-primary !px-3 !py-2"
                  aria-label="Send message"
                >
                  <PaperPlaneRight size={14} weight="fill" />
                </button>
              )}
            </div>

            {/* Hidden file inputs */}
            <input
              ref={imageInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                handleFiles(e.target.files, 'image')
                e.target.value = ''
              }}
            />
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.md,.csv,.json,.log,.xlsx,.xls,application/pdf,text/*,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              multiple
              className="hidden"
              onChange={(e) => {
                handleFiles(e.target.files, 'file')
                e.target.value = ''
              }}
            />
          </div>

          <p
            className="mt-2 text-center text-[10px] tracking-wide"
            style={{ color: 'var(--text-subtle)' }}
          >
            press Enter to send · Shift+Enter for newline
          </p>
        </div>
      </div>
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function ToolButton({
  active,
  onClick,
  children,
  title,
  'aria-label': ariaLabel,
}: {
  active?: boolean
  onClick: () => void
  children: React.ReactNode
  title?: string
  'aria-label'?: string
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={ariaLabel}
      aria-pressed={!!active}
      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[12px] transition-colors"
      style={{
        background: active ? 'var(--accent-soft)' : 'transparent',
        color: active ? 'var(--accent)' : 'var(--text-muted)',
        border: `1px solid ${active ? 'var(--accent-ring)' : 'var(--border-strong)'}`,
      }}
      onMouseEnter={(e) => {
        if (active) return
        e.currentTarget.style.color = 'var(--text)'
        e.currentTarget.style.borderColor = 'var(--accent-ring)'
      }}
      onMouseLeave={(e) => {
        if (active) return
        e.currentTarget.style.color = 'var(--text-muted)'
        e.currentTarget.style.borderColor = 'var(--border-strong)'
      }}
    >
      {children}
    </button>
  )
}

function PlusMenuItem({
  icon,
  label,
  hint,
  onClick,
  disabled,
  active,
}: {
  icon: React.ReactNode
  label: string
  hint?: string
  onClick?: () => void
  disabled?: boolean
  /** When true, render the item as a "toggle on" state. Used by mobile
   *  Web-search / Research entries so users can see the toggle status. */
  active?: boolean
}) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      aria-pressed={active}
      className="flex items-center gap-2.5 w-full px-2.5 py-2 rounded-lg text-[13px] text-left transition-colors disabled:cursor-not-allowed"
      style={{
        color: disabled ? 'var(--text-subtle)' : active ? 'var(--accent)' : 'var(--text)',
        background: active ? 'var(--accent-soft)' : 'transparent',
        opacity: disabled ? 0.55 : 1,
      }}
      onMouseEnter={(e) => {
        if (disabled || active) return
        e.currentTarget.style.background = 'var(--accent-soft)'
      }}
      onMouseLeave={(e) => {
        if (active) return
        e.currentTarget.style.background = 'transparent'
      }}
    >
      <span style={{ color: disabled ? 'var(--text-subtle)' : 'var(--accent)' }}>{icon}</span>
      <span className="flex-1">{label}</span>
      {hint && (
        <span className="text-[10px] uppercase tracking-[0.18em]" style={{ color: active ? 'var(--accent)' : 'var(--text-subtle)' }}>
          {hint}
        </span>
      )}
    </button>
  )
}

import MermaidRenderer from '../components/MermaidRenderer'

function PreWithCopy({ children, ...props }: any) {
  const preRef = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    const text = preRef.current?.innerText || ''
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore
    }
  }

  // Intercept and render Mermaid blocks visually
  const codeChild = React.Children.toArray(children).find(
    (child: any) => child && child.type === 'code'
  ) as any

  if (codeChild && codeChild.props) {
    const className = codeChild.props.className || ''
    const codeContent = React.Children.toArray(codeChild.props.children).join('').trim()
    const isMermaid = 
      className.includes('language-mermaid') || 
      className.includes('mermaid') ||
      codeContent.startsWith('flowchart ') ||
      codeContent.startsWith('graph ') ||
      codeContent.startsWith('sequenceDiagram') ||
      codeContent.startsWith('stateDiagram') ||
      codeContent.startsWith('classDiagram')

    if (isMermaid) {
      return (
        <div className="my-4 w-full">
          <MermaidRenderer code={codeContent} inline={true} />
        </div>
      )
    }
  }

  return (
    <div className="relative group my-3 overflow-x-auto max-w-full">
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 z-10 flex items-center gap-1 px-2 py-1 rounded text-[11px] opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          color: 'var(--text-muted)',
        }}
      >
        <Copy size={12} />
        {copied ? 'Copied!' : 'Copy'}
      </button>
      <pre ref={preRef} {...props} className={`overflow-x-auto ${props.className || ''}`}>
        {children}
      </pre>
    </div>
  )
}

// Translate a backend phase event into a single human-readable status string.
// Kept here (rather than in api.ts) because phase rendering is purely a chat
// UI concern — the backend just emits the structured event.
function formatPhaseMessage(e: { phase: string; count?: number; subs?: number }): string | null {
  switch (e.phase) {
    case 'thinking':
      return 'thinking'
    case 'searching':
      return 'searching the web'
    case 'researching':
      return 'researching across sources'
    case 'sources': {
      const c = e.count ?? 0
      if (c <= 0) return 'searching the web'
      return `found ${c} ${c === 1 ? 'source' : 'sources'}`
    }
    case 'research_sources': {
      const c = e.count ?? 0
      const s = e.subs ?? 0
      if (c > 0 && s > 0) return `synthesizing ${c} sources across ${s} angles`
      if (c > 0) return `synthesizing ${c} sources`
      return 'synthesizing the answer'
    }
    case 'writing':
      return 'writing your answer'
    default:
      return null
  }
}

// Mode-specific status tracks shown while the assistant is preparing its first
// streamed delta. Messages cycle in order; each character types in to match
// the chat's quiet, editorial feel — the same theme as the original
// "thinking…" indicator, just with more granularity. Used as a fallback when
// no live phase event has arrived yet.
const STATUS_TRACKS: Record<'thinking' | 'search' | 'research' | 'uploading', string[]> = {
  thinking: ['thinking'],
  search: [
    'understanding your question',
    'searching the web',
    'reading the top sources',
    'connecting the dots',
  ],
  research: [
    'breaking the question apart',
    'searching across sources',
    'extracting key facts',
    'cross-checking findings',
    'synthesizing the answer',
  ],
  uploading: [
    'processing your files',
    'extracting the text',
    'indexing for retrieval',
  ],
}

function TypewriterStatus({
  mode,
  overrideMessage,
}: {
  mode: 'thinking' | 'search' | 'research' | 'uploading'
  overrideMessage?: string | null
}) {
  // When the backend pushes a live phase, render that single message and stop
  // cycling defaults. Each new override message retypes from char 0 so the
  // typewriter effect repeats and feels alive on every transition.
  const messages = useMemo(
    () => (overrideMessage ? [overrideMessage] : STATUS_TRACKS[mode] ?? STATUS_TRACKS.thinking),
    [overrideMessage, mode],
  )
  const [msgIdx, setMsgIdx] = useState(0)
  const [charIdx, setCharIdx] = useState(0)

  // Reset typing position whenever the message set changes (mode swap or new
  // override arriving).
  useEffect(() => {
    setMsgIdx(0)
    setCharIdx(0)
  }, [messages])

  useEffect(() => {
    const target = messages[msgIdx] ?? ''
    if (charIdx < target.length) {
      const t = setTimeout(() => setCharIdx((c) => c + 1), 32)
      return () => clearTimeout(t)
    }
    // Single-message tracks just hold; multi-message tracks advance after a beat.
    if (messages.length <= 1) return
    const hold = setTimeout(() => {
      setCharIdx(0)
      setMsgIdx((i) => (i + 1) % messages.length)
    }, 1100)
    return () => clearTimeout(hold)
  }, [msgIdx, charIdx, messages])

  const current = messages[msgIdx] ?? ''
  return (
    <span className="text-[13px] italic">
      {current.slice(0, charIdx)}
      <span aria-hidden>…</span>
    </span>
  )
}

function SkeletonBubble({
  role,
  widthPct,
  lines = 1,
}: {
  role: 'user' | 'assistant'
  widthPct: number
  lines?: number
}) {
  const isUser = role === 'user'
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div
        className="w-7 h-7 rounded-md shrink-0 animate-pulse"
        style={{
          background: isUser ? 'var(--bg-card)' : 'var(--accent-soft)',
          border: '1px solid var(--border)',
          opacity: 0.6,
        }}
      />
      <div className={`flex flex-col min-w-0 pt-0.5 ${isUser ? 'max-w-[50%] items-end' : 'max-w-[95%] items-start'}`}>
        <div
          className="h-2 rounded mb-2 animate-pulse"
          style={{ background: 'var(--border-strong)', width: '40px', opacity: 0.5 }}
        />
        <div
          className={`rounded-2xl ${isUser ? 'rounded-tr-sm' : 'rounded-tl-sm'} px-4 py-3 animate-pulse`}
          style={{
            background: isUser ? 'var(--accent-soft)' : 'var(--bg-card)',
            border: '1px solid var(--border)',
            width: `${widthPct}%`,
            minWidth: '120px',
            opacity: 0.6,
          }}
        >
          <div className="space-y-1.5">
            {Array.from({ length: lines }).map((_, i) => (
              <div
                key={i}
                className="h-2 rounded"
                style={{
                  background: 'var(--border-strong)',
                  width: i === lines - 1 ? '60%' : '95%',
                  opacity: 0.5,
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

const MessageBubble = React.memo(function MessageBubble({
  message,
  sending,
  isLast,
  userQuery,
  streamingMode,
  phaseMessage,
  onRetry,
  onInDepth,
}: {
  message: ChatMessage
  sending: boolean
  isLast: boolean
  userQuery?: string
  streamingMode?: 'thinking' | 'search' | 'research' | 'uploading'
  phaseMessage?: string | null
  onRetry?: (q: string) => void
  onInDepth?: (q: string) => void
}) {
  const isUser = message.role === 'user'
  const isEmpty = !message.content && !isUser
  const isStreaming = isLast && sending
  const [msgCopied, setMsgCopied] = useState(false)

  const handleCopyMessage = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setMsgCopied(true)
      setTimeout(() => setMsgCopied(false), 2000)
    } catch {
      // ignore
    }
  }

  const markdownComponents = useMemo(
    () => ({
      pre: PreWithCopy,
    }),
    [],
  )

  return (
    <div className={`flex gap-3 message-bubble-animate ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div
        className="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
        style={{
          background: isUser ? 'var(--bg-card)' : 'var(--accent-soft)',
          border: '1px solid var(--border)',
          color: isUser ? 'var(--text-muted)' : 'var(--accent)',
        }}
      >
        {isUser ? <User size={13} /> : <Sparkle size={13} weight="fill" />}
      </div>
      <div className={`flex flex-col min-w-0 pt-0.5 ${isUser ? 'max-w-[50%] items-end' : 'max-w-[95%] items-start'}`}>
        <div
          className="text-[10px] uppercase tracking-[0.2em] mb-1"
          style={{ color: 'var(--text-subtle)' }}
        >
          {isUser ? 'you' : 'snti'}
        </div>
        {isEmpty && sending ? (
          <div className="flex items-center gap-2" style={{ color: 'var(--text-subtle)' }}>
            <Spinner className="animate-spin" size={14} />
            <TypewriterStatus
              mode={(isLast ? streamingMode : 'thinking') ?? 'thinking'}
              overrideMessage={isLast ? phaseMessage : null}
            />
          </div>
        ) : isUser ? (
          <div
            className="rounded-2xl rounded-tr-sm px-4 py-2.5 text-[14px] leading-relaxed whitespace-pre-wrap overflow-hidden min-w-0"
            style={{
              background: 'var(--accent-soft)',
              border: '1px solid var(--border)',
              color: 'var(--text)',
            }}
          >
            {message.content}
          </div>
        ) : isStreaming ? (
          // During streaming render raw plain text — ReactMarkdown with
          // remark-gfm re-parses the full markdown AST on every token
          // update which is O(n²) work and can freeze the UI for long
          // conversations. We switch to markdown only after streaming
          // completes (sending becomes false).
          <div
            className="rounded-2xl rounded-tl-sm px-4 py-2.5 text-[14px] leading-relaxed whitespace-pre-wrap overflow-hidden min-w-0"
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              color: 'var(--text)',
            }}
          >
            {message.content}
          </div>
        ) : (
          <div
            className="rounded-2xl rounded-tl-sm px-4 py-2.5 overflow-hidden min-w-0"
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
            }}
          >
            <div className="prose dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {message.content}
              </ReactMarkdown>
            </div>
          </div>
        )}

        {/* Assistant message action bar */}
        {!isUser && !isEmpty && !isStreaming && (
          <div className="flex items-center gap-2 mt-2">
            <button
              onClick={handleCopyMessage}
              className="flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-colors cursor-pointer"
              style={{
                border: '1px solid var(--border)',
                color: 'var(--text-muted)',
                background: 'transparent',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'var(--bg-card)'
                e.currentTarget.style.color = 'var(--text)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent'
                e.currentTarget.style.color = 'var(--text-muted)'
              }}
            >
              <Copy size={12} />
              {msgCopied ? 'Copied!' : 'Copy'}
            </button>
            {userQuery && onRetry && (
              <button
                onClick={() => onRetry(userQuery)}
                disabled={sending}
                className="flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-colors cursor-pointer disabled:opacity-40"
                style={{
                  border: '1px solid var(--border)',
                  color: 'var(--text-muted)',
                  background: 'transparent',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--bg-card)'
                  e.currentTarget.style.color = 'var(--text)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent'
                  e.currentTarget.style.color = 'var(--text-muted)'
                }}
              >
                <ArrowCounterClockwise size={12} />
                Retry
              </button>
            )}
            {userQuery && onInDepth && (
              <button
                onClick={() => onInDepth(userQuery)}
                disabled={sending}
                className="flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-colors cursor-pointer disabled:opacity-40"
                style={{
                  border: '1px solid var(--border)',
                  color: 'var(--text-muted)',
                  background: 'transparent',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--bg-card)'
                  e.currentTarget.style.color = 'var(--text)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent'
                  e.currentTarget.style.color = 'var(--text-muted)'
                }}
              >
                <Article size={12} />
                In-depth
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
})
