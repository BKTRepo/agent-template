import { useEffect, useState } from 'react'
import { useAuthStore } from '@/stores/authStore'
import App from '@/App'

const sourceOrigin = 'http://10.208.237.37:6001'

export default function TechnicalTestLoginPage({ showAppWhileWaiting = false }: { showAppWhileWaiting?: boolean }) {
  const [complete, setComplete] = useState(false)
  const [started, setStarted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('正在等待技术测试平台传入工号…')

  useEffect(() => {
    const controller = new AbortController()
    let submitting = false
    const sources: Window[] = []
    if (window.opener) sources.push(window.opener)
    if (window.parent !== window) sources.push(window.parent)
    const receive = async (event: MessageEvent) => {
      if (event.origin !== sourceOrigin || !sources.includes(event.source as Window) || submitting) return
      setStarted(true)
      const raw: unknown = typeof event.data === 'string' ? event.data : event.data?.loginName
      if (typeof raw !== 'string' || !/^[A-Za-z0-9_-]{1,32}$/.test(raw.trim())) {
        setMessage('未收到有效工号，请联系技术测试平台。')
        return
      }
      submitting = true
      setBusy(true)
      setMessage('正在校验工号并登录…')
      try {
        const response = await fetch('/base/auth/technical-test-login', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ loginName: raw.trim() }), signal: controller.signal,
        })
        const result = await response.json().catch(() => null)
        if (!response.ok || result?.status !== 'success') throw new Error(result?.detail || result?.message || '登录失败，请稍后重试。')
        const data = result.data
        if (!data?.access_token || !data?.username) throw new Error('登录服务返回的数据不完整。')
        useAuthStore.getState().setSession({ token: data.access_token, username: data.username, alias: data.alias || data.username })
        window.history.replaceState({}, '', '/')
        setComplete(true)
      } catch (error) {
        if (!controller.signal.aborted) { setMessage(error instanceof Error ? error.message : '登录失败，请稍后重试。'); submitting = false; setBusy(false) }
      }
    }
    window.addEventListener('message', receive)
    sources.forEach(source => source.postMessage({ type: 'technical-test-sso-ready' }, sourceOrigin))
    return () => { controller.abort(); window.removeEventListener('message', receive) }
  }, [])

  if (complete || (showAppWhileWaiting && !started)) return <App />
  return <main className="auth-loading" aria-live="polite"><div className="surface"><h1>技术测试平台登录</h1><p>{message}</p>{showAppWhileWaiting && <button type="button" disabled={busy} onClick={() => setStarted(false)}>返回普通登录</button>}</div></main>
}
