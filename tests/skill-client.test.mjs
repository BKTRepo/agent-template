import test from 'node:test'
import assert from 'node:assert/strict'
import { buildSkill, checkSkillName, ensureSkill, readSkillDefinition, saveSkillDefinition, SkillApiError } from '../src/api/skillClient.ts'
import { useAuthStore } from '../src/stores/authStore.ts'
import { searchKnowledgeBases } from '../src/api/knowledge.ts'

const item = { technicalName: 'skill-test', name: '测试技能', classId: 'SKILL-CASE-001', system: '核心系统', applicationIds:['核心系统'], team: '测试一组', modelTier: 'standard', version: '0.1.0', backendVersion:'1.0.1', description: '测试技能', instructions: '生成用例', resourceIds: ['real-kb'], knowledgeBases: [{ id: 'real-kb', source: 'backend' }], resourceUsage: '先读取规范；运行脚本校验结果', backendSkillId: 'test-skill', uploadedResources:[{id:'r',name:'ref.md',category:'模板'},{id:'s',name:'check.py',category:'脚本'}] }
const session = { token: 'test-only-token', username: 'test', alias: '测试用户' }
const response = data => new Response(JSON.stringify({ status: 'success', data }), { headers: { 'Content-Type': 'application/json' } })
test('定稿表单提交技能大类应用和按上传顺序排列的分类，版本按服务器校验', async () => {
  useAuthStore.getState().setSession(session)
  const original = globalThis.fetch
  let captured
  globalThis.fetch = async (url, options) => { captured = { url, ...options }; return response({ build_id: 'build' }) }
  try {
    await buildSkill(item, { references: [{ id: 'r', file: new File(['ref'], 'ref.md') }], scripts: [{ id: 's', file: new File(['code'], 'check.py') }] })
    assert.equal(captured.url, '/skills/form/builds')
    const source = JSON.parse(captured.body.get('source'))
    assert.deepEqual(source.knowledge_base_ids, ['real-kb'])
    assert.equal(source.skill_id, 'test-skill')
    assert.equal(source.skill_name, item.name)
    assert.equal(source.resource_usage, item.resourceUsage)
    assert.equal(source.instructions, item.instructions)
    assert.equal(source.name, undefined)
    assert.equal(source.description, item.description)
    assert.equal(source.version, item.version)
    assert.equal(source.skill_class_id,item.classId)
    assert.equal(source.application,'核心系统')
    assert.deepEqual(source.resource_categories,['template','script'])
    assert.equal(source.expected_version,'1.0.1')
    assert.equal(source.team,undefined)
    assert.equal(captured.headers.token, session.token)
    assert.equal(captured.headers['Content-Type'], undefined)
    assert.deepEqual(captured.body.getAll('files').map(file => file.name), ['ref.md', 'check.py'])
    await assert.rejects(buildSkill({ ...item, knowledgeBases: [{ id: 'real-kb', source: 'mock' }] }, { references: [], scripts: [] }), SkillApiError)
  } finally { globalThis.fetch = original }
})

test('无附件也使用同一合同，后端字段错误返回八项表单', async () => {
  useAuthStore.getState().setSession(session)
  const original = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/skills/form/builds')
    assert.equal(options.body.getAll('files').length, 0)
    return response({ build_id: 'plain' })
  }
  try {
    await buildSkill({ ...item, resourceIds: [], resourceUsage: '' }, { references: [], scripts: [] })
    globalThis.fetch = async () => new Response(JSON.stringify({ status: 'failure', data: { missing_fields: [{ field: 'resource_usage', reason: '缺少说明' }], errors: [{ field: 'skill_name', reason: '名称错误' }] } }))
    await assert.rejects(buildSkill(item, { references: [], scripts: [] }), error => error.fields.resourceUsage === '缺少说明' && error.fields.name === '名称错误')
    useAuthStore.getState().setSession(null)
    globalThis.fetch = async () => { throw new Error('未登录不应发送请求') }
    await assert.rejects(buildSkill(item, { references: [], scripts: [] }), /请先登录/)
  } finally { globalThis.fetch = original }
})
test('复用知识库搜索参数，真实空结果不展示示例，401清除平台会话', async () => {
  useAuthStore.getState().setSession(session)
  const original = globalThis.fetch
  let url
  globalThis.fetch = async request => { url = request; return response([]) }
  try {
    const result = await searchKnowledgeBases('  交易  ', '测试一组', new AbortController().signal)
    assert.equal(url, '/knowledge-bases/?search=%E4%BA%A4%E6%98%93')
    assert.equal(result.demo, false)
    assert.deepEqual(result.items, [])
    globalThis.fetch = async () => new Response('{}', { status: 401 })
    await searchKnowledgeBases('', '测试一组', new AbortController().signal)
    assert.equal(useAuthStore.getState().session, null)
  } finally { globalThis.fetch = original }
})
test('真实Markdown查询与保存使用后端定义接口和服务器版本，版本冲突原样提示', async()=>{
 useAuthStore.getState().setSession(session)
 const original=globalThis.fetch
 try{
  const real={...item,buildOrigin:'backend',buildId:'old-build'}
  globalThis.fetch=async(url,options)=>{
   assert.equal(url,'/skills/test-skill/definition')
   assert.equal(options.headers.token,session.token)
   if(options.method==='PUT'){
    assert.deepEqual(JSON.parse(options.body),{markdown:'# 新指令',expected_version:'1.0.1'})
    return response({build_id:'new-build',version:'1.0.2'})
   }
   return response({build:{build_id:'old-build'},markdown:'---\nname: actual\n---\n实际定义',version:'1.0.1'})
  }
  assert.match((await readSkillDefinition(real)).markdown,/实际定义/)
  assert.equal((await saveSkillDefinition(real,'# 新指令')).version,'1.0.2')
  globalThis.fetch=async()=>new Response(JSON.stringify({status:'failure',data:{errors:[{field:'expected_version',reason:'技能已被修改，请刷新后重试'}]}}))
  await assert.rejects(saveSkillDefinition(real,'# 新指令'),/技能已被修改/)
 }finally{globalThis.fetch=original;useAuthStore.getState().setSession(null)}
})
test('名称预检查传编辑ID，创建时重名错误回到名称字段，无会话不请求', async () => {
  useAuthStore.getState().setSession(session)
  const original = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    const query = new URL(url, 'http://test')
    assert.equal(query.pathname, '/skills/name-availability')
    assert.equal(query.searchParams.get('name'), '中文技能')
    assert.equal(query.searchParams.get('exclude_id'), 'owned-skill')
    assert.equal(options.headers.token, session.token)
    return response({ available: false })
  }
  try {
    assert.deepEqual(await checkSkillName('中文技能', 'owned-skill'), { available: false })
    globalThis.fetch = async () => new Response(JSON.stringify({ status: 'failure', data: { errors: [{ field: 'skill_name', reason: '名称已存在' }] } }))
    await assert.rejects(ensureSkill({ ...item, backendSkillId: undefined }), error => error.fields.name === '名称已存在')
    useAuthStore.getState().setSession(null)
    globalThis.fetch = async () => { throw new Error('无会话不请求') }
    await assert.rejects(checkSkillName('中文技能'), /请先登录/)
  } finally { globalThis.fetch = original }
})
