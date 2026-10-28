// 服务端版本/权限替代旧前端造数流程；此处仅在测试中模拟HTTP边界。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { useAuthStore } from '../src/stores/authStore.ts'
import { useDeveloperStore } from '../src/stores/developerStore.ts'
import { listDeveloperSkills,createDeveloperSkill,updateDeveloperSkill,deleteDeveloperSkill,publishDeveloperSkill,
  getPlatformContext,persistSkillResources } from '../src/api/developerCenter.ts'
import { restoreSkillUploads } from '../src/api/skillArchive.ts'
import { validateInput } from '../src/api/developer.ts'
const session={token:'test-only-token',username:'test',alias:'测试用户'}
const form={classId:'SKILL-CASE-001',name:'测试技能',technicalName:'skill-test',applicationIds:['*'],version:'999.0.0',
  description:'测试描述',instructions:'生成用例',resourceIds:[],uploadedResources:[],resourceUsage:'',revision:2}
const row={id:'server-id',name:'测试技能',class_id:'SKILL-CASE-001',application_ids:['*'],version:'1.0.2',current_revision:3,
  skill_version_id:12,status:'草稿',creator_id:'1',creator_name:'测试用户',updated_at:'2026-10-24T10:00:00',
  description:'测试描述',instructions:'生成用例',resource_ids:[],uploaded_resources:[],knowledge_bases:[]}
const success=data=>Response.json({status:'success',data})
async function mocked(handler,work){
 const original=globalThis.fetch
 useAuthStore.getState().setSession(session);globalThis.fetch=handler
 try{return await work()}finally{globalThis.fetch=original;useAuthStore.getState().setSession(null)}
}

test('开发者中心初始没有前端示例技能，也没有浏览器持久化版本生成器',()=>{
 assert.deepEqual(useDeveloperStore.getState().implementations,[])
 assert.equal(useDeveloperStore.getState().save,undefined)
 assert.equal(useDeveloperStore.persist,undefined)
})
test('创建使用服务器返回的ID和版本，客户端版本不上传',async()=>{
 await mocked(async(url,options)=>{
  assert.equal(url,'/skills/developer/');assert.equal(options.method,'POST')
  const body=JSON.parse(options.body);assert.equal(body.version,undefined);assert.equal(body.creator_id,undefined)
  assert.deepEqual(body.application_ids,['*']);return success(row)
 },async()=>{
  const item=await createDeveloperSkill(form)
  assert.equal(item.id,'server-id');assert.equal(item.version,'1.0.2');assert.equal(item.revision,3);assert.equal(item.skillVersionId,12)
 })
})
test('保存修改携带打开时的revision，后端冲突提示原样显示',async()=>{
 await mocked(async(url,options)=>{
  assert.equal(url,'/skills/developer/server-id');assert.equal(options.method,'PUT')
  assert.equal(JSON.parse(options.body).expected_revision,2)
  return Response.json({status:'failure',message:'技能已被修改，请刷新后重试'},{status:409})
 },async()=>{await assert.rejects(updateDeveloperSkill('server-id',form),/技能已被修改/)})
})
test('删除调用后端接口，不在浏览器伪造删除成功',async()=>{
 await mocked(async(url,options)=>{
  assert.equal(url,'/skills/developer/server-id');assert.equal(options.method,'DELETE')
  return Response.json({status:'failure',message:'只有草稿可以删除'},{status:400})
 },async()=>{await assert.rejects(deleteDeveloperSkill('server-id'),/只有草稿/)})
})
test('上线完全由后端校验，前端passed标签不能代替当前版本通过记录',async()=>{
 await mocked(async()=>Response.json({status:'failure',message:'当前版本尚未取得沙箱调试通过结果，不能上线'},{status:409}),
  async()=>{await assert.rejects(publishDeveloperSkill('server-id'),/不能上线/)})
})
test('刷新通过接口取得列表和目录，空结果保持空白',async()=>{
 await mocked(async(url)=>success(url.includes('metadata')?{skill_classes:[],applications:[]}:[]),async()=>{
  await useDeveloperStore.getState().load()
  assert.deepEqual(useDeveloperStore.getState().implementations,[])
  assert.deepEqual(await listDeveloperSkills(),[])
 })
})
test('平台身份由认证接口返回，无登录表单或退出入口',async()=>{
 await mocked(async(url)=>{assert.equal(url,'/skills/developer/context');return success({id:'1',name:'系统管理员'})},async()=>{
  assert.deepEqual(await getPlatformContext(),{id:'1',name:'系统管理员'})
 })
 const account=readFileSync('src/components/common/PlatformAccount.tsx','utf8')
 assert.doesNotMatch(account,/登录平台|退出登录|type="password"|<Dialog/)
  assert.match(account,/当前团队：/)
  assert.match(account,/<strong>测试一组<\/strong>/)
  assert.match(account,/aria-label="用户头像">何/)
})
test('401与非JSON响应提供明确错误，不当作空列表',async()=>{
 await mocked(async()=>Response.json({},{status:401}),async()=>{
  await assert.rejects(listDeveloperSkills(),/凭证已失效/)
  assert.equal(useAuthStore.getState().session,null)
 })
 await mocked(async()=>new Response('<html>error</html>'),async()=>{
  await assert.rejects(listDeveloperSkills(),/返回格式异常/)
 })
})
test('挂载原文件可从服务器恢复，无需依赖浏览器缓存',async()=>{
 const source={id:'file:1',fileId:1,name:'需求.md',size:6,lastModified:0,category:'参考资料',savedCategory:'参考资料',downloadUrl:'/skills/developer/resources/1/download'}
 await mocked(async(url)=>{assert.equal(url,source.downloadUrl);return new Response('原始需求')},async()=>{
  const restored=await restoreSkillUploads({...form,uploadedResources:[source]})
  assert.equal(await restored.references[0].file.text(),'原始需求')
 })
})
test('新挂载文件先上传并保存用途，表单仅引用服务端文件编号',async()=>{
 const file=new File(['需求'],'new.md');const selected={id:'browser-only',name:file.name,size:file.size,lastModified:0,category:'参考资料'}
 await mocked(async(url,options)=>{
  assert.equal(url,'/skills/developer/resources');assert.ok(options.body instanceof FormData)
  assert.equal(options.headers['Content-Type'],undefined)
  assert.deepEqual(JSON.parse(options.body.get('categories')),['参考资料'])
  return success([{...selected,id:'file:8',fileId:8}])
 },async()=>{
  const saved=await persistSkillResources({...form,resourceUsage:'参考',uploadedResources:[selected]}, {references:[{id:selected.id,file}],scripts:[]})
  assert.equal(saved.uploadedResources[0].fileId,8)
  assert.equal(saved.uploadedResources[0].savedCategory,'参考资料')
 })
})
test('已有挂载不重复上传，保留文件编号',async()=>{
 const source={id:'file:8',fileId:8,name:'需求.md',category:'参考资料',savedCategory:'参考资料'}
 await mocked(async()=>{throw Error('不应上传')},async()=>{
  const saved=await persistSkillResources({...form,uploadedResources:[source]},{references:[],scripts:[]})
  assert.equal(saved.uploadedResources[0].fileId,8)
 })
})
test('调试至少有对话或文件；旧粘贴字段不能代替真实输入',()=>{
 assert.throws(()=>validateInput(form,{conversation:'',documentText:'旧内容',documents:[]}),/至少提供一项/)
 validateInput(form,{conversation:'生成登录用例',documents:[]})
 validateInput(form,{conversation:'',documents:[{id:'document'}]})
})
