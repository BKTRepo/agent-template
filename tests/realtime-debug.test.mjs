import test from 'node:test'
import assert from 'node:assert/strict'
import { runRealtimeDebug, restoreRealtimeDebug, resumeRealtimeDebug, downloadRealtimeDocument, downloadRealtimeDocuments, mountedDebugFiles, debugPollInterval } from '../src/api/realtimeDebug.ts'
import { recordDeveloperDebugResult } from '../src/api/developerCenter.ts'
import { saveBlobs, readBlob } from './fixtures/resourceStorage.mjs'
import { useAuthStore } from '../src/stores/authStore.ts'

const input={conversation:'生成登录测试用例',documents:[],documentText:''}
const bytes=new Uint8Array([0x50,0x4b,3,4,10,20,30,40])
const excel=()=>new Response(bytes,{headers:{'content-type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','content-disposition':"attachment; filename*=UTF-8''%E6%B5%8B%E8%AF%95.xlsx"}})
const json=(value,status=200)=>Response.json(value,{status})
const success=data=>json({status:'success',data})
let sequence=0
function fixture(changes={}) {
  const item={id:`async-unit-${++sequence}`,name:'联调技能',creatorId:'1',buildId:'build-1',skillVersionId:1,resourceIds:[],uploadedResources:[]}
  const state={status:'queued',registered:false,current:true,buildId:'build-1',versionId:1,failRegister:0,failPoll:0,failDownload:0,auto:true,...changes}
  const runId='run/'+item.id, calls=[]
  const documents=()=>state.status==='completed'?[{filename:'测试.xlsx',format:'xlsx',size_bytes:bytes.length,test_case_count:18,
    download_url:`/realtime-test-case-gen/runs/${encodeURIComponent(runId)}/document?filename=${encodeURIComponent('测试.xlsx')}`,expires_at:'2026-10-29T10:31:15+08:00'}]:[]
  const task=()=>({run_id:runId,skill_id:item.id,debugger:'系统管理员',status:state.status,started_at:null,finished_at:null,error_message:state.status==='failed'?'模型429：额度不足':null,documents:documents()})
  const link=()=>({run_id:runId,skill_id:item.id,build_id:state.buildId,skill_version_id:state.versionId,is_current_version:state.current,version:'1.0.0',task:null})
  const row=()=>({id:item.id,name:item.name,class_id:'class',application_ids:['*'],description:'描述',instructions:'指令',
    resource_ids:[],uploaded_resources:[],knowledge_bases:[],version:'1.0.0',current_revision:1,skill_version_id:1,status:'调试中',
    creator_id:'1',creator_name:'测试',updated_at:'2026-10-26',build_id:state.buildId})
  const handler=async(path,options={})=>{
    const method=options.method || 'GET'
    calls.push({path,method,options})
    if(path==='/realtime-test-case-gen/runs' && method==='POST') return json(task())
    if(path.endsWith('/latest-run')) return json(task())
    if(path===`/skills/developer/${item.id}/debug-runs` && method==='POST') {
      if(state.failRegister-->0) return json({status:'failure',message:'运行记录暂未可见，请稍后重试'},409)
      const body=JSON.parse(options.body)
      state.registered=true;state.buildId=body.build_id;state.versionId=body.skill_version_id ?? 1
      return success(row())
    }
    if(path.startsWith(`/skills/developer/${item.id}/debug-runs/`)) return state.registered ? success(link()) : json({status:'failure',message:'任务尚未关联'},404)
    if(path.includes('/document')) {
      assert.equal(state.status,'completed','未完成时不得请求结果文档')
      if(state.failDownload-->0) return json({message:'文档暂不可下载'},503)
      return excel()
    }
    if(path.startsWith('/realtime-test-case-gen/runs/')) {
      assert.ok(state.registered || state.failRegister>=0,'应先尝试登记')
      if(state.failPoll-->0) return json({message:'查询暂不可用'},503)
      if(state.auto) state.status=state.status==='queued'?'running':'completed'
      return json(task())
    }
    throw new Error(`未声明的请求：${method} ${path}`)
  }
  return {item,state,runId,calls,handler,task}
}
async function use(f,work) {
  const original=globalThis.fetch
  useAuthStore.getState().setSession({token:'test-only-token',username:'tester',alias:'测试'})
  globalThis.fetch=f.handler
  try { return await work() } finally { globalThis.fetch=original;useAuthStore.getState().setSession(null) }
}
const options={pollIntervalMs:1}

test('POST新任务后立即登记冻结版本；queued→running→completed才下载Excel',async()=>{
  const f=fixture(),progress=[]
  await use(f,async()=>{
    const result=await runRealtimeDebug(f.item,input,'# Skill',[],undefined,{...options,onProgress:r=>progress.push(r.status)})
    assert.equal(f.calls[0].path,'/realtime-test-case-gen/runs')
    const register=f.calls.findIndex(c=>c.method==='POST' && c.path.endsWith('/debug-runs'))
    const poll=f.calls.findIndex(c=>c.path.startsWith('/realtime-test-case-gen/runs/') && !c.path.includes('/document'))
    assert.ok(register>0 && register<poll)
    assert.deepEqual(JSON.parse(f.calls[register].options.body),{run_id:f.runId,build_id:'build-1',skill_version_id:1,conversation_input:input.conversation,request_document_count:0})
    assert.deepEqual(progress,['queued','running','passed'])
    assert.equal(result.status,'passed');assert.equal(result.versionRegistered,true);assert.equal(result.isCurrentVersion,true)
    assert.equal(result.artifact.name,'测试.xlsx')
    assert.equal(result.artifacts.length,1);assert.equal(result.artifact.count,18)
    assert.deepEqual(new Uint8Array(await (await readBlob(result.artifact.key)).arrayBuffer()),bytes)
    assert.equal(debugPollInterval,5000)
    assert.ok(!f.calls.some(c=>c.path.endsWith('/generate')))
  })
})

test('原始文档和资源按multipart提交；版本字段只发给我方登记接口',async()=>{
  const f=fixture({status:'completed'}),file=new File(['# 需求'],'需求.md'),script=new File(['print(1)'],'check.py')
  await saveBlobs([{key:'resource:script',blob:script}])
  await use(f,async()=>{
    await runRealtimeDebug({...f.item,uploadedResources:[{id:'script',name:'check.py'}]},
      {...input,documents:[{id:'doc',name:file.name}]},'# 定义',[{id:'doc',file}],undefined,options)
    const form=f.calls[0].options.body
    assert.ok(form instanceof FormData);assert.equal(form.get('skill_definition'),'# 定义')
    assert.equal(form.get('skill_version_id'),null);assert.equal(await form.get('documents').text(),'# 需求')
    assert.equal(await form.get('mounted_resources').text(),'print(1)')
  })
})

test('真实failed任务显示error_message，不转成通过且不请求下载',async()=>{
  const f=fixture({status:'failed'})
  await use(f,async()=>{
    const result=await runRealtimeDebug(f.item,input,'# Skill',[],undefined,options)
    assert.equal(result.status,'failed');assert.match(result.output,/429/)
    assert.ok(!f.calls.some(c=>c.path.includes('/document')))
  })
})

test('关闭查询后找回同一任务，不重新创建；原始版本关联仍有效',async()=>{
  const f=fixture(),controller=new AbortController()
  await use(f,async()=>{
    await assert.rejects(runRealtimeDebug(f.item,input,'# Skill',[],controller.signal,
      {...options,onProgress:()=>controller.abort()}),{name:'AbortError'})
    assert.equal(f.state.registered,true)
    f.state.status='completed'
    const recovered=await restoreRealtimeDebug(f.item,undefined,options)
    assert.equal(recovered.runId,f.runId);assert.equal(recovered.buildId,'build-1')
    assert.ok(f.calls.some(c=>c.path.endsWith('/latest-run')))
    assert.equal(f.calls.filter(c=>c.path==='/realtime-test-case-gen/runs').length,1)
    assert.ok(!f.calls.some(c=>/cancel|delete/i.test(c.path)))
  })
})

test('关闭发生在创建响应时，也完成版本登记，不把关闭当执行失败',async()=>{
  const f=fixture(),controller=new AbortController(),original=f.handler
  f.handler=async(path,opt)=>{const response=await original(path,opt);if(path==='/realtime-test-case-gen/runs') controller.abort();return response}
  await use(f,async()=>{
    await assert.rejects(runRealtimeDebug(f.item,input,'# Skill',[],controller.signal,options),{name:'AbortError'})
    assert.equal(f.state.registered,true)
  })
})

test('状态查询断网保留任务，继续查询不会重启沙箱',async()=>{
  const f=fixture({failPoll:1})
  await use(f,async()=>{
    const result=await runRealtimeDebug(f.item,input,'# Skill',[],undefined,options)
    assert.equal(result.status,'queued');assert.match(result.monitorError,/继续查询/)
    f.state.status='completed'
    const resumed=await resumeRealtimeDebug(f.item,result,undefined,options)
    assert.equal(resumed.status,'passed');assert.equal(resumed.monitorError,undefined)
    assert.equal(f.calls.filter(c=>c.path==='/realtime-test-case-gen/runs').length,1)
  })
})

test('登记失败后刷新，用原始收据补登记旧版，绝不绑定修改后的新版',async()=>{
  const f=fixture({failRegister:1}),controller=new AbortController()
  await use(f,async()=>{
    await assert.rejects(runRealtimeDebug(f.item,input,'# Skill',[],controller.signal,
      {...options,onProgress:()=>controller.abort()}),{name:'AbortError'})
    assert.equal(f.state.registered,false)
    f.state.current=false;f.state.status='completed'
    const restored=await restoreRealtimeDebug({...f.item,buildId:'build-2',skillVersionId:2},undefined,options)
    assert.equal(restored.buildId,'build-1');assert.equal(restored.skillVersionId,1);assert.equal(restored.isCurrentVersion,false)
    assert.equal(f.calls.filter(c=>c.path==='/realtime-test-case-gen/runs').length,1)
    assert.equal(JSON.parse(f.calls.filter(c=>c.method==='POST' && c.path.endsWith('/debug-runs')).at(-1).options.body).build_id,'build-1')
  })
})

test('latest-run没有版本关联时，只能查看，不能用当前版本替它补登记',async()=>{
  const f=fixture({status:'completed'})
  await use(f,async()=>{
    const restored=await restoreRealtimeDebug(f.item,undefined,options)
    assert.equal(restored.isCurrentVersion,false);assert.equal(restored.buildId,'');assert.match(restored.registrationError,/不能作为当前版本/)
    assert.ok(!f.calls.some(c=>c.method==='POST'))
  })
})

test('登记已落库但响应丢失，重新打开只读取原关联，不重复创建或登记',async()=>{
  const f=fixture(),controller=new AbortController(),original=f.handler
  let lost=true
  f.handler=async(path,opt)=>{
    const response=await original(path,opt)
    if(lost && opt?.method==='POST' && path.endsWith('/debug-runs')) {lost=false;throw new TypeError('连接在返回前断开')}
    return response
  }
  await use(f,async()=>{
    await assert.rejects(runRealtimeDebug(f.item,input,'# Skill',[],controller.signal,
      {...options,onProgress:()=>controller.abort()}),{name:'AbortError'})
    assert.equal(f.state.registered,true)
    f.state.status='completed'
    const restored=await restoreRealtimeDebug(f.item,undefined,options)
    assert.equal(restored.versionRegistered,true)
    assert.equal(f.calls.filter(c=>c.path==='/realtime-test-case-gen/runs').length,1)
    assert.equal(f.calls.filter(c=>c.method==='POST' && c.path.endsWith('/debug-runs')).length,1)
  })
})

test('完成时再次核对版本，旧版成功不能短暂显示为当前版本通过',async()=>{
  const f=fixture(),progress=[],original=f.handler
  f.handler=async(path,opt)=>{const response=await original(path,opt);if(f.state.status==='completed') f.state.current=false;return response}
  await use(f,async()=>{
    const result=await runRealtimeDebug(f.item,input,'# Skill',[],undefined,{...options,onProgress:r=>progress.push({...r})})
    assert.equal(result.isCurrentVersion,false)
    assert.ok(!progress.some(r=>r.status==='passed' && r.isCurrentVersion))
  })
})

test('同版本重复点击只创建一个后台任务',async()=>{
  const f=fixture()
  await use(f,async()=>{
    const [a,b]=await Promise.all([runRealtimeDebug(f.item,input,'# Skill',[],undefined,options),runRealtimeDebug(f.item,input,'# Skill',[],undefined,options)])
    assert.equal(a.runId,b.runId);assert.equal(f.calls.filter(c=>c.path==='/realtime-test-case-gen/runs').length,1)
  })
})

test('下载失败保留任务编号，重试下载不创建或重新登记任务',async()=>{
  const f=fixture({status:'completed',failDownload:1})
  await use(f,async()=>{
    const result=await runRealtimeDebug(f.item,input,'# Skill',[],undefined,options)
    assert.equal(result.runId,f.runId);assert.equal(result.artifact,undefined);assert.match(result.documentError,/暂不可下载/)
    await downloadRealtimeDocument(result.runId,f.item.name)
    assert.equal(f.calls.filter(c=>c.path==='/realtime-test-case-gen/runs').length,1)
    assert.equal(f.calls.filter(c=>c.path.includes('/document')).length,2)
  })
})

test('完成响应包含多个documents时，按每项download_url下载并保存',async()=>{
  const f=fixture({status:'completed'})
  const docs=[
    {filename:'登录功能.xlsx',download_url:`/realtime-test-case-gen/runs/${encodeURIComponent(f.runId)}/document?filename=${encodeURIComponent('登录功能.xlsx')}`,test_case_count:8},
    {filename:'权限功能.xlsx',download_url:`/realtime-test-case-gen/runs/${encodeURIComponent(f.runId)}/document?filename=${encodeURIComponent('权限功能.xlsx')}`,test_case_count:10},
  ]
  await use(f,async()=>{
    const artifacts=await downloadRealtimeDocuments(f.runId,f.item.name,docs)
    assert.deepEqual(artifacts.map(row=>row.name),['登录功能.xlsx','权限功能.xlsx'])
    assert.deepEqual(artifacts.map(row=>row.count),[8,10])
    assert.equal(f.calls.filter(c=>c.path.includes('/document?filename=')).length,2)
    assert.notEqual(artifacts[0].key,artifacts[1].key)
  })
})

test('后端错误、缺少任务编号和其他技能任务都拒绝，不下载伪结果',async()=>{
  for(const response of [json({status:'failure',message:'后端超时'}),json({status:'success',data:{}}),json({run_id:'r',skill_id:'other',status:'queued'})]) {
    const f=fixture();f.handler=async()=>response
    await use(f,async()=>{await assert.rejects(runRealtimeDebug(f.item,input,'# Skill',[],undefined,options),/超时|run_id|不属于/)})
  }
})

test('运行中登记函数真实发起登记请求，不要求前端传status',async()=>{
  const f=fixture()
  await use(f,async()=>{
    await recordDeveloperDebugResult(f.item.id,{id:f.runId,runId:f.runId,buildId:'build-1',input,status:'running'})
    assert.equal(f.state.registered,true);assert.equal(JSON.parse(f.calls[0].options.body).status,undefined)
  })
})

test('鉴权、JSON错误及伪装Excel不能保存为可下载结果',async()=>{
  for(const response of [json({message:'unauthorized'},401),json({status:'failure',message:'结果不存在'}),new Response('not excel',{headers:{'content-type':'application/octet-stream'}})]) {
    const f=fixture();f.handler=async()=>response
    await use(f,async()=>{await assert.rejects(downloadRealtimeDocument('r',f.item.name),/token|不存在|Excel/)})
  }
})

test('数量、格式、50MB大小及缺失原文件在创建任务前拦截',async()=>{
  const f=fixture();f.handler=async()=>{throw Error('不应发请求')}
  await use(f,async()=>{
    await assert.rejects(runRealtimeDebug(f.item,{...input,documents:Array.from({length:11},(_,i)=>({id:String(i)}))},'# 定义',[]),/10/)
    await assert.rejects(runRealtimeDebug(f.item,{...input,documents:[{id:'missing',name:'丢失.txt'}]},'# 定义',[]),/重新选择/)
    const file=new File(['x'],'unsupported.exe')
    await assert.rejects(runRealtimeDebug(f.item,{...input,documents:[{id:'doc',name:file.name}]},'# 定义',[{id:'doc',file}]),/格式|支持/)
    const large=new File(['x'],'large.pdf');Object.defineProperty(large,'size',{value:50*1024*1024+1})
    await assert.rejects(runRealtimeDebug(f.item,{...input,documents:[{id:'doc',name:large.name}]},'# 定义',[{id:'doc',file:large}]),/50/)
    await assert.rejects(mountedDebugFiles({...f.item,resourceIds:['missing']}),/原文件/)
  })
})
