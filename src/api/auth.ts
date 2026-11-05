import { authFetch } from './authFetch'
import type { AuthSession } from '@/stores/authStore'

interface UserProfile { id?: string | number; username: string; alias?: string; is_active?: boolean; state?: number }

export async function login(username: string, password: string, signal?: AbortSignal): Promise<AuthSession> {
  let response: Response
  try {
    response = await fetch('/base/auth/access_token', { method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username.trim(), password }) })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new Error('无法连接登录服务，请稍后重试。')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok || body?.status !== 'success') throw new Error(body?.message || '登录失败，请检查账号和密码。')
  const user = body.data
  if (!user || typeof user.access_token !== 'string' || !user.access_token || typeof user.username !== 'string' || !user.username) {
    throw new Error('登录服务返回的数据不完整，请联系管理员。')
  }
  return { token: user.access_token, username: user.username, alias: user.alias || user.username }
}

export async function currentUser(signal?: AbortSignal): Promise<UserProfile> {
  const response = await authFetch('/base/auth/userinfo', { method: 'POST', signal,
    headers: { 'Content-Type': 'application/json' }, body: '{}' })
  const body = await response.json().catch(() => null)
  if (!response.ok || body?.status !== 'success') throw new Error(body?.message || body?.detail || '无法获取用户信息，请重试。')
  if (!body.data?.username || body.data.is_active === false || body.data.state === 1) throw new Error('账号状态不可用，请联系管理员。')
  return body.data
}
