import { Fragment, useEffect, useRef, useState } from 'react'
import { Plus } from 'lucide-react'
import SkillClassDeleteDialog from './SkillClassDeleteDialog'
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
import type { SkillClassDetail, SkillClassPage, TestStage } from '@/types/skillClass'

export function SkillClassStageBar({ stages, selectedId, total, onSelect }: {
  stages: (TestStage & { count: number })[]; selectedId: string; total?: number; onSelect: (id: string) => void
}) {
  return <nav className="skill-class-stage-bar" aria-label="按测试阶段筛选技能大类">
    <button className={selectedId === '' ? 'active' : ''} aria-pressed={selectedId === ''} onClick={() => onSelect('')}>全部 <b>{total ?? '—'}</b></button>
    {stages.map((stage, index) => <Fragment key={stage.id}>
      <span aria-hidden="true" className={index === 0 || stage.code === 'support' ? 'skill-class-stage-divider' : 'skill-class-stage-arrow'}>{index !== 0 && stage.code !== 'support' ? '›' : null}</span>
      <button data-stage={stage.code} className={selectedId === stage.id ? 'active' : ''} aria-pressed={selectedId === stage.id} onClick={() => onSelect(stage.id)}>{stage.name}<b>{stage.count}</b></button>
    </Fragment>)}
  </nav>
}

export default function SkillClassPanel({ onNewImplementation }: { onNewImplementation: (row: SkillClassDetail) => Promise<void> }) {
  const actor = useAccessStore(state => state.actor.id)
  const catalog = useSkillClassCatalog()
  const [stageId,setStageId] = useState(''), [page,setPage] = useState(1)
  const [result,setResult] = useState<SkillClassPage>(), [loading,setLoading] = useState(true), [busy,setBusy] = useState(false), [error,setError] = useState('')
  const [form,setForm] = useState<{ existing?: SkillClassDetail; stageId: string }>()
  const [detail,setDetail] = useState<SkillClassDetail>(), [deleting,setDeleting] = useState<SkillClassDetail>()
  const [deleteError,setDeleteError] = useState('')
  const [publishError,setPublishError] = useState<string>()
  const [publishTarget,setPublishTarget] = useState<SkillClassDetail>()
  const active = useRef(true)
  const listRequest = useRef<AbortController | null>(null)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  useEffect(() => { setForm(undefined); setDetail(undefined); setDeleting(undefined); setPublishError(undefined); setPublishTarget(undefined); setStageId(''); setPage(1); setResult(undefined) },[actor])
  useEffect(() => {
    const controller = new AbortController()
    listRequest.current = controller
    setLoading(true); setError('')
    void listSkillClasses(stageId,page,controller.signal).then(data => { if(!controller.signal.aborted){setResult(data);setPage(data.page)} })
      .catch(reason => {if(!controller.signal.aborted)setError((reason as Error).message)})
      .finally(() => {if(!controller.signal.aborted)setLoading(false)})
    return () => controller.abort()
  },[stageId,page,catalog.version,actor])
  function acceptMutation(row: SkillClassDetail) {
    // 保存/发布响应已确认最新修订号；在途列表快照不能再覆盖它。
    listRequest.current?.abort()
    setResult(current => current ? { ...current, items: current.items.flatMap(item => {
      if (item.id !== row.id) return [item]
      return !stageId || String(row.test_stage_id) === stageId ? [row] : []
    }) } : current)
  }
  async function inspect(row: SkillClassDetail, edit = false) {
    const account = skillAccount(); setBusy(true);setError('')
    try { const current = await getSkillClass(row.id); if(active.current && skillAccount()===account){if(edit)setForm({existing:current,stageId:''});else setDetail(current)} }
    catch(reason){if(active.current && skillAccount()===account)setError((reason as Error).message)}
    finally{if(active.current && skillAccount()===account)setBusy(false)}
  }
  function saved(row: SkillClassDetail) {
    acceptMutation(row)
    setForm(undefined);useSkillClassStore.getState().invalidate()
    const outside = stageId && String(row.test_stage_id)!==stageId
    toast.success(`大类「${row.name}」草稿已保存${outside ? `至${row.test_stage_name}` : ''}，发布后生效`)
  }
  function requestPublish(row: SkillClassDetail) {
    if (!row.output_description?.trim()) { setForm({ existing: row, stageId: '' }); return }
    setPublishTarget(row)
  }
  async function publish(row: SkillClassDetail) {
    if (busy) return
    const account = skillAccount(); setBusy(true); setError(''); setPublishError(undefined)
    try { const saved = await publishSkillClass(row); if (active.current && account === skillAccount()) { setPublishTarget(undefined); acceptMutation(saved); setDetail(current => current?.id === saved.id ? saved : current); useSkillClassStore.getState().invalidate(); toast.success(`大类「${saved.name}」已发布`) } }
    catch (reason) { if (active.current && account === skillAccount()) {
      setPublishTarget(undefined)
      if ((reason as Error).message.includes('输出描述')) setForm({ existing: row, stageId: '' })
      else setPublishError((reason as Error).message)
    } }
    finally { if (active.current && account === skillAccount()) setBusy(false) }
  }
  async function requestDelete(row: SkillClassDetail) {
    const account = skillAccount(); setBusy(true); setError('')
    try {
      const current = await getSkillClass(row.id)
      if (active.current && skillAccount() === account) {
        setDeleting(current); setDeleteError(current.delete_disabled_reason || '')
      }
    } catch (reason) { if (active.current && skillAccount() === account) setError((reason as Error).message) }
    finally { if (active.current && skillAccount() === account) setBusy(false) }
  }
  async function confirmDelete() {
    if(!deleting || !deleting.can_delete)return
    const account=skillAccount();setBusy(true);setDeleteError('')
    try{await removeSkillClass(deleting);if(active.current&&skillAccount()===account){toast.success(`大类「${deleting.name}」已删除`);setDeleting(undefined);useSkillClassStore.getState().invalidate()}}
    catch(reason){if(active.current&&skillAccount()===account)setDeleteError((reason as Error).message)}
    finally{if(active.current&&skillAccount()===account)setBusy(false)}
  }
  const stages=result?.summary.stages ?? catalog.stages.map(row=>({...row,count:0}))
  return <section className="surface skill-class-panel" aria-label="技能大类管理">
    <div className="section-heading"><div className="skill-class-heading"><h2>技能大类</h2><p className="helper-text">大类即契约：统一入参与出参，团队基于大类提交自己的实现</p></div><div className="section-actions"><button className="button primary" disabled={busy} onClick={()=>setForm({stageId})}><Plus size={16}/>新建技能大类</button></div></div>
    <SkillClassStageBar stages={stages} selectedId={stageId} total={result?.summary.total} onSelect={id=>{setStageId(id);setPage(1)}}/>
    {error&&<p className="error-banner" role="alert">{error}</p>}
    <div className="implementation-table-wrap"><table className="implementation-table skill-class-table"><thead><tr>{['大类名称','测试阶段','功能说明','实现','维护人','更新','操作'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{result?.items.map(row=><tr key={row.id}>
      <td><strong>{row.name}</strong>{row.is_mine&&<span className="skill-class-mine">我创建</span>}</td><td><TestStageBadge name={row.test_stage_name} code={row.test_stage_code}/></td><td><p className="skill-class-summary" title={row.description}>{row.description||'未填写'}</p></td><td>{row.implementation_count}</td><td>{row.maintainer_name}</td><td>{row.updated_time?new Date(row.updated_time).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit'}).replace(/\//g,'-'):'—'}</td><td><div className="table-actions"><button className="button small" disabled={busy} onClick={()=>void inspect(row)}>详情</button>{row.publication_status==='PUBLISHED'&&!row.has_unpublished_changes&&row.can_create_implementation&&<button className="button small" disabled={busy} onClick={()=>{setBusy(true);void onNewImplementation(row).catch(reason=>setError((reason as Error).message)).finally(()=>{if(active.current)setBusy(false)})}}>新建实现</button>}{row.can_publish&&<button className="button small primary" disabled={busy} onClick={()=>requestPublish(row)}>发布</button>}{row.is_mine&&<button className="button small skill-class-delete" title={row.delete_disabled_reason||'删除大类'} disabled={busy} onClick={()=>void requestDelete(row)}>删除</button>}</div></td>
    </tr>)}{(!result?.items.length||loading)&&<tr><td colSpan={7} className="empty-table">{loading?'正在查询技能大类…':'该阶段暂无技能大类，可点击右上角新建'}</td></tr>}</tbody></table></div>
    <div className="skill-class-statistics"><span>共 {result?.summary.total ?? 0} 个大类 · 覆盖 {result?.summary.covered_stages ?? 0}/{stages.length} 个测试阶段{stageId&&` · 当前筛选「${stages.find(row=>row.id===stageId)?.name||''}」`}</span>{!!result?.summary.unassigned&&<span>{result.summary.unassigned} 个历史大类尚未配置阶段</span>}</div>
    <ListPagination total={result?.total??0} page={result?.page??1} pages={result?.pages??1} label="技能大类分页" busy={loading||busy} onPageChange={setPage}/>
    {form&&<SkillClassFormDialog existing={form.existing} defaultStageId={form.stageId} onClose={()=>setForm(undefined)} onSaved={saved}/>}
    {detail&&<SkillClassDetailDialog row={detail} busy={busy} error={error} onClose={()=>{setDetail(undefined);setError('')}} onEdit={()=>{setError('');setDetail(undefined);setForm({existing:detail,stageId:''})}}/>}
    {deleting&&<SkillClassDeleteDialog row={deleting} busy={busy} error={deleteError} onClose={()=>setDeleting(undefined)} onConfirm={()=>void confirmDelete()}/>}
    {publishTarget&&<Dialog title="确认发布技能大类" busy={busy} onClose={()=>{if(!busy)setPublishTarget(undefined)}} footer={<><button className="button" disabled={busy} onClick={()=>setPublishTarget(undefined)}>取消</button><button className="button primary" disabled={busy} onClick={()=>void publish(publishTarget)}>{busy?'正在发布…':'确认发布'}</button></>}><p>是否确认发布技能大类“{publishTarget.name}”？</p><p className="helper-text">发布后所有人可见，并可基于此契约创建具体技能。</p></Dialog>}
    {publishError&&<Dialog title="发布未完成" onClose={()=>setPublishError(undefined)} footer={<button className="button primary" onClick={()=>setPublishError(undefined)}>我知道了</button>}><p role="alert">{publishError}</p></Dialog>}
  </section>
}
