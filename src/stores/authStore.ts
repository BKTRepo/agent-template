import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export interface AuthSession { token: string; username: string; alias: string }
interface AuthState { session: AuthSession | null; setSession: (session: AuthSession | null) => void }
export const useAuthStore = create<AuthState>()(persist(set => ({
  session: null, setSession: session => set({ session }),
}), { name: 'znfwdd-session', storage: createJSONStorage(() => sessionStorage) }))
