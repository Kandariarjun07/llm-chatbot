import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'light' | 'dark'

interface ThemeState {
  theme: Theme
  setTheme: (t: Theme) => void
  toggle: () => void
}

const applyToDocument = (theme: Theme) => {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      setTheme: (theme) => {
        applyToDocument(theme)
        set({ theme })
      },
      toggle: () => {
        const next: Theme = get().theme === 'dark' ? 'light' : 'dark'
        applyToDocument(next)
        set({ theme: next })
      },
    }),
    {
      name: 'snti.theme',
      onRehydrateStorage: () => (state) => {
        if (state) applyToDocument(state.theme)
      },
    }
  )
)

/**
 * Call once at app boot (before React renders) so first paint matches the
 * persisted theme and we avoid a light → dark flash.
 */
export function initTheme() {
  try {
    const raw = localStorage.getItem('snti.theme')
    const saved = raw ? (JSON.parse(raw)?.state?.theme as Theme | undefined) : undefined
    applyToDocument(saved ?? 'dark')
  } catch {
    applyToDocument('dark')
  }
}
