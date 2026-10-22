import { useAuthStore } from '@/stores/authStore'

export const skillBackendEnabled = import.meta.env?.VITE_SKILL_METADATA_READY === 'true'
export const skillProxyAuth = import.meta.env?.VITE_SKILL_PROXY_AUTH === 'true'
export function hasSkillSession() { return !!useAuthStore.getState().session?.token || skillProxyAuth }
export function skillAccount() {
  return skillProxyAuth ? import.meta.env?.VITE_SKILL_PROXY_ACCOUNT || 'local-skill-proxy' : useAuthStore.getState().session?.username
}
