import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export interface AuthSession { token: string; username: string; alias: string; userId?: string }
interface AuthState { session: AuthSession | null; notice: string; setSession: (session: AuthSession | null) => void; clearSession: (notice?: string) => void }
export const useAuthStore = create<AuthState>()(persist(set => ({
  session: null, notice: '', setSession: session => set(state => ({ session, notice: session ? '' : state.notice })),
  clearSession: (notice = '') => set({ session: null, notice }),
}), { name: 'znfwdd-session', storage: createJSONStorage(() => sessionStorage), partialize: state => ({ session: state.session }) }))
