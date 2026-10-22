import test from 'node:test'
import assert from 'node:assert/strict'
import { runRealtimeDebug, downloadRealtimeDocument, mountedDebugFiles } from '../src/api/realtimeDebug.ts'
import { saveBlobs, readBlob } from './fixtures/resourceStorage.mjs'
import { useAuthStore } from '../src/stores/authStore.ts'
import { useKnowledgeStore } from '../src/stores/knowledgeStore.ts'

const item = { id:'realtime-test', name:'联调技能', buildId:'current-build', resourceIds:[], uploadedResources:[] }
const input = { conversation:'生成登录测试用例', documents:[], documentText:'' }
const excelBytes = new Uint8Array([0x50,0x4b,3,4,10,20,30,40])
const excel = () => new Response(excelBytes, { headers:{'content-type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','content-disposition':"attachment; filename*=UTF-8''%E6%B5%8B%E8%AF%95%E7%94%A8%E4%BE%8B.xlsx"} })
const json = (value, status=200) => Response.json(value,{status})

test('真实调试按multipart提交原始文档与资源，使用run_id认证下载Excel并保存字节', async()=>{
 const original=globalThis.fetch, knowledge=useKnowledgeStore.getState().knowledgeBases
 try{
  const resource=new File(['挂载脚本'],'check.py'), document=new File(['真实需求'],'需求.txt')
  await saveBlobs([{key:'resource:realtime-script',blob:resource}])
  useKnowledgeStore.setState({knowledgeBases:[{id:'real-kb',files:[{id:'kb-file',name:'规范.md',sampleContent:'规范原文'}]}]})
  const calls=[]
  useAuthStore.getState().setSession({token:'test-token-only',username:'tester',alias:'测试'})
  globalThis.fetch=async(path,options)=>{
   calls.push({path,options})
   return calls.length===1 ? json({status:'completed',run_id:'run/一',document:{format:'xlsx',test_case_count:1}}) : excel()
  }
  const result=await runRealtimeDebug({...item,resourceIds:['real-kb'],uploadedResources:[{id:'realtime-script',name:'check.py',size:resource.size,lastModified:1}]},{...input,documents:[{id:'doc',name:'需求.txt'}]},'# Skill 定义',[{id:'doc',file:document}])
  assert.equal(calls[0].path,'/realtime-test-case-gen/generate')
  assert.equal(calls[0].options.headers.token,'test-token-only')
  const form=calls[0].options.body
  assert.ok(form instanceof FormData)
  assert.equal(form.get('skill_definition'),'# Skill 定义')
  assert.equal(form.get('conversation_input'),input.conversation)
  assert.equal(await form.get('documents').text(),'真实需求')
  assert.deepEqual(await Promise.all(form.getAll('mounted_resources').map(file=>file.text())),['挂载脚本','规范原文'])
  assert.equal(calls[1].path,'/realtime-test-case-gen/runs/run%2F%E4%B8%80/document')
  assert.equal(calls[1].options.headers.token,'test-token-only')
  assert.equal(result.origin,'backend');assert.equal(result.buildId,item.buildId)
  assert.equal(result.artifact.name,'测试用例.xlsx');assert.equal(result.artifact.format,'Excel')
  assert.equal(result.artifact.count,1)
  assert.deepEqual(new Uint8Array(await (await readBlob(result.artifact.key)).arrayBuffer()),excelBytes)
 }finally{globalThis.fetch=original;useAuthStore.getState().setSession(null);useKnowledgeStore.setState({knowledgeBases:knowledge})}
})

test('HTTP200的后端超时错误不会变成成功，缺少run_id不请求下载',async()=>{
 const original=globalThis.fetch
 try{
  let requests=0
  globalThis.fetch=async()=>{requests++;return json({code:'999999',status:'failure',message:'422: 在线调试超时（180 秒）',data:null})}
  await assert.rejects(runRealtimeDebug(item,input,'# 定义',[]),/180 秒/)
  assert.equal(requests,1)
  globalThis.fetch=async()=>json({status:'success',data:{}})
  await assert.rejects(runRealtimeDebug(item,input,'# 定义',[]),/run_id/)
 }finally{globalThis.fetch=original}
})

test('下载失败保留运行编号，可只重试GET下载，不重复生成',async()=>{
 const original=globalThis.fetch
 try{
  let generation=0,downloads=0
  globalThis.fetch=async(path)=>{
   if(path.endsWith('/generate')) {generation++;return json({status:'success',data:{run_id:'retry-run'}})}
   downloads++;return downloads===1 ? json({message:'文档尚未就绪'},503) : excel()
  }
  const result=await runRealtimeDebug(item,input,'# 定义',[])
  assert.equal(result.runId,'retry-run');assert.equal(result.artifact,undefined);assert.match(result.documentError,/未就绪/)
  assert.equal((await downloadRealtimeDocument(result.runId,item.name)).format,'Excel')
  assert.equal(generation,1);assert.equal(downloads,2)
 }finally{globalThis.fetch=original}
})

test('鉴权失败、JSON错误和伪装的Excel不能保存为可下载结果',async()=>{
 const original=globalThis.fetch
 try{
  globalThis.fetch=async()=>json({message:'unauthorized'},401)
  await assert.rejects(downloadRealtimeDocument('run',item.name),/token/)
  globalThis.fetch=async()=>json({status:'failure',message:'结果不存在'})
  await assert.rejects(downloadRealtimeDocument('run',item.name),/结果不存在/)
  globalThis.fetch=async()=>new Response('不是Excel',{headers:{'content-type':'application/octet-stream'}})
  await assert.rejects(downloadRealtimeDocument('run',item.name),/Excel/)
 }finally{globalThis.fetch=original}
})

test('文档超量、原文件缺失及挂载资源超量时在发请求前阻止提交',async()=>{
 const original=globalThis.fetch
 try{
  globalThis.fetch=async()=>{throw new Error('不应发出请求')}
  await assert.rejects(runRealtimeDebug(item,{...input,documents:Array.from({length:11},(_,i)=>({id:String(i)}))},'# 定义',[]),/10/)
  await assert.rejects(runRealtimeDebug(item,{...input,documents:[{id:'missing',name:'丢失.txt'}]},'# 定义',[]),/重新选择/)
  await assert.rejects(mountedDebugFiles({...item,resourceIds:['missing-kb']}),/原文件/)
  await assert.rejects(mountedDebugFiles({...item,buildOrigin:'backend',build:{files:[{path:'scripts/missing.py'}]}}),/原文件/)
  const rows=Array.from({length:21},(_,i)=>({id:`many-${i}`,name:`${i}.txt`,lastModified:1}))
  await saveBlobs(rows.map(row=>({key:`resource:${row.id}`,blob:new Blob(['file'])})))
  await assert.rejects(mountedDebugFiles({...item,uploadedResources:rows}),/20/)
 }finally{globalThis.fetch=original}
})
