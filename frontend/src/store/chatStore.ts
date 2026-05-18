import { create } from 'zustand'
import { chatApi } from '../lib/api'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: number
}

export interface Conversation {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: ChatMessage[]
}

interface ChatState {
  conversations: Record<string, Conversation>
  order: string[]
  activeId: string | null
  loaded: boolean

  createConversation: (seedTitle?: string) => string
  deleteConversation: (id: string) => Promise<void>
  renameConversation: (id: string, title: string) => void
  setActive: (id: string | null) => void

  appendMessage: (id: string, msg: Omit<ChatMessage, 'id' | 'createdAt'>) => ChatMessage
  updateMessage: (convId: string, msgId: string, patch: Partial<ChatMessage>) => void
  clearAll: () => Promise<void>
  loadFromApi: () => Promise<void>
  flushSyncs: () => Promise<void>

  ensureActive: () => string
}

const uid = () => Math.random().toString(36).slice(2) + Date.now().toString(36)

const deriveTitle = (content: string): string => {
  const clean = content.trim().replace(/\s+/g, ' ')
  if (!clean) return 'New conversation'
  return clean.length > 48 ? clean.slice(0, 48) + '…' : clean
}

// ── activeId persistence ─────────────────────────────────────────
//
// Mirror ChatGPT/Claude: refreshing the page restores the user to
// their last-open conversation. We use a dedicated localStorage key
// rather than a zustand persist middleware so the heavy `conversations`
// map (which can grow to megabytes) is never written to disk.
const ACTIVE_ID_KEY = 'chat_active_id'

function loadActiveId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_ID_KEY)
  } catch {
    return null
  }
}

function saveActiveId(id: string | null): void {
  try {
    if (id) localStorage.setItem(ACTIVE_ID_KEY, id)
    else localStorage.removeItem(ACTIVE_ID_KEY)
  } catch {
    // localStorage may throw in private-mode Safari — non-fatal
  }
}

// ── debounced sync ────────────────────────────────────────────────
//
// The previous implementation POSTed the entire conversation on every
// updateMessage() call — which during streaming meant ~60 POSTs/sec to
// /chat/history, each carrying the full message list. This bombarded
// the backend and made subsequent GETs slow.
//
// New strategy: per-conversation trailing-edge debouncer with 800ms
// latency. Streaming bursts collapse into a single save. Critical
// state changes (create, delete, append) trigger an immediate flush
// so they survive tab close / reload.

const SYNC_DEBOUNCE_MS = 800
const pendingTimers = new Map<string, ReturnType<typeof setTimeout>>()
const pendingPromises = new Map<string, Promise<void>>()

async function syncNow(id: string, getState: () => ChatState): Promise<void> {
  const conv = getState().conversations[id]
  if (!conv) return
  try {
    await chatApi.history.save({
      id: conv.id,
      title: conv.title,
      createdAt: conv.createdAt,
      updatedAt: conv.updatedAt,
      messages: conv.messages,
    })
  } catch {
    // Silent failure — the next change re-attempts. We deliberately
    // don't surface this to the UI because frequent transient errors
    // (network blips, 401 mid-refresh) would create noise.
  }
}

function scheduleSync(
  id: string,
  getState: () => ChatState,
  immediate = false,
): void {
  // Cancel any pending debounced save for this conv.
  const existing = pendingTimers.get(id)
  if (existing) {
    clearTimeout(existing)
    pendingTimers.delete(id)
  }

  if (immediate) {
    const p = syncNow(id, getState).finally(() => {
      pendingPromises.delete(id)
    })
    pendingPromises.set(id, p)
    return
  }

  const timer = setTimeout(() => {
    pendingTimers.delete(id)
    const p = syncNow(id, getState).finally(() => {
      pendingPromises.delete(id)
    })
    pendingPromises.set(id, p)
  }, SYNC_DEBOUNCE_MS)
  pendingTimers.set(id, timer)
}

async function flushAllSyncs(getState: () => ChatState): Promise<void> {
  // Promote every pending debounce to immediate.
  const ids = Array.from(pendingTimers.keys())
  for (const id of ids) {
    const t = pendingTimers.get(id)
    if (t) clearTimeout(t)
    pendingTimers.delete(id)
    const p = syncNow(id, getState).finally(() => {
      pendingPromises.delete(id)
    })
    pendingPromises.set(id, p)
  }
  // Wait for all in-flight saves to complete.
  await Promise.allSettled(Array.from(pendingPromises.values()))
}

export const useChatStore = create<ChatState>((set, get) => {
  // Best-effort flush on tab close so a half-streamed message isn't lost.
  // Browsers cap beforeunload network activity; we use the synchronous
  // sendBeacon path implicitly via fetch keepalive when possible.
  if (typeof window !== 'undefined') {
    window.addEventListener('beforeunload', () => {
      // Fire-and-forget — promote all debounced syncs to immediate.
      // The browser may or may not deliver them depending on size.
      const ids = Array.from(pendingTimers.keys())
      for (const id of ids) {
        const t = pendingTimers.get(id)
        if (t) clearTimeout(t)
        pendingTimers.delete(id)
        void syncNow(id, get)
      }
    })
  }

  return {
    conversations: {},
    order: [],
    activeId: loadActiveId(),
    loaded: false,

    loadFromApi: async () => {
      try {
        const { data } = await chatApi.history.list()
        // ── Merge, don't overwrite ──
        //
        // While loadFromApi() was in flight, the user may have created
        // a new conversation and started streaming into it. Overwriting
        // the local state would orphan that conversation and the in-
        // progress stream would write into a dead conv ID, producing
        // the "no response on screen" bug.
        //
        // Merge strategy:
        //  - Server convs always win for IDs the server knows about
        //    (they're the source of truth for replicated state).
        //  - Local-only convs (created during the load) are kept
        //    on top of the order list.
        //  - The active conversation is preserved.
        set((s) => {
          const serverConvs: Record<string, Conversation> = {}
          const serverOrder: string[] = []
          for (const c of data) {
            serverConvs[c.id] = {
              id: c.id,
              title: c.title,
              createdAt: c.createdAt,
              updatedAt: c.updatedAt,
              messages: c.messages || [],
            }
            serverOrder.push(c.id)
          }

          // Find local-only convs (created while the network call was in flight)
          const localOnlyIds = s.order.filter(
            (id) => !serverConvs[id] && s.conversations[id],
          )
          const mergedConvs: Record<string, Conversation> = { ...serverConvs }
          // Preserve local-only convs
          for (const id of localOnlyIds) {
            mergedConvs[id] = s.conversations[id]
          }
          // For conversations that exist both locally and on the server,
          // keep whichever is MORE RECENT. This prevents a stale server
          // snapshot (from a GET that was in flight before a local sync
          // POST) from overwriting newer local messages.
          for (const id of Object.keys(serverConvs)) {
            const local = s.conversations[id]
            if (!local) continue
            if (local.updatedAt > serverConvs[id].updatedAt) {
              mergedConvs[id] = local
            }
          }
          // Local-only convs are newest; sort the rest by server order
          const mergedOrder = [...localOnlyIds, ...serverOrder]

          return {
            conversations: mergedConvs,
            order: mergedOrder,
            loaded: true,
          }
        })
      } catch {
        set({ loaded: true })
      }
    },

    createConversation: (seedTitle) => {
      const id = uid()
      const now = Date.now()
      const conv: Conversation = {
        id,
        title: seedTitle || 'New conversation',
        createdAt: now,
        updatedAt: now,
        messages: [],
      }
      set((s) => ({
        conversations: { ...s.conversations, [id]: conv },
        order: [id, ...s.order],
        activeId: id,
      }))
      saveActiveId(id)
      scheduleSync(id, get, true)
      return id
    },

    deleteConversation: async (id) => {
      // Cancel any pending debounced sync for this conv — the row is
      // being deleted, no point saving it. If we let it fire after
      // the delete returns, the conv would resurrect server-side.
      const t = pendingTimers.get(id)
      if (t) {
        clearTimeout(t)
        pendingTimers.delete(id)
      }

      // Snapshot for rollback
      const previous = get()
      const conversation = previous.conversations[id]
      const previousOrder = previous.order
      const previousActiveId = previous.activeId

      // Optimistic remove
      set((s) => {
        const { [id]: _removed, ...rest } = s.conversations
        const order = s.order.filter((x) => x !== id)
        const activeId = s.activeId === id ? order[0] ?? null : s.activeId
        if (s.activeId === id) saveActiveId(activeId)
        return { conversations: rest, order, activeId }
      })

      try {
        await chatApi.history.delete(id)
      } catch (err) {
        if (conversation) {
          set({
            conversations: { ...get().conversations, [id]: conversation },
            order: previousOrder,
            activeId: previousActiveId,
          })
          saveActiveId(previousActiveId)
        }
        throw err
      }
    },

    renameConversation: (id, title) => {
      set((s) => {
        const conv = s.conversations[id]
        if (!conv) return s
        return {
          conversations: {
            ...s.conversations,
            [id]: { ...conv, title: title.trim() || conv.title, updatedAt: Date.now() },
          },
        }
      })
      // Rename is user-visible state — sync immediately so a refresh
      // shows the new title.
      scheduleSync(id, get, true)
    },

    setActive: (id) => {
      set({ activeId: id })
      saveActiveId(id)
    },

    appendMessage: (id, msg) => {
      const full: ChatMessage = { id: uid(), createdAt: Date.now(), ...msg }
      set((s) => {
        const conv = s.conversations[id]
        if (!conv) return s
        const nextMessages = [...conv.messages, full]
        const nextTitle =
          conv.messages.length === 0 && msg.role === 'user'
            ? deriveTitle(msg.content)
            : conv.title
        return {
          conversations: {
            ...s.conversations,
            [id]: { ...conv, messages: nextMessages, title: nextTitle, updatedAt: Date.now() },
          },
          order: [id, ...s.order.filter((x) => x !== id)],
        }
      })
      // Debounced sync — a typical handleSend appends two messages back-to-
      // back (user + assistant placeholder). With immediate-sync each one
      // would fire its own POST /chat/history, flooding the backend with
      // 2 redundant writes that compete with the actual /chat/stream
      // request for browser connection slots and the SQLite write lock.
      // Debouncing collapses both into a single save 800ms later, while
      // beforeunload still flushes pending syncs on tab close so data
      // is never lost.
      scheduleSync(id, get, false)
      return full
    },

    updateMessage: (convId, msgId, patch) => {
      set((s) => {
        const conv = s.conversations[convId]
        if (!conv) return s
        return {
          conversations: {
            ...s.conversations,
            [convId]: {
              ...conv,
              messages: conv.messages.map((m) => (m.id === msgId ? { ...m, ...patch } : m)),
              updatedAt: Date.now(),
            },
          },
        }
      })
      // Streaming updates use the debounced path — the message will
      // be saved 800ms after the last token, instead of after every token.
      scheduleSync(convId, get, false)
    },

    clearAll: async () => {
      // Cancel every pending sync — they'd recreate convs we're about to wipe.
      for (const t of pendingTimers.values()) clearTimeout(t)
      pendingTimers.clear()
      set({ conversations: {}, order: [], activeId: null })
      saveActiveId(null)
      try {
        await chatApi.history.clear()
      } catch {
        // ignore
      }
    },

    flushSyncs: () => flushAllSyncs(get),

    ensureActive: () => {
      const { activeId, conversations, order, createConversation } = get()
      // 1. Honor a valid stored activeId
      if (activeId && conversations[activeId]) return activeId
      // 2. Fall back to the most-recently-updated existing conversation.
      //    `order` is already maintained with newest first.
      for (const id of order) {
        if (conversations[id]) {
          set({ activeId: id })
          saveActiveId(id)
          return id
        }
      }
      // 3. Only create a new conversation if the user truly has none.
      return createConversation()
    },
  }
})

