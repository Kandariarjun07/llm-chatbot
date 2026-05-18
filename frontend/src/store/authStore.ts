import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface User {
  user_id: string
  email: string
  name: string
  email_verified?: boolean
}

interface AuthState {
  user: User | null
  idToken: string | null
  refreshToken: string | null
  isLoading: boolean
  setUser: (user: User | null) => void
  setTokens: (idToken: string | null, refreshToken: string | null) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      idToken: null,
      refreshToken: null,
      isLoading: true,
      setUser: (user) => set({ user }),
      setTokens: (idToken, refreshToken) => set({ idToken, refreshToken }),
      logout: () => {
        localStorage.removeItem('id_token')
        localStorage.removeItem('refresh_token')
        set({ user: null, idToken: null, refreshToken: null })
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ user: state.user, idToken: state.idToken, refreshToken: state.refreshToken }),
    },
  ),
)
