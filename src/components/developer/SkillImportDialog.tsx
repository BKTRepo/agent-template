import { useEffect, useRef, useState } from 'react'
import { Upload, CheckCircle2, AlertCircle, FolderOpen, LoaderCircle, X } from 'lucide-react'
import Dialog from './Dialog'
import SearchSelect from './SearchSelect'
import { getDeveloperMetadata, type DeveloperMetadata } from '@/api/developerCenter'
import { getImportLimits, readDroppedSkills, discardSkillImport, type ImportLimits, type ImportUpload } from '@/api/skillImport'
import { skillAccount } from '@/api/skillSession'
import { useSkillClassStore } from '@/stores/skillClassStore'
import { cacheSkillFiles, mergeCachedSkills, removeCachedSkill, type CachedSkill } from '@/lib/skillImportLocal'
import { executeCachedSkill, validateCachedSkill, checkCachedSkillNames } from '@/lib/skillImportExecution'

const formatBytes = (value: number) => `${(value / 1024 / 1024).toFixed(0)} MiB`

export function SkillImportNavigation({ step, rows, busy, initializing, onStep, onBack, onConfirm, onClose }: {
  step: number; rows: CachedSkill[]; busy: boolean; initializing: boolean
  onStep: (step: number) => void; onBack: () => void; onConfirm: () => void; onClose: () => void
}) {
  return <>
    <span className="skill-import-footer-note">{step === 1 ? '上传时校验并临时暂存，通过校验的技能可进入下一步' : step === 2 ? '确认归属和名称后开始导入；返回修改会保存到原技能' : '可返回上一步修改同一条技能'}</span>
    {step > 1 && <button className="button" disabled={busy} onClick={onBack}>上一步</button>}
    {step === 1 && <button className="button primary" disabled={busy || initializing || !rows.some(row => row.validated)} onClick={() => onStep(2)}>下一步</button>}
    {step === 2 && <button className="button primary" disabled={busy || !rows.some(row => row.validated)} onClick={onConfirm}>{busy ? <><LoaderCircle size={16} className="spin" />正在导入…</> : '开始导入'}</button>}
    {step === 3 && <button className="button primary" disabled={busy} onClick={onClose}>完成</button>}
  </>
}

export default function SkillImportDialog({ onClose, onImported, onOpen }: { onClose: () => void; onImported: () => Promise<void>; onOpen: (id: number) => Promise<void> }) {
  const classCatalogVersion = useSkillClassStore(state => state.version)
  const [step, setStep] = useState(1)
  const [rows, setRows] = useState<CachedSkill[]>([])
  const [limits, setLimits] = useState<ImportLimits>()
  const [metadata, setMetadata] = useState<DeveloperMetadata>()
  const [busy, setBusy] = useState(false)
  const [initializing, setInitializing] = useState(true)
  const [message, setMessage] = useState('')
  const [progress, setProgress] = useState('')
  const [dragging, setDragging] = useState(false)
  const [nameErrors, setNameErrors] = useState<Record<string,string[]>>({})
  const fileInput = useRef<HTMLInputElement>(null)
  const folderInput = useRef<HTMLInputElement>(null)
  const previousRows = useRef<CachedSkill[]>([])
  const active = useRef(true)
  const account = useRef(skillAccount()).current
  const isCurrent = () => active.current && skillAccount() === account
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  async function initialize() {
    setInitializing(true); setMessage('')
    try {
      const [catalog, rules] = await Promise.all([getDeveloperMetadata(),getImportLimits()])
      if (isCurrent()) { setMetadata(catalog); setLimits(rules) }
    } catch (error) { if (isCurrent()) setMessage((error as Error).message) }
    finally { if (isCurrent()) setInitializing(false) }
  }
  useEffect(() => { void initialize() }, [])
  useEffect(() => {
    let current = true
    const refresh = () => { void getDeveloperMetadata().then(data=>{if(current&&isCurrent())setMetadata(data)}).catch(error=>{if(current&&isCurrent())setMessage((error as Error).message)}) }
    refresh();window.addEventListener('focus',refresh)
    return ()=>{current=false;window.removeEventListener('focus',refresh)}
  },[classCatalogVersion])
  function remember(values: CachedSkill[]) {
    const identities = new Map(previousRows.current.map(row => [row.id,row]))
    // Keep only identity metadata for removed items, never retain their File objects.
    values.forEach(row => { if (row.skillId) identities.set(row.id,{...row,files:[]}) })
    previousRows.current = [...identities.values()]
  }
  function updateRow(row: CachedSkill) { if (isCurrent()) { remember([row]); setRows(previous => previous.map(item => item.id === row.id ? row : item)) } }
  async function addFiles(files: ImportUpload[], directory = false) {
    if (!limits) return
    setBusy(true); setMessage('')
    try {
      const incoming = await cacheSkillFiles(files,directory,limits)
      if (!isCurrent()) return
      remember(rows)
      const previous = [...new Map([...previousRows.current,...rows].map(row => [row.id,row])).values()]
      const merged = mergeCachedSkills(rows,incoming,previous)
      const originals = [...new Set(merged.flatMap(row => row.files.map(file => file.file)))]
      if (merged.length > limits.max_skills || originals.length > limits.max_files || originals.reduce((total,file) => total+file.size,0) > limits.max_batch_bytes) throw new Error(`待导入条目或文件总量超出限制，请减少文件（最多 ${limits.max_skills} 个技能）。`)
      setRows(merged); remember(merged); setStep(1)
      const waiting = merged.filter(row => !row.validated && row.status === 'READY')
      for (let index=0; index<waiting.length; index++) {
        if (!isCurrent()) return
        setProgress(`正在上传并校验 ${index+1}/${waiting.length}：${waiting[index].sourceName}`)
        updateRow(await validateCachedSkill(waiting[index],isCurrent))
      }
    } catch (error) { if (isCurrent()) setMessage((error as Error).message) }
    finally { if (isCurrent()) {setBusy(false);setProgress('')} }
  }
  function discard(values: CachedSkill[]) { for (const id of new Set(values.flatMap(row => row.receipt ? [row.receipt.importId] : []))) void discardSkillImport(id).catch(() => {/* Expired files are also reclaimed by periodic cleanup. */}) }
  function remove(id: string) { remember(rows); discard(rows.filter(row=>row.id===id)); setRows(removeCachedSkill(rows,id)); setMessage('') }
  function clear() { remember(rows);discard(rows);setRows([]);setStep(1);setMessage('') }
  function closeDialog() { discard(rows);onClose() }
  function change(id: string, changes: Partial<CachedSkill>) {
    setRows(previous => previous.map(row => row.id === id ? {...row,...changes,errors:[]} : row))
    setNameErrors(previous => {if(changes.name!==undefined)return {};const next={...previous};delete next[id];return next});setMessage('')
  }
  function goBack() {
    // Keep original skill IDs; navigation never creates new records.
    if (step === 3) setRows(previous => previous.map(row => row.validated ? {...row,status:'READY',errors:[]} : row))
    setStep(step - 1); setMessage('')
    setNameErrors({})
  }
  async function confirm() {
    setBusy(true); setMessage('')
    const pending = rows.filter(row => row.validated && row.status !== 'SUCCEEDED')
    let saved = false
    try {
      const errors=await checkCachedSkillNames(pending,undefined,isCurrent)
      for(const row of pending) if(!row.classId||!row.application) errors[row.id]=[...errors[row.id]??[],'请选择所属大类和所属应用。']
      if(!isCurrent())return
      setNameErrors(errors)
      if(Object.keys(errors).length){setMessage('请处理标注的问题后再开始导入。');return}
      for (let index = 0; index < pending.length; index++) {
        if (!isCurrent()) return
        setProgress(`正在处理 ${index + 1}/${pending.length}：${pending[index].name || pending[index].sourceName}`)
        const result = await executeCachedSkill(pending[index],updateRow,isCurrent)
        if (!isCurrent()) return
        updateRow(result); saved ||= result.status === 'SUCCEEDED'
      }
      if (!isCurrent()) return
      setStep(3)
      if (saved) await onImported()
    } catch (error) { if (isCurrent()) setMessage((error as Error).message) }
    finally { if (isCurrent()) { setBusy(false); setProgress('') } }
  }
  const successful = rows.filter(row => row.status === 'SUCCEEDED')
  const failed = rows.filter(row => row.status !== 'SUCCEEDED')
  const complete = rows.length > 0 && !failed.length
  const steps = <ol className="skill-import-steps" aria-label="导入步骤">{['选择文件','填写信息','完成'].map((label,index) => <li key={label} className={step === index+1 ? 'current' : step > index+1 ? 'complete' : ''} aria-current={step === index+1 ? 'step' : undefined}><span>{step > index+1 ? '✓' : index+1}</span>{label}</li>)}</ol>
  return <Dialog wide className="skill-import-dialog" title="一键导入 Skill" subtitle="上传并校验技能文件，补充归属信息后正式导入，成功后为「草稿」状态" topContent={steps} busy={busy} onClose={closeDialog}
    footer={<SkillImportNavigation step={step} rows={rows} busy={busy} initializing={initializing} onStep={setStep} onBack={goBack} onConfirm={() => void confirm()} onClose={closeDialog}/>}>
    {message && <p role="alert" className="error-banner">{message}</p>}
    {progress && <p role="status" className="skill-import-name-checking">{progress}</p>}
    {initializing && <p role="status">正在加载技能类、应用和上传限制…</p>}
    {!initializing && !metadata && <button className="button" onClick={() => void initialize()}>重新加载配置</button>}
    {step === 1 && <>
      <input ref={fileInput} type="file" accept=".md,.zip" multiple hidden disabled={busy} onChange={event => {const files=Array.from(event.target.files ?? []);event.target.value='';if(files.length) void addFiles(files.map(file => ({file,path:file.name})))}} />
      <input ref={folderInput} type="file" multiple hidden disabled={busy} {...{webkitdirectory:''}} onChange={event => {const files=Array.from(event.target.files ?? []);event.target.value='';if(files.length) void addFiles(files.map(file => ({file,path:file.webkitRelativePath || file.name})),true)}} />
      <div className={`skill-import-drop ${dragging ? 'dragging' : ''}`} aria-busy={busy} onDragOver={event => {event.preventDefault();if(!busy) setDragging(true)}} onDragLeave={() => setDragging(false)} onDrop={event => {
        event.preventDefault();setDragging(false)
        if(busy || !limits) return
        setBusy(true)
        void readDroppedSkills(event.dataTransfer.items,limits.max_files).then(result => {if(isCurrent()) return addFiles(result.files,result.directory)})
          .catch(error => {if(isCurrent()) setMessage((error as Error).message)}).finally(() => {if(isCurrent()) setBusy(false)})
      }}>
        <span className="skill-import-upload-icon"><Upload size={24}/></span><strong>{busy ? '正在上传并校验文件…' : '将技能文件或文件夹拖到这里'}</strong>
        <p>支持 SKILL.md、ZIP 技能包或包含多个技能的文件夹</p>
        <div className="section-actions"><button className="button primary" disabled={busy || !limits} onClick={() => fileInput.current?.click()}>选择文件</button><button className="button" disabled={busy || !limits} onClick={() => folderInput.current?.click()}><FolderOpen size={16}/>选择文件夹</button></div>
        {limits && <small>单文件 ≤ {formatBytes(limits.max_file_bytes)} · 每个技能最多 {limits.max_skill_files - 1} 个附件 · 批次 ≤ {formatBytes(limits.max_batch_bytes)} · 最多 {limits.max_skills} 个技能</small>}
      </div>
      {rows.length > 0 && <div className="skill-import-candidates"><div className="skill-import-queue-heading"><h3>校验结果 · {rows.filter(row=>row.validated).length} 项通过 · {rows.filter(row=>row.validated===false).length} 项未通过</h3><button className="button small" disabled={busy} onClick={clear}>全部清空</button></div>
        {rows.map(row => <article key={row.id}><div><strong>{row.rootPath === '.' ? row.sourceName : row.rootPath}</strong><p>{row.sourceName} · {row.fileCount} 个文件 · {row.validated ? row.skillId ? '校验通过，修改原技能' : '校验通过，已临时暂存' : row.validated===false ? '未通过校验，已拦截' : '等待上传校验'}</p>{row.errors.length>0&&<p role="alert" className="skill-import-name-error">{row.errors.join('；')}</p>}</div><button className="icon-button" aria-label={`移除${row.name}`} title="移出待导入列表" disabled={busy} onClick={() => remove(row.id)}><X size={17}/></button></article>)}
      </div>}
    </>}
    {step === 2 && <section className="skill-import-fill"><div className="skill-import-fill-heading"><h3>技能归属信息</h3><p>名称不可与其他技能重复；点击开始导入后正式保存，返回修改会更新原技能</p></div>
      <div className="skill-import-table-wrap"><table className="skill-import-table"><thead><tr><th>文件</th><th>技能名称 <em>*</em></th><th>所属大类 <em>*</em></th><th>所属应用 <em>*</em></th></tr></thead><tbody>{rows.filter(row=>row.validated).map(row => {
        const locked = busy || row.status === 'SUCCEEDED'
        return <tr key={row.id}><td><strong title={row.sourceName}>{row.sourceName.split('/').pop()}</strong><small className="skill-import-file-size">{(row.sourceSize/1024).toFixed(1)} KB · {row.fileCount} 个文件</small>{row.skillId && <small className="skill-import-file-size">编辑原技能</small>}{row.errors.length > 0 && <p role="alert" className="skill-import-name-error">{row.errors.join('；')}</p>}</td>
          <td><input aria-label={`${row.rootPath}的技能名称`} aria-invalid={!!nameErrors[row.id]?.length} value={row.name} maxLength={128} disabled={locked} onChange={event => change(row.id,{name:event.target.value})}/>{nameErrors[row.id]?.length>0&&<p role="alert" className="skill-import-name-error">{nameErrors[row.id].join('；')}</p>}</td>
          <td><select aria-label={`${row.rootPath}的所属大类`} value={row.classId} disabled={locked} onChange={event => change(row.id,{classId:event.target.value})}><option value="">请选择所属大类</option>{metadata?.skill_classes.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></td>
          <td><SearchSelect label={`${row.rootPath}的所属应用`} value={row.application} disabled={locked}
            options={metadata?.applications ?? []} placeholder="请选择所属应用" required
            onChange={application => change(row.id, { application })} /></td></tr>
      })}</tbody></table></div>
    </section>}
    {step === 3 && <section className="skill-import-results"><div className={`skill-import-completion ${complete ? 'success' : 'partial'}`} role="status"><span className="skill-import-completion-icon">{complete ? <CheckCircle2 size={31}/> : <AlertCircle size={31}/>}</span><h3>{complete ? '导入完成' : '导入结果'}</h3><p>已成功处理 {successful.length} 个技能，状态为草稿。{failed.length > 0 && `另有 ${failed.length} 项未完成，请查看失败原因。`}</p></div>
      <div className="skill-import-statistics"><div><span>成功导入</span><strong className="success">{successful.length}</strong></div><div><span>导入附件</span><strong className="attachments">{successful.reduce((sum,row) => sum+Math.max(0,row.fileCount-1),0)}</strong></div><div><span>未导入</span><strong className={failed.length ? 'pending' : ''}>{failed.length}</strong></div></div>
      <p className="skill-import-completion-note">{successful.length ? '成功条目的归属信息、执行指令和附件已保存，可在「我创建的技能」中查看。返回编辑会覆盖原技能，不会新增一条。' : '本次未保存任何技能，请根据失败原因修改后重试。'}</p>
      <details className="skill-import-result-details" open={!complete}><summary>查看导入明细</summary>{rows.map(row => <article key={row.id}><div><strong>{row.name || row.sourceName}</strong><p>{row.rootPath}</p><p className={row.status === 'FAILED' ? 'skill-import-name-error' : ''} role={row.status === 'FAILED' ? 'alert' : undefined}>{row.status === 'SUCCEEDED' ? '保存成功 · 草稿' : row.errors.join('；') || '尚未完成'}</p></div>{row.skillId && <button className="button small" disabled={busy} onClick={() => {setBusy(true);void onOpen(row.skillId!).catch(error => {if(isCurrent()) setMessage((error as Error).message)}).finally(() => {if(isCurrent()) setBusy(false)})}}>查看草稿</button>}</article>)}</details>
    </section>}
  </Dialog>
}
