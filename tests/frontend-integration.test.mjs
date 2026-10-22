import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { buildMockArchive, downloadSkillArchive, renderSkillMarkdown, restoreSkillUploads } from '../src/api/skillArchive.ts'
import { generateSkill, validateInput, runSandbox } from '../src/api/developer.ts'
import { useAuthStore } from '../src/stores/authStore.ts'
import { useKnowledgeStore, migrateKnowledgeState, filterKnowledgeBases, assertKnowledgeMounts } from '../src/stores/knowledgeStore.ts'
import { saveBlobs, readBlob, downloaded } from './fixtures/resourceStorage.mjs'
import { skillDefinition } from '../src/lib/skillDefinition.ts'
import { deleteDraft, publishSkill, saveOnlineChanges, takeSkillOffline } from '../src/api/developerLifecycle.ts'
import { migrateDeveloperState, useDeveloperStore } from '../src/stores/developerStore.ts'
import { useAccessStore } from '../src/stores/accessStore.ts'
import { actorApplications, assertApplications, canEditKnowledge, canViewKnowledge, demoActors } from '../src/lib/access.ts'
import { searchKnowledgeBases } from '../src/api/knowledge.ts'
import { mountKnowledge } from '../src/api/knowledgeMount.ts'
import { skillCatalog } from '../src/lib/skillCatalog.ts'
import { createAssistantRequest, replyWithDemo } from '../src/api/assistant.ts'
const form = (changes={}) => ({ classId:'SKILL-CASE-001',name:`验收${crypto.randomUUID()}`,technicalName:'acceptance',system:'核心系统',team:'',version:'99.9.9',modelTier:'standard',description:'验收描述',instructions:'读取需求，生成用例',resourceIds:[],knowledgeBases:[],uploadedResources:[],applicationIds:['ATPM'],...changes })
const kbForm = (changes={}) => ({name:`验收知识${crypto.randomUUID()}`,version:'V99.0.0',description:'验收规范',tag:'通识类',team:'',scope:'public',applicationIds:['*'],vectorized:false,model:'',files:[{id:crypto.randomUUID(),name:'规则.md',size:4,lastModified:1,sampleContent:'规则'}],...changes})
async function unpack(blob) {
 const output=execFileSync('python',['-c','import sys,io,zipfile,json,base64; z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())); assert z.testzip() is None; print(json.dumps({n:base64.b64encode(z.read(n)).decode() for n in z.namelist()}))'],{input:Buffer.from(await blob.arrayBuffer())})
 return Object.fromEntries(Object.entries(JSON.parse(output)).map(([name,bytes])=>[name,Buffer.from(bytes,'base64')]))
}
test('创建与保存修改使用系统版本，客户端填入的版本不能覆盖；所有修改仅允许本人',async()=>{
 const before=useDeveloperStore.getState().implementations, store=useDeveloperStore.getState()
 try {
  const first=store.save(form())
  assert.equal(first.version,'1.0.0')
  assert.equal(first.creatorId,'he')
  const next=store.save({...first,description:'更新',version:'100.0.0'},first.id)
  assert.equal(next.version,'1.0.1')
  useAccessStore.getState().setActor('li')
  assert.throws(()=>store.save(next,next.id),/只有创建者/)
  assert.throws(()=>store.patch(next.id,{creatorId:'li'}),/只有创建者/)
  assert.throws(()=>store.remove(next.id),/只有创建者/)
  await assert.rejects(deleteDraft(next),/只有创建者/)
  await assert.rejects(publishSkill(next),/只有创建者/)
  useAccessStore.getState().setActor('he')
  store.patch(next.id,{creatorId:'li'}); assert.equal(useDeveloperStore.getState().implementations[0].creatorId,'he')
  assert.equal(await deleteDraft(next),next.id); store.remove(next.id)
  assert.throws(()=>store.save(form(),'missing'),/不存在/)
 } finally {useAccessStore.getState().setActor('he');useDeveloperStore.setState({implementations:before})}
})
test('生成、自测、直接上线及刷新闭环，失败/超时/旧构建/迟到上线响应均不能发布',async()=>{
 const before=useDeveloperStore.getState().implementations, store=useDeveloperStore.getState()
 try {
  const first=store.save(form()); const built=await buildMockArchive(first,{references:[],scripts:[]})
  store.patch(first.id,{...built,status:'调试中'})
  let item=useDeveloperStore.getState().implementations[0]
  for(const scenario of ['failed','timeout']) {const debug=await runSandbox(item,'转账需求',30,scenario);assert.equal(debug.status,scenario);await assert.rejects(publishSkill({...item,debug}),/调试通过/)}
  const debug=await runSandbox(item,'转账需求',30,'passed')
  assert.ok(debug.artifact.count<=10)
  assert.match(await (await readBlob(debug.artifact.key)).text(),/前端模拟/)
  await assert.rejects(publishSkill({...item,debug:{...debug,buildId:'old'}}),/当前构建/)
  store.patch(item.id,{debug});item=useDeveloperStore.getState().implementations[0]
  const reply=await publishSkill(item)
  assert.throws(()=>store.applyPublication({...reply,buildId:'old'}),/过期/)
  store.patch(item.id,{debug:undefined});assert.throws(()=>store.applyPublication(reply),/过期/)
  store.patch(item.id,{debug});store.applyPublication(reply)
  await useDeveloperStore.persist.rehydrate()
  assert.equal(useDeveloperStore.getState().implementations[0].status,'已上线')
  assert.throws(()=>store.applyPublication(reply),/过期/)
  const real={...item,backendSkillId:'server',buildOrigin:'backend'}
  await assert.rejects(publishSkill(real),/尚未接入/)
  assert.throws(()=>validateInput(item,{conversation:'',documentText:'旧粘贴框',documents:[]}),/至少提供一项/)
  validateInput(item,{conversation:'',documentText:'',documents:[{id:'document'}]})
 }finally{useDeveloperStore.setState({implementations:before})}
})
test('上线技能修改后转为草稿，需重新调试后才能再次上线',async()=>{
 const before=useDeveloperStore.getState().implementations, store=useDeveloperStore.getState()
 try {
  const own=store.save(form());store.patch(own.id,{status:'已上线',buildOrigin:'mock'})
  const online=useDeveloperStore.getState().implementations[0]
  const changes=await saveOnlineChanges(online,{...online,description:'更新后的定义',version:'999.0.0'},[online])
  store.patch(online.id,changes)
  const current=useDeveloperStore.getState().implementations[0]
  assert.equal(current.version,'1.0.1');assert.equal(current.description,'更新后的定义');assert.equal(current.status,'草稿');assert.equal(current.pendingChanges,undefined)
  await downloadSkillArchive(current);const zip=await unpack(downloaded.blob);assert.match(zip['SKILL.md'].toString(),/更新后的定义/)
  await assert.rejects(takeSkillOffline(current),/当前不是已上线/)
  store.patch(current.id,{status:'调试中'})
  const rerun=await runSandbox(useDeveloperStore.getState().implementations[0],'更新后的需求',30,'passed')
  store.patch(current.id,{debug:rerun})
  store.applyPublication(await publishSkill(useDeveloperStore.getState().implementations[0]))
  const published=useDeveloperStore.getState().implementations[0]
  store.patch(published.id,await takeSkillOffline(published));const offline=useDeveloperStore.getState().implementations[0]
  assert.equal(offline.status,'已下线');await assert.rejects(publishSkill(offline),/未上线的调试版本/)
  const draft=store.save(offline,offline.id);assert.equal(draft.version,'1.0.2');assert.equal(draft.debug,undefined)
  await assert.rejects(saveOnlineChanges({...current,status:'已上线',backendSkillId:'real'},current,[]),/接口尚未接入/)
  await assert.rejects(takeSkillOffline({...current,status:'已上线',backendSkillId:'real'}),/接口尚未接入/)
 }finally{useDeveloperStore.setState({implementations:before})}
})
test('ZIP完整保存知识库与分类资源字节，原文件可从浏览器恢复，旧包不会随知识库修改',async()=>{
 const before=useKnowledgeStore.getState().knowledgeBases
 try {
  const kb=useKnowledgeStore.getState().save(kbForm())
  const script=new File(['print("check")'],'check.py'), template=new File(['template'],'template.md')
  const item={...form({resourceIds:[kb.id],resourceUsage:'规则校验',version:'1.0.0'}),id:'archive',uploadedResources:[{id:'script',name:script.name,size:script.size,lastModified:script.lastModified,category:'脚本'},{id:'template',name:template.name,size:template.size,lastModified:template.lastModified,category:'模板'}]}
  const build=await buildMockArchive(item,{scripts:[{id:'script',file:script}],references:[{id:'template',file:template}]})
  useKnowledgeStore.getState().save({...kb,description:'新规则',changeSummary:'更新知识说明'},kb.id)
  await downloadSkillArchive({...item,...build});const zip=await unpack(downloaded.blob)
  assert.equal(zip['scripts/check.py'].toString(),'print("check")');assert.equal(zip['templates/template.md'].toString(),'template')
  assert.equal(JSON.parse(zip['manifest.json']).knowledgeBases[0].version,'V1.0.0')
  const restored=await restoreSkillUploads(item);assert.equal(restored.scripts[0].file.name,'check.py')
  assert.equal(await restored.references[0].file.text(),'template')
  await assert.rejects(buildMockArchive(item,{references:[],scripts:[]}),/原文件缺失/)
 }finally{useKnowledgeStore.setState({knowledgeBases:before})}
})
test('Markdown定义保存同步技能与ZIP，系统覆盖版本字段，旧调试失效且只能本人编辑',async()=>{
 const before=useDeveloperStore.getState().implementations, store=useDeveloperStore.getState()
 try{
  const item=store.save(form());const build=await buildMockArchive(item,{references:[],scripts:[]})
  store.patch(item.id,{...build,status:'调试中',debug:{id:'old',buildId:build.buildId,status:'passed',input:'需求',output:'ok'}})
  const md='---\nname: edited\nversion: "999.0.0"\n---\n\n# 修改定义\n新增幂等约束'
  await store.saveDefinition(item.id,md)
  const current=useDeveloperStore.getState().implementations[0]
  assert.equal(current.version,'1.0.1');assert.equal(current.debug,undefined);assert.match(current.skillMarkdown,/新增幂等约束/)
  assert.match(current.skillMarkdown,/version: "1.0.1"/);assert.doesNotMatch(current.skillMarkdown,/999/)
  await downloadSkillArchive(current);const zip=await unpack(downloaded.blob);assert.equal(zip['SKILL.md'].toString(),renderSkillMarkdown(current))
  assert.match(current.instructions,/新增幂等约束/)
  const regular = store.save({...current, instructions:'# 新指令\n补充金额边界',description:'表单更新说明'},current.id)
  assert.match(renderSkillMarkdown(regular),/补充金额边界/);assert.match(renderSkillMarkdown(regular),/表单更新说明/);assert.doesNotMatch(renderSkillMarkdown(regular),/新增幂等约束/)
  useAccessStore.getState().setActor('li');await assert.rejects(store.saveDefinition(item.id,md),/只有创建者/)
 }finally{useAccessStore.getState().setActor('he');useDeveloperStore.setState({implementations:before})}
})
test('真实生成保留原附件供独立调试服务和刷新恢复使用，采用服务器返回的版本',async()=>{
 const original=globalThis.fetch
 try{
  const file=new File(['真实上传的需求原文'],'需求.md')
  const item={...form({resourceUsage:'读取需求'}),backendSkillId:'real-cache',uploadedResources:[{id:'cached-real-resource',name:file.name,size:file.size,lastModified:file.lastModified,category:'参考资料'}]}
  useAuthStore.getState().setSession({token:'test-only-token',username:'test',alias:'测试'})
  globalThis.fetch=async()=>Response.json({status:'success',data:{build_id:'server-build',version:'1.0.0',name:'actual-skill'}})
  const built=await generateSkill(item,{references:[{id:'cached-real-resource',file}],scripts:[]})
  assert.equal(built.version,'1.0.0');assert.equal(built.backendVersion,'1.0.0')
  assert.equal(await (await readBlob('resource:cached-real-resource')).text(),'真实上传的需求原文')
  assert.equal((await restoreSkillUploads(item)).references[0].file.name,'需求.md')
 }finally{globalThis.fetch=original;useAuthStore.getState().setSession(null)}
})
test('旧示例缺少挂载原文件时仍可保存定义，保留资源引用并使旧ZIP和调试失效',async()=>{
 const before=useDeveloperStore.getState().implementations,store=useDeveloperStore.getState()
 try{
  const original=before.find(row=>row.id==='impl-core')
  const edited={...original,debug:{id:'previous-debug',buildId:original.buildId,status:'passed',input:'登录',output:'ok'}}
  useDeveloperStore.setState({implementations:[edited]})
  await store.saveDefinition(edited.id,'# 登录用例\n验证正确账号和密码能够登录。')
  const current=useDeveloperStore.getState().implementations[0]
  assert.equal(current.version,'1.8.3')
  assert.deepEqual(current.resourceIds,original.resourceIds)
  assert.match(renderSkillMarkdown(current),/验证正确账号和密码/)
  assert.notEqual(current.buildId,original.buildId)
  assert.equal(current.debug,undefined)
  await assert.rejects(downloadSkillArchive(current),/原文件/)
  await assert.rejects(publishSkill(current),/调试通过/)
  const uploaded={...current,id:'missing-upload',resourceIds:[],uploadedResources:[{id:'missing-source',name:'原始脚本.py',size:100,lastModified:1}]}
  useDeveloperStore.setState({implementations:[uploaded]})
  await store.saveDefinition(uploaded.id,'# 保留附件编辑\n更新执行步骤。')
  const saved=useDeveloperStore.getState().implementations[0]
  assert.equal(saved.uploadedResources[0].name,'原始脚本.py')
  await assert.rejects(downloadSkillArchive(saved),/原文件缺失/)
 }finally{useDeveloperStore.setState({implementations:before})}
})
test('旧数据迁移保留资源、所有者与发布记录，移除审批；不会按原团队把私有库授予他人',()=>{
 const base={...form(),id:'legacy',classId:'SKILL-API-003',status:'待审批',buildId:'old',debug:{status:'passed'},approval:{},uploadedResources:[{id:'old-file',name:'a.py',size:3}]}
 const migrated=migrateDeveloperState({implementations:[base,{...base,id:'online',status:'已上线'}]})
 assert.equal(migrated.implementations[0].classId,'SKILL-POINT-005');assert.equal(migrated.implementations[0].status,'调试中')
 assert.equal(migrated.implementations[0].debug,undefined);assert.equal(migrated.implementations[0].approval,undefined)
 assert.deepEqual(migrated.implementations[0].uploadedResources,base.uploadedResources);assert.equal(migrated.implementations[1].status,'已上线')
 const old={...kbForm(),id:'unknown-owner',scope:'team',creatorId:undefined,history:[]}
 const knowledge=migrateKnowledgeState({knowledgeBases:[old]})
 assert.equal(knowledge.knowledgeBases[0].creatorId,'legacy-unassigned');assert.equal(canViewKnowledge(knowledge.knowledgeBases[0],demoActors[0]),false)
 const known=migrateKnowledgeState({knowledgeBases:[{...old,history:[{maintainer:'李明'}]}]})
 assert.equal(known.knowledgeBases[0].creatorId,'li')
})
test('个人权限：全量应用可选，公开库人人可挂载，但编辑仅限创建者；私有库仅本人可见',async()=>{
 const before=useKnowledgeStore.getState().knowledgeBases
 try{
  assert.deepEqual(actorApplications(demoActors[0]),actorApplications(demoActors[3]));assertApplications(['信用卡系统'],demoActors[0]);assert.throws(()=>assertApplications(['未登记应用']),/已有的应用/)
  const pub=useKnowledgeStore.getState().save(kbForm({name:'权限公开库'})),priv=useKnowledgeStore.getState().save(kbForm({name:'权限私有库',scope:'team'}))
  useAccessStore.getState().setActor('li')
  assert.equal(canEditKnowledge(pub,useAccessStore.getState().actor),false)
  assert.deepEqual(filterKnowledgeBases([pub,priv],'权限').map(row=>row.id),[pub.id])
  const found=await searchKnowledgeBases('权限','测试一组',new AbortController().signal,true)
  assert.ok(found.items.some(row=>row.id===pub.id));assert.ok(!found.items.some(row=>row.id===priv.id))
  assert.throws(()=>assertKnowledgeMounts([priv.id]),/可见范围/)
  assert.throws(()=>useKnowledgeStore.getState().save({...pub,changeSummary:'他人修改'},pub.id),/只有创建者/)
 }finally{useAccessStore.getState().setActor('he');useKnowledgeStore.setState({knowledgeBases:before})}
})
test('知识库初建文件必输、版本自动递增，维护与历史只读；按变更文档处理并防止旧任务覆盖',async()=>{
 const before=useKnowledgeStore.getState().knowledgeBases, store=useKnowledgeStore.getState()
 try{
  assert.throws(()=>store.save(kbForm({files:[]})),/至少上传/)
  const base=kbForm({processingOutcome:'failure'}),first=store.save(base)
  assert.equal(first.version,'V1.0.0');assert.equal(first.processingStatus,'知识处理中')
  store.finishProcessing(first.id,'stale');assert.equal(useKnowledgeStore.getState().knowledgeBases[0].processingStatus,'知识处理中')
  store.finishProcessing(first.id,first.processingJobId);assert.equal(useKnowledgeStore.getState().knowledgeBases[0].processingStatus,'知识处理失败')
  useAccessStore.getState().setActor('li');assert.throws(()=>store.retry(first.id),/没有重试/)
  useAccessStore.getState().setActor('he');store.retry(first.id)
  const retry=useKnowledgeStore.getState().knowledgeBases[0];store.finishProcessing(first.id,retry.processingJobId)
  const done=useKnowledgeStore.getState().knowledgeBases[0]
  assert.throws(()=>store.save(done,done.id),/变更摘要/)
  const metadata=store.save({...done,version:'V999.0.0',description:'改说明',changeSummary:'补充描述'},done.id)
  assert.equal(metadata.version,'V1.0.1');assert.equal(metadata.processingStatus,'知识处理完成')
  const replacement={...metadata.files[0],id:'new-file',lastModified:2}
  const next=store.save({...metadata,files:[replacement],creatorId:'li',changeSummary:'替换规则文档'},first.id)
  assert.equal(next.creatorId,'he');assert.deepEqual(next.processedFileIds,['new-file']);assert.equal(next.history.length,3)
  store.finishProcessing(first.id,retry.processingJobId);assert.equal(useKnowledgeStore.getState().knowledgeBases[0].processingStatus,'知识处理中')
  await useKnowledgeStore.persist.rehydrate();store.finishProcessing(first.id,next.processingJobId)
  assert.equal(useKnowledgeStore.getState().knowledgeBases[0].processingStatus,'知识处理完成')
 }finally{useKnowledgeStore.setState({knowledgeBases:before})}
})
test('知识库挂载仅能修改本人技能；多目标失败不部分写入，挂载成功递增版本并使旧构建失效',async()=>{
 const ds=useDeveloperStore.getState(),ks=useKnowledgeStore.getState(), beforeD=ds.implementations,beforeK=ks.knowledgeBases
 try{
  const kb=ks.save(kbForm()),own=ds.save(form())
  useAccessStore.getState().setActor('li');const other=ds.save(form());useAccessStore.getState().setActor('he')
  await assert.rejects(mountKnowledge(kb.id,[own.id,other.id],'检索规则'),/只有创建者/)
  assert.equal(useDeveloperStore.getState().implementations.find(row=>row.id===own.id).resourceIds.length,0)
  assert.equal(await mountKnowledge(kb.id,[own.id],'检索规则'),1)
  const updated=useDeveloperStore.getState().implementations.find(row=>row.id===own.id)
  assert.equal(updated.version,'1.0.1');assert.equal(updated.knowledgeBases[0].id,kb.id);assert.equal(updated.debug,undefined)
  assert.equal(await mountKnowledge(kb.id,[own.id],'检索规则'),0)
 }finally{useAccessStore.getState().setActor('he');useDeveloperStore.setState({implementations:beforeD});useKnowledgeStore.setState({knowledgeBases:beforeK})}
})
test('技能中心保留上线/下线记录；助手只加载上线，全量目录不按用户裁剪',()=>{
 const rows=[{...form(),id:'one',status:'已上线'},{...form(),id:'two',status:'已下线'},{...form(),id:'three',status:'草稿'}]
 assert.equal(skillCatalog(rows).length,2);assert.equal(skillCatalog(rows,true).length,1)
 useAccessStore.getState().setActor('zhang');assert.equal(skillCatalog(rows).length,2);useAccessStore.getState().setActor('he')
 const real={buildOrigin:'backend',buildId:'old',build:{build_id:'old',version:'1.0.0',source:{display_name:'原名称',instructions:'原指令'},files:[]},name:'后来名称',instructions:'后来指令'}
 assert.equal(Object.fromEntries(skillDefinition(real))['执行指令'],'原指令');assert.equal(skillDefinition({...real,buildId:'new'}),null)
})
test('助手按轮上传文件，已加载Skill名称描述输入输出进入消息快照；取消不会产生晚到回复',async()=>{
 const file=new File(['需求'],'需求.txt'), skills=[{id:'skill',name:'用例技能',description:'生成用例',input:'需求',output:'用例'}]
 const first=createAssistantRequest([],'生成用例',[file],skills)
 skills[0].description='后续编辑';assert.equal(first.skills[0].description,'生成用例')
 const history=[{id:'one',role:'user',text:'生成用例',attachments:['需求.txt'],skills:first.skills},{id:'two',role:'assistant',text:'请补充约束'}]
 const second=createAssistantRequest(history,'继续',[],[])
 assert.equal(second.files.length,0);assert.equal(second.messages[0].attachments,undefined);assert.equal(second.messages[0].skills,undefined)
 const abort=new AbortController(),pending=replyWithDemo(first,abort.signal);abort.abort();await assert.rejects(pending,{name:'AbortError'})
 assert.match(await replyWithDemo(second,new AbortController().signal),/第 2 轮/)
})
