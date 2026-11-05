import { useAuthStore } from '@/stores/authStore'

/** One authentication path for JSON, multipart, polling and binary downloads. */
export async function authFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const token = useAuthStore.getState().session?.token
  const headers = Object.fromEntries(new Headers(options.headers).entries())
  if (token) headers.token = token
  const response = await fetch(path, { ...options, headers })
  let expired = response.status === 401
  if (!expired && response.headers.get('content-type')?.includes('application/json')) {
    const body = await response.clone().json().catch(() => null)
    // The existing platform can report authentication failure in an HTTP 200 envelope.
    expired = body?.status === 'failure' && String(body?.code) === '400401'
  }
  if (expired) {
    // A response from an old session must not log out the newly signed-in account.
    if (token && useAuthStore.getState().session?.token === token) {
      useAuthStore.getState().clearSession('登录已失效，请重新登录。')
    }
    if (response.status !== 401) return new Response(await response.text(), { status: 401, headers: response.headers })
  }
  return response
}
