import { create } from 'zustand'
import { demoActors, type Actor } from '@/lib/access'

// 沿用平台身份入口；此处不持久化模拟身份，切换仅用于验证个人权限。
export const useAccessStore = create<{ actor: Actor; setIdentity: (actor: Actor) => void; setActor: (id: string) => void }>(set => ({
  actor: { id: '', name: '未登录' },
  setIdentity: actor => set({ actor }),
  setActor: id => { const actor = demoActors.find(row => row.id === id); if (actor) set({ actor }) },
}))
