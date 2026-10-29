import { useEffect, useState } from 'react'
import { Boxes, FileStack, GitBranch, House, Layers3, Menu, Settings, Sparkles, X } from 'lucide-react'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import DeveloperPage from '@/pages/DeveloperPage'
import KnowledgePage from '@/pages/KnowledgePage'
import SkillsPage from '@/pages/SkillsPage'
import { useDeveloperStore } from '@/stores/developerStore'
import { useAccessStore } from '@/stores/accessStore'
import { getPlatformContext } from '@/api/developerCenter'
import PlatformAccount from '@/components/common/PlatformAccount'
import FloatingAssistant from '@/components/assistant/FloatingAssistant'
import KnowledgeProcessingWorker from '@/components/developer/KnowledgeProcessingWorker'

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
  const [page, setPage] = useState('developer')
  const [mobileMenu, setMobileMenu] = useState(false)
  const { implementations } = useDeveloperStore()
  const actor = useAccessStore(state => state.actor)
  const { setIdentity } = useAccessStore()
  useEffect(() => {
    useDeveloperStore.setState({ implementations: [], skillClasses: [], applications: [] })
    let active = true
    void getPlatformContext().then(identity => { if (active) setIdentity(identity) }).catch(() => { if (active) setIdentity({ id: '', name: '' }) })
    return () => { active = false }
  }, [setIdentity])
  const pending = implementations.filter(item => ['草稿', '已生成', '调试中'].includes(item.status)).length
  const label = navigation.flatMap(group => group.items).find(item => item.id === page)?.label ?? '开发者中心'
  return <ErrorBoundary><div className="platform">
    {mobileMenu && <button className="sidebar-shade" aria-label="关闭导航" onClick={() => setMobileMenu(false)} />}
    <aside className={`platform-sidebar ${mobileMenu ? 'is-open' : ''}`} aria-label="平台导航">
      <a className="platform-logo" href="#developer" onClick={() => { setPage('developer'); setMobileMenu(false) }}><span className="platform-mark">AI</span><span>智能服务调度集</span></a>
      <button className="mobile-close icon-button" aria-label="关闭导航" onClick={() => setMobileMenu(false)}><X size={20} /></button>
      <nav>{navigation.map(group => <div className="nav-group" key={group.group}><div className="nav-group-title">{group.group}</div>
        {group.items.map(item => <button key={item.id} className={`nav-link ${page === item.id ? 'active' : ''}`} aria-current={page === item.id ? 'page' : undefined} onClick={() => { setPage(item.id); setMobileMenu(false) }}><item.icon size={17} strokeWidth={1.6} /><span>{item.label}</span>{item.id === 'developer' && pending > 0 && <span className="nav-badge">{pending}</span>}</button>)}
      </div>)}</nav>
    </aside>
    <main className="platform-main"><header className="platform-topbar"><div className="topbar-title"><button className="mobile-menu icon-button" aria-label="打开导航" onClick={() => setMobileMenu(true)}><Menu size={20} /></button><span>{label}</span>{page === 'developer' && <span className="topbar-subtitle">技能新建、调试、上线全链路管理</span>}</div><div className="topbar-actions"><PlatformAccount /></div></header>
      <div className="platform-content" key={actor.id || "platform"}>{page === 'developer' ? <DeveloperPage /> : page === 'knowledge' ? <KnowledgePage /> : page === 'skills' ? <SkillsPage /> : <section className="module-placeholder"><h1>{label}</h1><div className="surface placeholder-body"><Layers3 size={36} /><h2>该模块暂未开放</h2><p>当前可使用开发者中心创建和调试 Skill。</p><button className="button primary" onClick={() => setPage('developer')}>进入开发者中心</button></div></section>}</div>
    </main>
    <KnowledgeProcessingWorker /><FloatingAssistant key={actor.id || "platform"} />
  </div></ErrorBoundary>
}
