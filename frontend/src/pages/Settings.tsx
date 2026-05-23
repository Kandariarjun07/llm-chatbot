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
  Smiley,
  Brain,
  ChatCenteredText,
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
  const [aboutMe, setAboutMe] = useState('')
  const [responseMode, setResponseMode] = useState('friendly')
  const [emojiFrequency, setEmojiFrequency] = useState('moderately')
  const [updatingInst, setUpdatingInst] = useState(false)
  const [instMsg, setInstMsg] = useState<'' | 'ok' | 'err'>('')
  
  // Load preferences on mount
  useEffect(() => {
    if (user) {
      authApi.getPreferences()
        .then((res: any) => {
          setInstructions(res.data.instructions || '')
          setAboutMe(res.data.about_me || '')
          setResponseMode(res.data.response_mode || 'friendly')
          setEmojiFrequency(res.data.emoji_frequency || 'moderately')
        })
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
      await authApi.updatePreferences({
        instructions: instructions.trim(),
        about_me: aboutMe.trim(),
        response_mode: responseMode,
        emoji_frequency: emojiFrequency,
      })
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

      {/* AI Personalization */}
      <Section title="AI Personalization" icon={<Cpu size={16} />}>
        <div className="space-y-6">
          {/* About Yourself */}
          <div>
            <label className={labelCls} style={labelStyle}>about yourself (max 150 words)</label>
            <p className="text-[12px] mb-2" style={{ color: 'var(--text-muted)' }}>
              Tell the AI who you are (e.g. your role, interests, or background) to customize responses.
            </p>
            <textarea
              value={aboutMe}
              onChange={(e) => {
                const text = e.target.value;
                const words = text.trim().split(/\s+/);
                if (words.length <= 150 || text.length < aboutMe.length) {
                  setAboutMe(text);
                }
              }}
              placeholder="E.g., I am a web developer studying computer science..."
              className="input w-full min-h-[90px] resize-y p-3"
              style={{ fontSize: '13px' }}
            />
            <div className="text-[11px] mt-1 text-right" style={{ color: 'var(--text-muted)' }}>
              {aboutMe.trim() ? aboutMe.trim().split(/\s+/).length : 0} / 150 words
            </div>
          </div>

          {/* Custom Instructions */}
          <div>
            <label className={labelCls} style={labelStyle}>custom instructions (max 150 words)</label>
            <p className="text-[12px] mb-2" style={{ color: 'var(--text-muted)' }}>
              Tell the AI how you want it to behave (e.g., "Always explain with code examples").
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
              className="input w-full min-h-[90px] resize-y p-3"
              style={{ fontSize: '13px' }}
            />
            <div className="text-[11px] mt-1 text-right" style={{ color: 'var(--text-muted)' }}>
              {instructions.trim() ? instructions.trim().split(/\s+/).length : 0} / 150 words
            </div>
          </div>

          {/* Response Mode/Tone */}
          <div>
            <label className={labelCls} style={labelStyle}>response tone / mode</label>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {[
                { id: 'friendly', label: 'Friendly', desc: 'Warm & conversational', icon: <Smiley size={14} /> },
                { id: 'formal', label: 'Formal', desc: 'Structured & academic', icon: <Brain size={14} /> },
                { id: 'professional', label: 'Professional', desc: 'Crisp & business-like', icon: <Cpu size={14} /> },
                { id: 'creative', label: 'Creative', desc: 'Expressive & vivid', icon: <Palette size={14} /> },
                { id: 'humorous', label: 'Humorous', desc: 'Witty & playful', icon: <Smiley size={14} weight="fill" /> },
                { id: 'concise', label: 'Concise', desc: 'Brief & direct', icon: <ChatCenteredText size={14} /> },
              ].map((m) => (
                <SelectCard
                  key={m.id}
                  active={responseMode === m.id}
                  onClick={() => setResponseMode(m.id)}
                  label={m.label}
                  desc={m.desc}
                  icon={m.icon}
                />
              ))}
            </div>
          </div>

          {/* Emoji Frequency */}
          <div>
            <label className={labelCls} style={labelStyle}>emoji usage</label>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
              {[
                { id: 'never', label: 'Never', desc: '🚫 Strictly text' },
                { id: 'rarely', label: 'Rarely', desc: '⏳ Very sparse' },
                { id: 'moderately', label: 'Moderately', desc: '🙂 Natural' },
                { id: 'frequently', label: 'Frequently', desc: '🎉 Expressive' },
                { id: 'always', label: 'Always', desc: '🤪 Maximum' },
              ].map((f) => (
                <SelectCard
                  key={f.id}
                  active={emojiFrequency === f.id}
                  onClick={() => setEmojiFrequency(f.id)}
                  label={f.label}
                  desc={f.desc}
                />
              ))}
            </div>
          </div>

          {/* Save Button & Feedback Messages */}
          <div className="pt-4 flex items-center justify-between border-t" style={{ borderColor: 'var(--border)' }}>
            <div>
              {instMsg === 'ok' && (
                <div className="flex items-center gap-2 text-[13px]" style={{ color: 'var(--accent)' }}>
                  <CheckCircle size={15} weight="fill" /> personalization saved across devices
                </div>
              )}
              {instMsg === 'err' && (
                <div className="flex items-center gap-2 text-[13px]" style={{ color: 'var(--danger)' }}>
                  <WarningCircle size={15} weight="fill" /> failed to save personalization
                </div>
              )}
            </div>
            <button
              onClick={handleUpdateInstructions}
              disabled={updatingInst}
              className="btn-primary min-w-[100px]"
            >
              {updatingInst ? <Spinner className="animate-spin" size={14} /> : null}
              save changes
            </button>
          </div>
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

interface SelectCardProps {
  active: boolean
  onClick: () => void
  label: string
  desc: string
  icon?: React.ReactNode
}

function SelectCard({ active, onClick, label, desc, icon }: SelectCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left p-3.5 rounded-xl transition-all duration-200"
      style={{
        background: active ? 'var(--accent-soft)' : 'transparent',
        border: `1px solid ${active ? 'var(--accent)' : 'var(--border-strong)'}`,
        color: active ? 'var(--accent)' : 'var(--text)',
      }}
    >
      <div className="flex items-center gap-2 mb-1">
        {icon && <span className="shrink-0">{icon}</span>}
        <span className="font-medium text-[13px]">{label}</span>
      </div>
      <p className="text-[11px] leading-relaxed" style={{ color: 'var(--text-subtle)' }}>
        {desc}
      </p>
    </button>
  )
}
