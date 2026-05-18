import { useState, useEffect } from 'react'
import { useAuthStore } from '../store/authStore'
import { useThemeStore } from '../store/themeStore'
import { useChatStore } from '../store/chatStore'
import { api, authApi } from '../lib/api'
import {
  UserCircle,
  Palette,
  Trash,
  Spinner,
  CheckCircle,
  WarningCircle,
  Sun,
  Moon,
  SignOut,
  Cpu,
} from '@phosphor-icons/react'

export default function Settings() {
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)
  const logout = useAuthStore((s) => s.logout)

  const theme = useThemeStore((s) => s.theme)
  const setTheme = useThemeStore((s) => s.setTheme)
  const clearAllChats = useChatStore((s) => s.clearAll)

  const [name, setName] = useState(user?.name || '')
  const [updating, setUpdating] = useState(false)
  const [updateMsg, setUpdateMsg] = useState<'' | 'ok' | 'err'>('')
  const [instructions, setInstructions] = useState('')
  const [updatingInst, setUpdatingInst] = useState(false)
  const [instMsg, setInstMsg] = useState<'' | 'ok' | 'err'>('')
  
  // Load preferences on mount
  useEffect(() => {
    if (user) {
      authApi.getPreferences()
        .then((res: any) => setInstructions(res.data.instructions || ''))
        .catch(() => {})
    }
  }, [user])

  const handleUpdateProfile = async () => {
    if (!name.trim()) return
    setUpdating(true)
    setUpdateMsg('')
    try {
      await api.post('/auth/update-profile', { name: name.trim() })
      if (user) setUser({ ...user, name: name.trim() })
      setUpdateMsg('ok')
    } catch {
      setUpdateMsg('err')
    } finally {
      setUpdating(false)
    }
  }

  const handleUpdateInstructions = async () => {
    setUpdatingInst(true)
    setInstMsg('')
    try {
      await authApi.updatePreferences(instructions.trim())
      setInstMsg('ok')
    } catch {
      setInstMsg('err')
    } finally {
      setUpdatingInst(false)
    }
  }

  const clearImageHistory = () => {
    localStorage.removeItem('image_history')
  }

  const labelCls = 'block text-[10px] uppercase tracking-[0.22em] mb-2'
  const labelStyle: React.CSSProperties = { color: 'var(--text-subtle)' }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 space-y-8">
      {/* Header */}
      <div>
        <p
          className="text-[11px] uppercase tracking-[0.22em] mb-3"
          style={{ color: 'var(--accent)' }}
        >
          — preferences
        </p>
        <h1 className="font-display text-5xl leading-[1.02] tracking-tight">
          make it <span className="mark">yours</span>.
        </h1>
      </div>

      {/* Profile */}
      <Section title="Profile" icon={<UserCircle size={16} />}>
        <div className="space-y-5">
          <div>
            <label className={labelCls} style={labelStyle}>email</label>
            <input
              type="email"
              value={user?.email || ''}
              disabled
              className="input cursor-not-allowed opacity-60"
            />
          </div>
          <div>
            <label className={labelCls} style={labelStyle}>display name</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="input flex-1"
              />
              <button
                onClick={handleUpdateProfile}
                disabled={updating}
                className="btn-primary"
              >
                {updating ? <Spinner className="animate-spin" size={14} /> : null}
                save
              </button>
            </div>
          </div>
          {updateMsg === 'ok' && (
            <div
              className="flex items-center gap-2 text-[13px]"
              style={{ color: 'var(--accent)' }}
            >
              <CheckCircle size={14} weight="fill" /> profile updated
            </div>
          )}
          {updateMsg === 'err' && (
            <div
              className="flex items-center gap-2 text-[13px]"
              style={{ color: 'var(--danger)' }}
            >
              <WarningCircle size={14} weight="fill" /> failed to update
            </div>
          )}
        </div>
      </Section>

      {/* AI Instructions */}
      <Section title="AI Instructions" icon={<Cpu size={16} />}>
        <div className="space-y-3">
          <label className={labelCls} style={labelStyle}>custom instructions (max 150 words)</label>
          <p className="text-[12px] mb-3" style={{ color: 'var(--text-muted)' }}>
            Tell the AI how you want it to respond (e.g., "Always reply in Python", "Be very concise").
          </p>
          <textarea
            value={instructions}
            onChange={(e) => {
              const text = e.target.value;
              const words = text.trim().split(/\s+/);
              if (words.length <= 150 || text.length < instructions.length) {
                setInstructions(text);
              }
            }}
            placeholder="Your custom instructions..."
            className="input w-full min-h-[100px] resize-y p-3"
            style={{ fontSize: '13px' }}
          />
          <div className="flex items-center justify-between mt-2">
            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              {instructions.trim() ? instructions.trim().split(/\s+/).length : 0} / 150 words
            </span>
            <button
              onClick={handleUpdateInstructions}
              disabled={updatingInst}
              className="btn-primary"
            >
              {updatingInst ? <Spinner className="animate-spin" size={14} /> : null}
              save
            </button>
          </div>
          {instMsg === 'ok' && (
            <div className="flex items-center gap-2 text-[13px] mt-2" style={{ color: 'var(--accent)' }}>
              <CheckCircle size={14} weight="fill" /> instructions saved across devices
            </div>
          )}
          {instMsg === 'err' && (
            <div className="flex items-center gap-2 text-[13px] mt-2" style={{ color: 'var(--danger)' }}>
              <WarningCircle size={14} weight="fill" /> failed to save
            </div>
          )}
        </div>
      </Section>

      {/* Appearance */}
      <Section title="Appearance" icon={<Palette size={16} />}>
        <label className={labelCls} style={labelStyle}>theme</label>
        <div className="grid grid-cols-2 gap-3">
          <ThemeCard
            active={theme === 'light'}
            onClick={() => setTheme('light')}
            icon={<Sun size={18} weight="fill" />}
            label="Light"
            hint="warm cream · ink"
          />
          <ThemeCard
            active={theme === 'dark'}
            onClick={() => setTheme('dark')}
            icon={<Moon size={18} weight="fill" />}
            label="Dark"
            hint="near-black · gold"
          />
        </div>
      </Section>

      {/* Data */}
      <Section title="Data" icon={<Trash size={16} />}>
        <div className="space-y-3">
          <DataRow
            title="Chat history"
            subtitle="Delete every saved conversation"
            onAction={clearAllChats}
          />
          <DataRow
            title="Image history"
            subtitle="Delete every generated image"
            onAction={clearImageHistory}
          />
        </div>
      </Section>

      {/* Account */}
      <Section title="Account" icon={<SignOut size={16} />}>
        <button
          onClick={logout}
          className="w-full py-3 rounded-xl text-[13px] font-medium transition-colors flex items-center justify-center gap-2"
          style={{
            background: 'var(--danger-soft)',
            color: 'var(--danger)',
            border: '1px solid var(--danger)',
          }}
        >
          <SignOut size={14} /> sign out of all devices
        </button>
      </Section>
    </div>
  )
}

function Section({
  title,
  icon,
  children,
}: {
  title: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section
      className="rounded-2xl p-6"
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
      }}
    >
      <div className="flex items-center gap-2 mb-5">
        <span style={{ color: 'var(--accent)' }}>{icon}</span>
        <h2 className="font-display text-[22px] tracking-tight leading-none">
          {title.toLowerCase()}
        </h2>
      </div>
      {children}
    </section>
  )
}

function ThemeCard({
  active,
  onClick,
  icon,
  label,
  hint,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
  hint: string
}) {
  return (
    <button
      onClick={onClick}
      className="text-left p-4 rounded-xl transition-all duration-200"
      style={{
        background: active ? 'var(--accent-soft)' : 'transparent',
        border: `1px solid ${active ? 'var(--accent)' : 'var(--border-strong)'}`,
        color: active ? 'var(--accent)' : 'var(--text)',
      }}
    >
      <div className="flex items-center gap-2 mb-1">
        <span>{icon}</span>
        <span className="font-medium text-[14px]">{label}</span>
      </div>
      <p className="text-[11px]" style={{ color: 'var(--text-subtle)' }}>
        {hint}
      </p>
    </button>
  )
}

function DataRow({
  title,
  subtitle,
  onAction,
}: {
  title: string
  subtitle: string
  onAction: () => void
}) {
  return (
    <div
      className="flex items-center justify-between p-4 rounded-xl"
      style={{
        background: 'var(--bg-sunken)',
        border: '1px solid var(--border)',
      }}
    >
      <div>
        <p className="text-[14px] font-medium">{title}</p>
        <p className="text-[12px]" style={{ color: 'var(--text-muted)' }}>
          {subtitle}
        </p>
      </div>
      <button
        onClick={onAction}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] transition-colors"
        style={{
          color: 'var(--danger)',
          border: '1px solid var(--danger)',
        }}
      >
        <Trash size={12} />
        clear
      </button>
    </div>
  )
}
