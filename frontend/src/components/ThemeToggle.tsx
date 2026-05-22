import { Moon, Sun } from '@phosphor-icons/react'
import { useThemeStore } from '../store/themeStore'

interface ThemeToggleProps {
  compact?: boolean
}

export default function ThemeToggle({ compact = false }: ThemeToggleProps) {
  const theme = useThemeStore((s) => s.theme)
  const toggle = useThemeStore((s) => s.toggle)
  const isDark = theme === 'dark'

  if (compact) {
    return (
      <button
        onClick={toggle}
        aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
        className="btn-ghost !p-2"
        title={isDark ? 'Light mode' : 'Dark mode'}
      >
        {isDark ? <Sun size={18} weight="regular" /> : <Moon size={18} weight="regular" />}
      </button>
    )
  }

  return (
    <button
      onClick={toggle}
      aria-label="Toggle theme"
      className="flex items-center justify-between w-full px-3 py-2 rounded-lg text-sm
                 transition-all hover:bg-[var(--accent-soft)]"
      style={{ color: 'var(--text-muted)' }}
    >
      <span className="flex items-center gap-2.5">
        {isDark ? <Sun size={16} /> : <Moon size={16} />}
        <span>{isDark ? 'Light mode' : 'Dark mode'}</span>
      </span>
      <span
        className="relative h-5 w-9 rounded-full transition-colors"
        style={{ background: isDark ? 'var(--accent)' : 'var(--border-strong)' }}
      >
        <span
          className="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform"
          style={{ transform: isDark ? 'translateX(16px)' : 'translateX(0)' }}
        />
      </span>
    </button>
  )
}
