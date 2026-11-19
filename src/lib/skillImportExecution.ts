import { stageSkillImport, confirmSkillImport, restartSkillImport, getSkillImport, checkSkillImportNames, type ImportItem } from '@/api/skillImport'
import type { CachedSkill } from './skillImportLocal'

/** Upload-time format validation/extraction. This endpoint never creates DB records. */
export async function validateCachedSkill(source: CachedSkill, isCurrent = () => true): Promise<CachedSkill> {
  try {
    if (!isCurrent()) throw new Error('账号已变更，已停止当前上传。')
    const staged = await stageSkillImport(source.files,source.mode,source.archiveRoot,source.skillId ? source.baseImportId ?? source.receipt?.importId : undefined)
    if (!isCurrent()) throw new Error('账号已变更，已停止当前上传。')
    if (staged.items.length !== 1) throw new Error('无法唯一确定技能目录，请分别选择技能文件夹重试。')
    const item = staged.items[0]
    if (!item.valid) throw new Error(item.errors.join('；') || '不符合Skill标准格式。')
    return {...source,validated:true,uploaded:true,status:'READY',errors:[],fileCount:item.attachments.length+1,
      receipt:{importId:staged.import_id,itemId:item.item_id},skillId:item.skill_id ?? source.skillId,revision:source.revision ?? item.revision}
  } catch (error) {
    return {...source,validated:false,uploaded:false,status:'FAILED',errors:[(error as Error).message || '上传校验失败，请重试。']}
  }
}

export async function checkCachedSkillNames(rows: CachedSkill[], cache?: Map<string,string[]>, isCurrent = () => true) {
  const selected = rows.filter(row => row.validated && row.receipt)
  const keys = selected.map(row => row.name.trim().normalize('NFKC').trim().toLowerCase())
  const errors: Record<string,string[]> = {}
  await Promise.all(selected.map(async (row,index) => {
    const messages: string[] = []
    if (!row.name.trim()) messages.push('请填写技能名称。')
    else {
      if (keys.filter(key => key === keys[index]).length > 1) messages.push('本次导入中存在重名技能，请修改。')
      const key = `${row.receipt!.importId}:${row.receipt!.itemId}:${row.name.trim()}:${row.revision ?? ''}`
      let remote = cache?.get(key)
      if (!remote) {
        if (!isCurrent()) return
        try {
          const checked = await checkSkillImportNames(row.receipt!.importId,[{item_id:row.receipt!.itemId,name:row.name.trim()}])
          remote = checked.errors[row.receipt!.itemId] ?? []
          cache?.set(key,remote)
        } catch (error) { remote = [(error as Error).message || '名称校验失败，请重试。'] }
      }
      messages.push(...remote)
    }
    if (messages.length) errors[row.id] = messages
  }))
  return errors
}

/** Start only commits already validated temporary receipts. */
export async function executeCachedSkill(source: CachedSkill, onProgress: (row: CachedSkill) => void, isCurrent = () => true): Promise<CachedSkill> {
  let row = {...source,errors:[] as string[]}
  let submitted = false
  function guard() { if (!isCurrent()) throw new Error('账号已变更，已停止当前导入。') }
  function accept(item: ImportItem): CachedSkill {
    return {...row,status:'SUCCEEDED',errors:[],skillId:item.skill_id ?? row.skillId,revision:item.revision ?? row.revision,
      fileCount:item.attachments.length + 1,uploaded:true}
  }
  try {
    guard()
    if (!row.name.trim()) throw new Error('请填写技能名称。')
    if (!row.classId || !row.application) throw new Error('请选择所属大类和所属应用。')
    if (!row.validated || !row.uploaded) throw new Error('请先上传文件并通过Skill格式校验。')
    if (!row.receipt) throw new Error('缺少导入回执，请重新选择文件。')
    if (row.skillId) {
      guard()
      await restartSkillImport(row.receipt.importId)
      guard()
      if (!row.revision) throw new Error('缺少原技能版本信息，请重新打开原草稿后重试。')
    }
    guard()
    submitted = true
    onProgress(row)
    const result = await confirmSkillImport(row.receipt.importId,[{item_id:row.receipt.itemId,name:row.name.trim(),class_id:Number(row.classId),application_paso:row.application,
      ...(row.skillId ? {expected_revision:row.revision} : {})}])
    guard()
    const item = result.items.find(item => item.item_id === row.receipt?.itemId)
    if (item?.status !== 'SUCCEEDED') throw new Error(item?.errors.join('；') || '导入未完成，请重试。')
    return accept(item)
  } catch (error) {
    if (submitted && row.receipt && isCurrent()) {
      try {
        const status = await getSkillImport(row.receipt.importId)
        const item = status.items.find(item => item.item_id === row.receipt?.itemId)
        if (item?.status === 'SUCCEEDED') return accept(item)
      } catch { /* Retain the receipt so a retry cannot create the same draft again. */ }
    }
    return {...row,status:'FAILED',errors:[(error as Error).message || '导入失败，请重试。']}
  }
}
