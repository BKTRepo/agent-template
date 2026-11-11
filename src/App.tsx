import { useEffect, useState } from 'react'
import { Boxes, FileStack, GitBranch, House, Layers3, Menu, Settings, Sparkles, X } from 'lucide-react'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import DeveloperPage from '@/pages/DeveloperPage'
import AssetsPage from '@/pages/AssetsPage'
import KnowledgePage from '@/pages/KnowledgePage'
import OverviewPage from '@/pages/OverviewPage'
import SkillsPage from '@/pages/SkillsPage'
import { useDeveloperStore } from '@/stores/developerStore'
import { useAccessStore } from '@/stores/accessStore'
import { currentUser } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'
import { useKnowledgeStore } from '@/stores/knowledgeStore'
import LoginPage from '@/pages/LoginPage'
import PlatformAccount from '@/components/common/PlatformAccount'
import FloatingAssistant from '@/components/assistant/FloatingAssistant'
import KnowledgeProcessingWorker from '@/components/developer/KnowledgeProcessingWorker'
import KnowledgeUpdatesWorker from '@/components/developer/KnowledgeUpdatesWorker'
import { useKnowledgeUpdatesStore } from '@/stores/knowledgeUpdatesStore'

const navigation = [
  { group: '平台门户', items: [
    { id: 'overview', label: '总览', icon: House },
    { id: 'skills', label: '技能中心', icon: Sparkles },
    { id: 'developer', label: '开发者中心', icon: Boxes },
    { id: 'workflow', label: '技能编排', icon: GitBranch },
  ] },
  { group: '资源治理', items: [
    { id: 'knowledge', label: '知识库与文件管理', icon: Layers3 },
    { id: 'assets', label: '资产管理', icon: FileStack },
  ] },
  { group: '平台管理', items: [{ id: 'mcp', label: 'MCP 接入配置', icon: Settings }] },
]

export default function App() {
  const token = useAuthStore(state => state.session?.token)
  const [verifiedToken, setVerifiedToken] = useState('')
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setVerifiedToken(''); setError('')
    useAccessStore.getState().setIdentity({ id: '', name: '未登录' })
    useDeveloperStore.setState({ implementations: [], skillClasses: [], applications: [], filterSkillClasses: [], statuses: [], filters: { name: '', classId: '', status: '', application: '' }, total: 0, pages: 1, page: 1, loading: false })
    useKnowledgeStore.getState().reset()
    useKnowledgeUpdatesStore.getState().reset()
    if (token) void currentUser(controller.signal).then(user => {
      const session = useAuthStore.getState().session
      if (controller.signal.aborted || session?.token !== token) return
      useAuthStore.getState().setSession({ ...session, username: user.username, alias: user.alias || user.username, userId: String(user.id ?? '') })
      useAccessStore.getState().setIdentity({ id: user.username, name: user.alias || user.username })
      setVerifiedToken(token)
    }).catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
    return () => controller.abort()
  }, [token, retry])
  if (!token) return <LoginPage />
  if (verifiedToken !== token) return <main className="auth-loading" aria-live="polite"><div className="surface"><h1>{error ? '暂时无法确认登录状态' : '正在确认登录状态…'}</h1>{error && <><p role="alert">{error}</p><button className="button primary" onClick={() => setRetry(value => value + 1)}>重试</button><button className="button" onClick={() => useAuthStore.getState().clearSession()}>返回登录</button></>}</div></main>
  return <Workspace key={token} />
}

function Workspace() {
  const [page, setPage] = useState('developer')
  const [mobileMenu, setMobileMenu] = useState(false)
  const updateSummary = useKnowledgeUpdatesStore(state => state.summary)
  const actor = useAccessStore(state => state.actor)
  const unreadSkills = updateSummary?.unread_skill_count ?? 0
  const label = navigation.flatMap(group => group.items).find(item => item.id === page)?.label ?? '开发者中心'
  return <ErrorBoundary><div className="platform">
    {mobileMenu && <button className="sidebar-shade" aria-label="关闭导航" onClick={() => setMobileMenu(false)} />}
    <aside className={`platform-sidebar ${mobileMenu ? 'is-open' : ''}`} aria-label="平台导航">
      <a className="platform-logo" href="#developer" onClick={() => { setPage('developer'); setMobileMenu(false) }}><span className="platform-mark">AI</span><span>智能服务调度集</span></a>
      <button className="mobile-close icon-button" aria-label="关闭导航" onClick={() => setMobileMenu(false)}><X size={20} /></button>
      <nav>{navigation.map(group => <div className="nav-group" key={group.group}><div className="nav-group-title">{group.group}</div>
        {group.items.map(item => <button key={item.id} className={`nav-link ${page === item.id ? 'active' : ''}`} aria-current={page === item.id ? 'page' : undefined} onClick={() => { setPage(item.id); setMobileMenu(false) }}><item.icon size={17} strokeWidth={1.6} /><span>{item.label}</span>{item.id === 'developer' && unreadSkills > 0 && <span className="nav-badge knowledge-update-nav-badge" aria-label={`${unreadSkills}个技能有未读知识库更新`} title={`${unreadSkills}个技能有未读知识库更新`}>{unreadSkills > 99 ? '99+' : unreadSkills}</span>}</button>)}
      </div>)}</nav>
    </aside>
    <main className="platform-main"><header className="platform-topbar"><div className="topbar-title"><button className="mobile-menu icon-button" aria-label="打开导航" onClick={() => setMobileMenu(true)}><Menu size={20} /></button><span>{label}</span>{page === 'skills' && <span className="topbar-subtitle">Skill 类 + 实现类管理 · 已上线可在线测试，已下线保留详情和下载</span>}{page === 'developer' && <span className="topbar-subtitle">技能新建、调试、上线全链路管理</span>}{page === 'knowledge' && <span className="topbar-subtitle">Skill 依赖与引用资源管理 · 团队权限隔离</span>}</div><div className="topbar-actions"><PlatformAccount /></div></header>
      <div className="platform-content" key={actor.id || "platform"}>{page === 'developer' ? <DeveloperPage /> : page === 'knowledge' ? <KnowledgePage /> : page === 'skills' ? <SkillsPage /> : page === 'overview' ? <OverviewPage /> : page === 'assets' ? <AssetsPage /> : <section className="module-placeholder"><h1>{label}</h1><div className="surface placeholder-body"><Layers3 size={36} /><h2>该模块暂未开放</h2><p>当前可使用开发者中心创建和调试 Skill。</p><button className="button primary" onClick={() => setPage('developer')}>进入开发者中心</button></div></section>}</div>
    </main>
    <KnowledgeProcessingWorker /><KnowledgeUpdatesWorker /><FloatingAssistant key={actor.id || "platform"} />
  </div></ErrorBoundary>
}
