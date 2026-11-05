import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { BookOpen, Boxes, Eye, EyeOff, LoaderCircle, LockKeyhole } from 'lucide-react'
import { login } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const notice = useAuthStore(state => state.notice)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (request.current) return
    setError(''); setBusy(true)
    const controller = new AbortController(); request.current = controller
    try {
      const session = await login(username, password, controller.signal)
      if (!controller.signal.aborted) { setPassword(''); useAuthStore.getState().setSession(session) }
    } catch (reason) { if (!controller.signal.aborted) setError((reason as Error).message) }
    finally { request.current = null; if (!controller.signal.aborted) setBusy(false) }
  }
  return <main className="login-page"><section className="login-intro" aria-label="平台介绍">
    <div className="login-brand"><span className="platform-mark">AI</span><span>智能服务调度集</span></div>
    <div><p className="login-eyebrow">AI 辅助测试平台</p><h1>让技能与知识<br />连接测试工作</h1><p className="login-lead">集中管理测试技能与业务知识，让每一次调试都有依据。</p>
      <div className="login-features"><span><Boxes size={20} />发现与使用测试技能</span><span><BookOpen size={20} />管理与检索业务知识</span></div></div>
    <p className="login-caption">技能中心 · 开发者中心 · 知识库</p>
  </section><section className="login-panel"><div className="login-card">
    <span className="login-icon"><LockKeyhole size={26} /></span><h2>登录平台</h2><p className="login-subtitle">使用你的平台账号继续</p>
    <form onSubmit={submit} aria-label="平台登录" aria-busy={busy}>
      <label className="login-field" htmlFor="login-username">账号<input id="login-username" name="username" autoComplete="username" required maxLength={64} value={username} disabled={busy} onChange={event => setUsername(event.target.value)} placeholder="请输入平台账号" /></label>
      <label className="login-field" htmlFor="login-password">密码<span className="login-password"><input id="login-password" name="password" type={visible ? 'text' : 'password'} autoComplete="current-password" required value={password} disabled={busy} onChange={event => setPassword(event.target.value)} placeholder="请输入密码" /><button type="button" className="login-password-toggle" aria-label={visible ? '隐藏密码' : '显示密码'} aria-pressed={visible} onClick={() => setVisible(value => !value)}>{visible ? <EyeOff size={19} /> : <Eye size={19} />}</button></span></label>
      {(error || notice) && <p className="login-error" role="alert">{error || notice}</p>}
      <button className="login-submit" type="submit" disabled={busy}>{busy && <LoaderCircle size={18} className="spin" />}{busy ? '正在登录…' : '登录'}</button>
    </form><p className="login-help">账号或密码有问题？请联系平台管理员。</p>
  </div></section></main>
}
