// 手动联调：真实前端函数 + localhost 代理 + 本地 SQLite，不在普通 npm test 中运行。
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { login, ensureSkill, readBuild, downloadBuild } from '../src/api/skillClient.ts'
import { generateSkill } from '../src/api/developer.ts'
import { useAuthStore } from '../src/stores/authStore.ts'
import { skillDefinition } from '../src/lib/skillDefinition.ts'

const base = new URL(process.env.SKILL_VERIFY_BASE_URL ?? 'http://127.0.0.1:5174')
if (!['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)) throw new Error('只能验证本机联调服务')
const output = process.env.SKILL_VERIFY_OUTPUT_DIR
if (!output) throw new Error('请通过 scripts/verify-skill-live.mjs 运行')
const originalFetch = globalThis.fetch
const originalCreateObjectURL = URL.createObjectURL
const requests = []
let capturedBlob, downloadName, downloadClicked = false
globalThis.fetch = (url, options) => {
  const target = new URL(url, base)
  assert.equal(target.origin, base.origin)
  requests.push({ method: options?.method ?? 'GET', path: target.pathname })
  return originalFetch(target, options)
}
// 只替代浏览器下载点击，网络和返回 Blob 均来自真实接口。
globalThis.document = { createElement: () => ({ set href(value) {}, set download(value) { downloadName = value }, click() { downloadClicked = true } }) }
globalThis.window = { setTimeout: (callback, ms) => { const timer = setTimeout(callback, ms); timer.unref(); return timer } }
URL.createObjectURL = blob => { capturedBlob = blob; return originalCreateObjectURL(blob) }
const records = [], created = []
try {
  const health = await (await fetch('/health')).json()
  assert.equal(health.mode, 'local-skill-integration', '目标必须是本项目隔离联调服务')
  await login(process.env.SKILL_VERIFY_USERNAME ?? 'skill-dev', process.env.SKILL_VERIFY_PASSWORD ?? 'SkillLocal2026!')
  await mkdir(output, { recursive: true })
  const samples = [
    new File(['# 业务规则\n余额不足时拒绝转账。\n'], 'business-rules.md', { type: 'text/markdown' }),
    new File([Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=', 'base64')], 'flow.png', { type: 'image/png' }),
    new File(['raise RuntimeError("must not execute")\n'], 'check.py', { type: 'text/plain' }),
  ]
  for (const file of samples) await writeFile(path.join(output, file.name), Buffer.from(await file.arrayBuffer()))
  for (const scenario of ['plain', 'resources']) {
    let item = { id: crypto.randomUUID(), classId: 'SKILL-CASE-001', name: `无知识库联调-${scenario}-${crypto.randomUUID().slice(0, 8)}`, technicalName: '', system: '核心系统', team: '测试一组', modelTier: 'standard', status: '草稿', updatedAt: new Date().toISOString(), description: '按业务规则生成测试用例，适用于功能测试设计。', version: '0.3.0', instructions: '读取需求，生成正向、异常与边界场景；缺关键规则时列出待补充项。', compatibility: '', resourceIds: [], knowledgeBases: [], uploadedResources: [], resourceUsage: '' }
    const files = scenario === 'resources' ? samples : []
    item.uploadedResources = files.map(file => ({ id: crypto.randomUUID(), name: file.name, size: file.size, lastModified: file.lastModified }))
    item.resourceUsage = files.length ? '生成前读取业务规则和流程图；check.py 用于运行端校验，本次仅保存。' : ''
    const backendSkillId = await ensureSkill(item)
    created.push(backendSkillId)
    item = { ...item, backendSkillId, backendAccount: useAuthStore.getState().session.username }
    const uploads = { references: files.filter(file => !file.name.endsWith('.py')).map(file => ({ id: file.name, file, usage: '' })), scripts: files.filter(file => file.name.endsWith('.py')).map(file => ({ id: file.name, file, usage: '' })) }
    const generated = await generateSkill(item, uploads)
    item = { ...item, ...generated }
    const queried = await readBuild(item)
    assert.deepEqual(queried.source.knowledge_base_ids, [])
    assert.equal(queried.source.description, item.description)
    assert.equal(queried.version, item.version)
    assert.equal(queried.source.instructions, item.instructions)
    const definition = Object.fromEntries(skillDefinition({ ...item, build: queried,
      name: '后来修改的草稿名称', description: '后来修改的草稿描述', version: '9.9.9',
      instructions: '后来修改的指令', resourceIds: ['mock-kb'], knowledgeBases: [{ id: 'mock-kb', name: '示例知识库' }],
      uploadedResources: [{ id: 'later', name: 'later.png' }] }))
    assert.equal(definition['技能名称'], queried.source.display_name)
    assert.equal(definition['描述'], queried.source.description)
    assert.equal(definition['版本号'], queried.version)
    assert.equal(definition['执行指令'], queried.source.instructions)
    assert.equal(definition['挂载知识库'], '无')
    assert.ok(!definition['资源文件'].includes('later.png'))
    const expected = scenario === 'plain' ? ['SKILL.md'] : ['SKILL.md', 'assets/flow.png', 'references/business-rules.md', 'scripts/check.py']
    assert.deepEqual(queried.files.map(file => file.path).sort(), expected.sort())
    capturedBlob = undefined; downloadClicked = false
    await downloadBuild(item)
    assert.ok(downloadClicked && capturedBlob)
    assert.equal(downloadName, `${queried.name}.zip`)
    await writeFile(path.join(output, `${scenario}.zip`), Buffer.from(await capturedBlob.arrayBuffer()))
    await writeFile(path.join(output, `${scenario}-manifest.json`), JSON.stringify(queried, null, 2))
    records.push({ scenario, skill_id: backendSkillId, build_id: queried.build_id, files: expected, zip: `${scenario}.zip`, status: 'passed' })
  }
  assert.ok(!requests.some(row => row.path.startsWith('/knowledge-bases')))
} finally {
  for (const id of created) {
    const response = await fetch(`/skills/${id}`, { method: 'DELETE', headers: { token: useAuthStore.getState().session.token } })
    assert.equal((await response.json()).status, 'success')
  }
  useAuthStore.getState().setSession(null)
  globalThis.fetch = originalFetch
  URL.createObjectURL = originalCreateObjectURL
}
const report = { status: 'passed', transport: 'frontend-functions-through-5174-proxy', knowledge_base_ids: [], browser_session_modified: false, download_click: 'test DOM; ZIP bytes from real HTTP', cleanup: 'test skills soft-deleted', scenarios: records, requests }
await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2))
console.log(JSON.stringify({ status: report.status, scenarios: records.map(row => row.scenario), output }, null, 2))
