// 实际前端API函数 -> 真实TCP -> WRQ真实接口 -> 云数据库；沙箱由本轮Python进程替代。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { useAuthStore } from '../src/stores/authStore.ts'
import { listDeveloperSkills, recordDeveloperDebugResult, publishDeveloperSkill,
  offlineDeveloperSkill, updateDeveloperSkill } from '../src/api/developerCenter.ts'
import { runRealtimeDebug, restoreRealtimeDebug, downloadRealtimeDocument } from '../src/api/realtimeDebug.ts'
import { readBlob } from './fixtures/resourceStorage.mjs'

const config = JSON.parse(await readFile(process.argv[2], 'utf8'))
const base = new URL(config.base)
const token = (await readFile(config.tokenFile, 'utf8')).trim()
const originalFetch = globalThis.fetch
const report = {cases:[],requests:[]}
const input = {conversation:'生成登录测试用例',documents:[],documentText:''}
globalThis.fetch = async (url, options={}) => {
  const target = new URL(url, base)
  assert.equal(target.origin, base.origin, '只允许调用本轮临时服务')
  const response = await originalFetch(target, options)
  report.requests.push({method:options.method ?? 'GET',path:target.pathname,http_status:response.status})
  return response
}
useAuthStore.getState().setSession({token,username:'wrq-cloud-test',alias:'云库验收'})
async function scenario(id, work) {
  try {
    const detail=await work()
    report.cases.push({id,status:'PASSED',detail:detail ?? '实际前端函数与真实HTTP请求验证通过'})
  } catch(error) {
    report.cases.push({id,status:'FAILED',detail:error.message})
  }
}
let item
try {
  item=(await listDeveloperSkills()).find(row=>row.id===config.skillId)
  assert.ok(item,'找不到本轮真实创建的前端测试技能')
  await scenario('F01',async()=>{
    const before=report.requests.length
    let failure,result
    try { result=await runRealtimeDebug(item,input,'# 调试定义',[]) } catch(error) { failure=error }
    const calls=report.requests.slice(before)
    assert.ok(calls.some(row=>row.method==='POST' && row.path==='/realtime-test-case-gen/runs'),
      `未调用POST /runs；实际请求：${calls.map(row=>`${row.method} ${row.path} → ${row.http_status}`).join('；')}；${failure?.message ?? ''}`)
    assert.ok(!calls.some(row=>row.path.endsWith('/generate')),'仍在调用旧/generate')
    assert.equal(result?.status,'passed',failure?.message)
    const registration=calls.findIndex(row=>row.method==='POST' && row.path.endsWith('/debug-runs'))
    const firstPoll=calls.findIndex(row=>row.method==='GET' && row.path.startsWith('/realtime-test-case-gen/runs/') && !row.path.endsWith('/document'))
    assert.ok(registration>=0 && firstPoll>registration,'必须先登记，再查询状态')
    assert.equal(result.versionRegistered,true)
  })
  await scenario('F02',async()=>{
    const before=report.requests.length
    const saved=await recordDeveloperDebugResult(item.id,{id:config.queuedRun,runId:config.queuedRun,
      buildId:config.buildId,input,status:'running',origin:'backend',output:'已取得任务编号，等待执行'})
    assert.ok(report.requests.slice(before).some(row=>row.method==='POST' && row.path.includes('/debug-runs')),
      '运行开始时没有发出版本登记请求')
    assert.ok(saved,'运行开始时登记函数直接返回，未等待后端确认')
  })
  await scenario('F03',async()=>{
    const saved=await recordDeveloperDebugResult(item.id,{id:config.completedRun,runId:config.completedRun,
      buildId:config.buildId,input,status:'passed',origin:'backend',output:'测试沙箱已完成'})
    assert.equal(saved.id,item.id)
    assert.equal(saved.debug.runId,config.completedRun)
    assert.equal(saved.debug.status,'passed')
    assert.equal(saved.skillVersionId,config.versionId)
    item=saved
  })
  await scenario('F04',async()=>{
    const artifact=await downloadRealtimeDocument(config.completedRun,item.name)
    const blob=await readBlob(artifact.key)
    assert.ok(blob?.size>1000,'有效测试Excel应包含真实工作簿内容')
    assert.equal(createHash('sha256').update(Buffer.from(await blob.arrayBuffer())).digest('hex'),config.excelHash)
    assert.equal(artifact.format,'Excel')
    return '实际HTTP下载；SHA256与openpyxl生成的测试工作簿一致；浏览器缓存为测试存储'
  })
  await scenario('F10',async()=>{
    const before=report.requests.length,controller=new AbortController()
    let runId
    await assert.rejects(runRealtimeDebug(item,input,'# 关闭后恢复',[],controller.signal,
      {onProgress:debug=>{runId=debug.runId;controller.abort()}}),{name:'AbortError'})
    const restored=await restoreRealtimeDebug(item)
    assert.equal(restored.runId,runId)
    assert.equal(restored.status,'passed')
    assert.equal(restored.skillVersionId,config.versionId)
    assert.equal(restored.versionRegistered,true)
    assert.equal(report.requests.slice(before).filter(row=>row.method==='POST' && row.path==='/realtime-test-case-gen/runs').length,1)
    return '真实HTTP登记后取消前端查询，再通过latest-run与后端版本关联恢复；未重新创建任务'
  })
  await scenario('F05',async()=>{
    item=await publishDeveloperSkill(item.id)
    assert.equal(item.status,'已上线')
    assert.equal(item.skillVersionId,config.versionId)
  })
  await scenario('F06',async()=>{
    item=await offlineDeveloperSkill(item.id)
    assert.equal(item.status,'已下线')
  })
  await scenario('F07',async()=>{
    item=await publishDeveloperSkill(item.id)
    assert.equal(item.status,'已上线')
    item=await updateDeveloperSkill(item.id,{...item,instructions:'前端API保存的新版指令'})
    assert.equal(item.status,'草稿')
    assert.notEqual(item.skillVersionId,config.versionId)
    assert.equal(item.revision,2)
    assert.equal(item.debug,undefined)
    await assert.rejects(publishDeveloperSkill(item.id),/当前版本|不能上线/)
    return '真实上线→下线→重新上线→修改成草稿；新版借用旧结果被真实后端拒绝'
  })
  await scenario('F08',async()=>{
    await assert.rejects(downloadRealtimeDocument(config.queuedRun,item.name),/未完成/)
  })
  await scenario('F09',async()=>{
    const before=report.requests.length
    const restored=await restoreRealtimeDebug(item)
    assert.equal(restored.isCurrentVersion,false)
    assert.equal(restored.skillVersionId,config.versionId)
    assert.equal(restored.buildId,config.buildId)
    assert.ok(report.requests.slice(before).some(row=>row.path.endsWith('/latest-run')))
    assert.ok(!report.requests.slice(before).some(row=>row.method==='POST'))
    return '保存新版后恢复旧任务：实际GET关联接口确认旧版本，未给当前新版补登记'
  })
} catch(error) {
  report.error={message:error.message}
} finally {
  globalThis.fetch=originalFetch
  useAuthStore.getState().setSession(null)
  await writeFile(config.reportFile,JSON.stringify(report,null,2))
}
console.log(JSON.stringify({frontend_cases:report.cases.map(row=>({id:row.id,status:row.status})),fatal:report.error ?? null}))
if(report.error || report.cases.some(row=>row.status==='FAILED')) process.exitCode=1
