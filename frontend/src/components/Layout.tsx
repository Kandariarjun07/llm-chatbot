import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useChatStore } from '../store/chatStore'
import {
  ChatTeardropText,
  ImageSquare,
  Gear,
  SignOut,
  List,
  X,
  UserCircle,
  Plus,
  TrashSimple,
  DotsThreeVertical,
  PencilSimple,
  Table,
  ChartPieSlice,
} from '@phosphor-icons/react'
import { useState, useMemo, useRef, useEffect } from 'react'
import ThemeToggle from './ThemeToggle'

const navItems = [
  { to: '/chat', icon: ChatTeardropText, label: 'Chat' },
  { to: '/images', icon: ImageSquare, label: 'Images' },
  { to: '/sheets', icon: Table, label: 'Sheets' },
  { to: '/usage', icon: ChartPieSlice, label: 'Usage' },
  { to: '/settings', icon: Gear, label: 'Settings' },
]

function formatRelative(ts: number): string {
  const d = Math.floor((Date.now() - ts) / 1000)
  if (d < 60) return 'just now'
  if (d < 3600) return `${Math.floor(d / 60)}m`
  if (d < 86400) return `${Math.floor(d / 3600)}h`
  if (d < 604800) return `${Math.floor(d / 86400)}d`
  return new Date(ts).toLocaleDateString()
}

function ConversationRow({
  title,
  updatedAt,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  title: string
  updatedAt: number
  active: boolean
  onSelect: () => void
  onRename: (next: string) => void
  onDelete: () => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(title)
  const rowRef = useRef<HTMLDivElement>(null)

  const commit = () => {
    onRename(draft)
    setEditing(false)
  }

  // Close menu on outside click / Escape — keeps it open while cursor is on the menu itself
  useEffect(() => {
    if (!menuOpen) return
    const handlePointer = (e: MouseEvent) => {
      if (!rowRef.current?.contains(e.target as Node)) setMenuOpen(false)
    }
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [menuOpen])

  return (
    <div
      ref={rowRef}
      className="group relative flex items-center gap-2 rounded-lg pl-3 pr-1 py-2 cursor-pointer transition-colors"
      style={{
        background: active ? 'var(--accent-soft)' : 'transparent',
        color: active ? 'var(--accent)' : 'var(--text-muted)',
      }}
      onClick={editing ? undefined : onSelect}
    >
      <ChatTeardropText size={14} weight={active ? 'fill' : 'regular'} className="shrink-0" />
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') { setDraft(title); setEditing(false) }
          }}
          onClick={(e) => e.stopPropagation()}
          className="flex-1 bg-transparent outline-none text-[13px]"
          style={{ color: 'var(--text)' }}
        />
      ) : (
        <span
          className="flex-1 truncate text-[13px] leading-tight"
          style={{ color: active ? 'var(--accent)' : 'var(--text)' }}
          title={title}
        >
          {title}
        </span>
      )}
      <span
        className="text-[10px] opacity-70 group-hover:opacity-0 transition-opacity shrink-0 pr-1"
        style={{ color: 'var(--text-subtle)' }}
      >
        {formatRelative(updatedAt)}
      </span>

      <button
        onClick={(e) => {
          e.stopPropagation()
          setMenuOpen((v) => !v)
        }}
        className="p-1 rounded-md opacity-0 group-hover:opacity-100 transition-opacity hover:bg-[color:var(--border-strong)]"
        style={{ color: 'var(--text-muted)' }}
        aria-label="Conversation menu"
      >
        <DotsThreeVertical size={14} weight="bold" />
      </button>

      {menuOpen && (
        <div
          className="absolute right-1 top-full mt-1 z-20 min-w-[140px] rounded-lg p-1 shadow-lg"
          style={{
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-strong)',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => {
              setEditing(true)
              setMenuOpen(false)
            }}
            className="flex items-center gap-2 w-full px-2.5 py-1.5 text-[12px] rounded-md hover:bg-[color:var(--accent-soft)]"
            style={{ color: 'var(--text)' }}
          >
            <PencilSimple size={13} /> Rename
          </button>
          <button
            onClick={() => {
              onDelete()
              setMenuOpen(false)
            }}
            className="flex items-center gap-2 w-full px-2.5 py-1.5 text-[12px] rounded-md hover:bg-[color:var(--danger-soft)]"
            style={{ color: 'var(--danger)' }}
          >
            <TrashSimple size={13} /> Delete
          </button>
        </div>
      )}
    </div>
  )
}

function SkeletonRow({ widthPct }: { widthPct: number }) {
  // Mimics the visual rhythm of ConversationRow so the load → loaded
  // transition doesn't cause layout shift.
  return (
    <div
      className="flex items-center gap-2 rounded-lg pl-3 pr-2 py-2 animate-pulse"
      style={{ opacity: 0.55 }}
    >
      <div
        className="w-3.5 h-3.5 rounded shrink-0"
        style={{ background: 'var(--border-strong)' }}
      />
      <div
        className="h-2.5 rounded"
        style={{ background: 'var(--border-strong)', width: `${widthPct}%` }}
      />
    </div>
  )
}

export default function Layout() {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const location = useLocation()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(false)

  const {
    conversations,
    order,
    activeId,
    loaded,
    createConversation,
    deleteConversation,
    renameConversation,
  } = useChatStore()

  // Always load conversations for the sidebar, even if the user lands
  // on a non-chat route. This ensures skeletons show immediately.
  useEffect(() => {
    const { loadFromApi, loaded } = useChatStore.getState()
    if (!loaded) {
      void loadFromApi()
    }
  }, [])

  const onChatRoute = location.pathname.startsWith('/chat')

  const recent = useMemo(
    () => order.map((id) => conversations[id]).filter(Boolean),
    [order, conversations]
  )

  const currentLabel =
    navItems.find((n) => n.to === location.pathname)?.label || 'SNTI'

  const handleNewChat = () => {
    // If the current active conv is already empty, just reuse it
    // instead of spawning yet another empty conversation. Matches
    // ChatGPT behavior where "New chat" is a no-op when you're
    // already on a fresh chat.
    const current = activeId ? conversations[activeId] : null
    if (current && current.messages.length === 0) {
      navigate(`/chat/${current.id}`)
      return
    }
    const newId = createConversation()
    navigate(`/chat/${newId}`)
  }

  return (
    <div
      className="flex h-screen font-sans"
      style={{ background: 'var(--bg)', color: 'var(--text)' }}
    >
      {/* Sidebar */}
      <aside
        className="flex flex-col transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] overflow-hidden"
        style={{
          width: collapsed ? 0 : 288,
          borderRight: collapsed ? 'none' : '1px solid var(--border)',
          background: 'var(--bg-elevated)',
        }}
      >
        {/* Brand */}
        <div
          className="px-5 pt-5 pb-4 flex items-center gap-3"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <img
            src="/logo.jpeg"
            alt="SNTI"
            className="w-12 h-12 rounded-lg object-cover shrink-0"
            style={{ border: '1px solid var(--border-strong)' }}
          />
          <span className="font-display text-[22px] tracking-tight leading-none">
            snti<span className="mark">.</span>
          </span>
        </div>

        {/* Primary nav */}
        <nav className="px-3 py-3 space-y-0.5">
          {navItems.map(({ to, icon: Icon, label }) => {
            const active = location.pathname === to
            return (
              <NavLink
                key={to}
                to={to}
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-[13px] font-medium transition-colors"
                style={{
                  background: active ? 'var(--accent-soft)' : 'transparent',
                  color: active ? 'var(--accent)' : 'var(--text-muted)',
                }}
              >
                <Icon weight={active ? 'fill' : 'regular'} size={16} />
                {label}
              </NavLink>
            )
          })}
        </nav>

        {/* Chat history — only on /chat route */}
        {onChatRoute && (
          <>
            <div className="rule mx-3" />
            <div className="px-5 pt-4 pb-2 flex items-center justify-between">
              <span
                className="text-[10px] uppercase tracking-[0.18em]"
                style={{ color: 'var(--text-subtle)' }}
              >
                History
              </span>
              <button
                onClick={handleNewChat}
                className="flex items-center gap-1 text-[11px] rounded-full px-2 py-1 transition-colors"
                style={{
                  color: 'var(--accent)',
                  border: '1px solid var(--accent-ring)',
                }}
              >
                <Plus size={11} weight="bold" /> New
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-2 pb-3 space-y-0.5">
              {!loaded ? (
                // Skeleton conversation rows — gives a sense of structure
                // while history loads, instead of a single jarring spinner.
                <div className="space-y-1 px-1 pt-1">
                  {[80, 65, 90, 55, 75, 60].map((w, i) => (
                    <SkeletonRow key={i} widthPct={w} />
                  ))}
                </div>
              ) : recent.length === 0 ? (
                <div
                  className="px-3 py-6 text-center text-[12px] italic"
                  style={{ color: 'var(--text-subtle)' }}
                >
                  No conversations yet.
                </div>
              ) : (
                recent.map((c) => (
                  <ConversationRow
                    key={c.id}
                    title={c.title}
                    updatedAt={c.updatedAt}
                    active={c.id === activeId}
                    onSelect={() => navigate(`/chat/${c.id}`)}
                    onRename={(next) => renameConversation(c.id, next)}
                    onDelete={() => deleteConversation(c.id)}
                  />
                ))
              )}
            </div>
          </>
        )}

        {!onChatRoute && <div className="flex-1" />}

        {/* Footer: theme + user */}
        <div
          className="p-3 space-y-1"
          style={{ borderTop: '1px solid var(--border)' }}
        >
          <ThemeToggle />
          <div className="flex items-center gap-3 px-3 py-2">
            <UserCircle size={18} weight="fill" style={{ color: 'var(--accent)' }} />
            <div className="flex-1 min-w-0">
              <p className="text-[13px] font-medium truncate">{user?.name || 'User'}</p>
              <p
                className="text-[11px] truncate"
                style={{ color: 'var(--text-subtle)' }}
              >
                {user?.email}
              </p>
            </div>
          </div>
          <button
            onClick={logout}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-[13px] w-full transition-colors"
            style={{ color: 'var(--text-muted)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'var(--danger-soft)'
              e.currentTarget.style.color = 'var(--danger)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'transparent'
              e.currentTarget.style.color = 'var(--text-muted)'
            }}
          >
            <SignOut size={16} />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header
          className="h-14 flex items-center px-4 shrink-0"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="btn-ghost !p-2"
            aria-label={collapsed ? 'Open sidebar' : 'Close sidebar'}
          >
            {collapsed ? <List size={18} /> : <X size={18} />}
          </button>
          <span
            className="ml-4 font-display text-[18px] tracking-tight leading-none"
          >
            {currentLabel.toLowerCase()}
          </span>
          <span
            className="ml-3 text-[11px] uppercase tracking-[0.2em] mt-1"
            style={{ color: 'var(--text-subtle)' }}
          >
            — {new Date().toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}
          </span>

          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle compact />
          </div>
        </header>

        <div className="flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
