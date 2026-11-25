import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Plus } from 'lucide-react'
import Dialog from '../Dialog'
import ListPagination from '@/components/common/ListPagination'
import TestStageBadge from '@/components/skills/TestStageBadge'
import SkillClassFormDialog from './SkillClassFormDialog'
import SkillClassDetailDialog from './SkillClassDetailDialog'
import { getSkillClass, listSkillClasses, removeSkillClass, publishSkillClass } from '@/api/skillClasses'
import { useSkillClassCatalog, useSkillClassStore } from '@/stores/skillClassStore'
import { useAccessStore } from '@/stores/accessStore'
import { skillAccount } from '@/api/skillSession'
import { toast } from '@/lib/toast'
import type { SkillClassDetail, SkillClassPage } from '@/types/skillClass'

export default function SkillClassPanel({ onNewImplementation }: { onNewImplementation: (row: SkillClassDetail) => Promise<void> }) {
  const actor = useAccessStore(state => state.actor.id)
  const catalog = useSkillClassCatalog()
  const [stageId,setStageId] = useState(''), [page,setPage] = useState(1)
  const [result,setResult] = useState<SkillClassPage>(), [loading,setLoading] = useState(true), [busy,setBusy] = useState(false), [error,setError] = useState('')
  const [form,setForm] = useState<{ existing?: SkillClassDetail; stageId: string }>()
  const [detail,setDetail] = useState<SkillClassDetail>(), [deleting,setDeleting] = useState<SkillClassDetail>()
  const [deleteError,setDeleteError] = useState('')
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  useEffect(() => { setForm(undefined); setDetail(undefined); setDeleting(undefined); setStageId(''); setPage(1); setResult(undefined) },[actor])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError('')
    void listSkillClasses(stageId,page,controller.signal).then(data => { if(!controller.signal.aborted){setResult(data);setPage(data.page)} })
      .catch(reason => {if(!controller.signal.aborted)setError((reason as Error).message)})
      .finally(() => {if(!controller.signal.aborted)setLoading(false)})
    return () => controller.abort()
  },[stageId,page,catalog.version,actor])
  async function inspect(row: SkillClassDetail, edit = false) {
    const account = skillAccount(); setBusy(true);setError('')
    try { const current = await getSkillClass(row.id); if(active.current && skillAccount()===account){if(edit)setForm({existing:current,stageId:''});else setDetail(current)} }
    catch(reason){if(active.current && skillAccount()===account)setError((reason as Error).message)}
    finally{if(active.current && skillAccount()===account)setBusy(false)}
  }
  function saved(row: SkillClassDetail) {
    setForm(undefined);useSkillClassStore.getState().invalidate()
    const outside = stageId && String(row.test_stage_id)!==stageId
    toast.success(`大类「${row.name}」草稿已保存${outside ? `至${row.test_stage_name}` : ''}，发布后生效`)
  }
  async function publish(row: SkillClassDetail) {
    const account = skillAccount(); setBusy(true); setError('')
    try { const saved = await publishSkillClass(row); if (active.current && account === skillAccount()) { setDetail(current => current?.id === saved.id ? saved : current); setResult(current => current ? { ...current, items: current.items.map(item => item.id === saved.id ? saved : item) } : current); useSkillClassStore.getState().invalidate(); toast.success(`大类「${saved.name}」已发布`) } }
    catch (reason) { if (active.current && account === skillAccount()) setError((reason as Error).message) }
    finally { if (active.current && account === skillAccount()) setBusy(false) }
  }
  async function confirmDelete() {
    if(!deleting)return
    const account=skillAccount();setBusy(true);setDeleteError('')
    try{await removeSkillClass(deleting);if(active.current&&skillAccount()===account){toast.success(`大类「${deleting.name}」已删除`);setDeleting(undefined);useSkillClassStore.getState().invalidate()}}
    catch(reason){if(active.current&&skillAccount()===account)setDeleteError((reason as Error).message)}
    finally{if(active.current&&skillAccount()===account)setBusy(false)}
  }
  const stages=result?.summary.stages ?? catalog.stages.map(row=>({...row,count:0}))
  return <section className="surface skill-class-panel" aria-label="技能大类管理">
    <div className="section-heading"><div><h2>技能大类</h2><p className="helper-text">统一输入与输出规定，所有用户可基于已发布大类新建自己的实现</p></div><div className="section-actions"><button className="button primary" disabled={busy} onClick={()=>setForm({stageId})}><Plus size={16}/>新建技能大类</button></div></div>
    <nav className="skill-class-stage-bar" aria-label="按测试阶段筛选技能大类"><button className={stageId===''?'active':''} aria-pressed={stageId===''} onClick={()=>{setStageId('');setPage(1)}}>全部 <b>{result?.summary.total ?? '—'}</b></button>{stages.map(stage=><button key={stage.id} className={stageId===stage.id?'active':''} aria-pressed={stageId===stage.id} onClick={()=>{setStageId(stage.id);setPage(1)}}>{stage.name}<b>{stage.count}</b></button>)}</nav>
    {error&&<p className="error-banner" role="alert">{error}</p>}
    <div className="implementation-table-wrap"><table className="implementation-table skill-class-table"><thead><tr>{['大类名称 / 唯一标识','测试阶段','功能说明','实现','维护人','更新','操作'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{result?.items.map(row=><tr key={row.id}>
      <td><strong>{row.name}</strong>{row.is_mine&&<span className="skill-class-mine">我创建</span>}<small className="skill-class-code">{row.class_code}</small><span className={`status-tag ${row.publication_status==='PUBLISHED'?'green':'neutral'}`}>{row.publication_status==='PUBLISHED'?(row.has_unpublished_changes?'已发布 · 有待发布修改':'已发布'):'草稿'}</span></td><td><TestStageBadge name={row.test_stage_name} code={row.test_stage_code}/></td><td><p className="skill-class-summary" title={row.description}>{row.description||'未填写'}</p></td><td>{row.implementation_count}</td><td>{row.maintainer_name}</td><td>{row.updated_time?new Date(row.updated_time).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit'}).replace(/\//g,'-'):'—'}</td><td><div className="table-actions"><button className="button small" disabled={busy} onClick={()=>void inspect(row)}>详情</button>{row.can_create_implementation&&<button className="button small" disabled={busy} onClick={()=>{setBusy(true);void onNewImplementation(row).catch(reason=>setError((reason as Error).message)).finally(()=>{if(active.current)setBusy(false)})}}>新建实现</button>}{row.publication_status==='DRAFT'&&row.can_publish&&<button className="button small primary" disabled={busy} onClick={()=>void publish(row)}>发布</button>}{row.is_mine&&<button className="button small skill-class-delete" title={row.delete_disabled_reason||'删除大类'} disabled={busy||!row.can_delete} onClick={()=>{setDeleteError('');setDeleting(row)}}>删除</button>}</div></td>
    </tr>)}{(!result?.items.length||loading)&&<tr><td colSpan={7} className="empty-table">{loading?'正在查询技能大类…':'该阶段暂无技能大类，可点击右上角新建'}</td></tr>}</tbody></table></div>
    <div className="skill-class-statistics"><span>共 {result?.summary.total ?? 0} 个大类 · 覆盖 {result?.summary.covered_stages ?? 0}/{stages.length} 个测试阶段{stageId&&` · 当前筛选「${stages.find(row=>row.id===stageId)?.name||''}」`}</span>{!!result?.summary.unassigned&&<span>{result.summary.unassigned} 个历史大类尚未配置阶段</span>}</div>
    <ListPagination total={result?.total??0} page={result?.page??1} pages={result?.pages??1} label="技能大类分页" busy={loading||busy} onPageChange={setPage}/>
    {form&&<SkillClassFormDialog existing={form.existing} defaultStageId={form.stageId} onClose={()=>setForm(undefined)} onSaved={saved}/>}
    {detail&&<SkillClassDetailDialog row={detail} busy={busy} error={error} onPublish={()=>void publish(detail)} onClose={()=>{setDetail(undefined);setError('')}} onEdit={()=>{setError('');setDetail(undefined);setForm({existing:detail,stageId:''})}}/>}
    {deleting&&<Dialog title="删除技能大类" subtitle="删除后从有效大类列表移除，本期不提供恢复入口" busy={busy} onClose={()=>setDeleting(undefined)} footer={<><button className="button" disabled={busy} onClick={()=>setDeleting(undefined)}>取消</button><button className="button danger" disabled={busy} onClick={()=>void confirmDelete()}>{busy?'正在删除…':'确认删除'}</button></>}><div className="skill-class-delete-warning"><AlertCircle size={22}/><div><p>即将删除 <strong>{deleting.name}</strong></p><code>{deleting.class_code}</code><p>该大类下没有实现类，删除不会影响已有技能。</p></div></div>{deleteError&&<p className="error-banner" role="alert">{deleteError}</p>}</Dialog>}
  </section>
}
