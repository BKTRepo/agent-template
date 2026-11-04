import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { useAuthStore } from '../src/stores/authStore.ts'
import { getCatalogMetadata, getCatalogClass, listCatalogSkills, getCatalogSkill, prepareCatalogTest, catalogResourceFiles } from '../src/api/skillCatalog.ts'
import { runRealtimeDebug, restoreRealtimeDebug } from '../src/api/realtimeDebug.ts'

const success = data => Response.json({ status: 'success', data })
const row = changes => ({ id: 101, name: '真实发布实现', class_id: 7, application_ids: ['*'],
  description: '描述', instructions: '发布指令', technical_name: 'published-skill', resource_ids: [],
  resource_usage: '', compatibility: '', knowledge_bases: [], uploaded_resources: [], current_revision: 3,
  skill_version_id: 30, version: '1.0.2', status: '已上线', creator_login_name: 'owner', creator_name: 'owner',
  maintainer_id: 'editor', maintainer_name: 'editor', updated_at: '', build_id: 'published-build', build_origin: 'backend',
  call_count: 0, download_count: 0, skill_markdown: '# Published definition', ...changes })
async function mocked(handler, work) {
  const original = globalThis.fetch
  useAuthStore.getState().setSession({ token: 'test-token', username: 'viewer', alias: 'Viewer' })
  globalThis.fetch = (url, options = {}) => {
    assert.ok(['GET', 'POST'].includes(options.method || 'GET'))
    assert.equal(options.headers.token, 'test-token')
    return handler(new URL(url, 'http://local'), options)
  }
  try { await work() } finally { globalThis.fetch = original; useAuthStore.getState().setSession(null) }
}

test('目录独立读取后端分页与筛选，参数编码且保留真实维护人及真实统计', async () => {
  await mocked(async url => {
    if (url.pathname.endsWith('get-metadata')) return success({ skill_classes: [{ id: 7, name: 'Class', is_enabled: false, description: '' }], applications: [], maintainers: [] })
    if (url.pathname.endsWith('get-class')) { assert.equal(url.searchParams.get('class_id'), '7'); return success({ id: 7, input_schema: null, output_schema: null, template: null }) }
    assert.equal(url.pathname, '/skills/catalog/list-skills')
    assert.equal(url.searchParams.get('name'), '发布 & 中文'); assert.equal(url.searchParams.get('class_id'), '7')
    assert.equal(url.searchParams.get('application'), 'APP A'); assert.equal(url.searchParams.get('maintainer'), 'editor')
    assert.equal(url.searchParams.get('page'), '2')
    return success({ items: [row()], total: 21, page: 2, pages: 2 })
  }, async () => {
    assert.equal((await getCatalogMetadata()).skill_classes[0].id, '7')
    assert.equal((await getCatalogClass('7')).template, null)
    const result = await listCatalogSkills({ name: '发布 & 中文', classId: '7', system: 'APP A', maintainer: 'editor' }, 2)
    assert.equal(result.total, 21); assert.equal(result.items[0].catalog, true)
    assert.equal(result.items[0].maintainerId, 'editor'); assert.equal(result.items[0].callCount, 0)
    assert.equal(result.items[0].creatorId, 'owner')
  })
})

test('在线测试核对发布指针；下线或错误构建禁止打开', async () => {
  let status = '已下线', versionId = 30
  const build = { build_id: 'published-build', skill_version_id: versionId, files: [], source: {} }
  await mocked(async url => url.pathname.endsWith('get-skill') ? success(row({ status })) : success({ ...build, skill_version_id: versionId }), async () => {
    await assert.rejects(prepareCatalogTest('101'), /下线/)
    status = '已上线'; versionId = 31
    await assert.rejects(prepareCatalogTest('101'), /变更/)
    versionId = 30
    assert.equal((await prepareCatalogTest('101')).build.build_id, 'published-build')
  })
})

test('目录测试只提交需求，后端固定发布资源且不写开发者版本和状态', async () => {
  const resource = new TextEncoder().encode('# Frozen resource')
  const build = { build_id: 'published-build', skill_version_id: 30, files: [{ path: 'references/业务规则.txt', size: resource.length,
    sha256: createHash('sha256').update(resource).digest('hex'), role: 'reference' }], source: {} }
  const paths = []
  await mocked(async (url, options) => {
    paths.push(url.pathname)
    if (url.pathname.endsWith('get-skill')) return success(row())
    if (url.pathname.endsWith('get-build')) return success(build)
    if (url.pathname.endsWith('download-resource')) {
      assert.equal(url.searchParams.get('path'), 'references/业务规则.txt'); assert.equal(url.searchParams.get('build_id'), 'published-build')
      return new Response(resource, { headers: { 'content-type': 'application/octet-stream' } })
    }
    assert.equal(url.pathname, '/skills/catalog/create-test-run'); assert.equal(options.method, 'POST')
    const source = JSON.parse(options.body.get('source'))
    assert.equal(source.skill_id, 101); assert.equal(source.build_id, 'published-build')
    assert.match(source.request_id, /^[a-f0-9]{32}$/)
    assert.equal(options.body.get('skill_definition'), null); assert.equal(options.body.get('mounted_resources'), null)
    return Response.json({ run_id: 'catalog-task', skill_id: '101', status: 'failed', error_message: 'Explicit sandbox failure', documents: [] })
  }, async () => {
    const item = await prepareCatalogTest('101')
    assert.equal(await restoreRealtimeDebug(item), undefined)
    const result = await runRealtimeDebug(item, { conversation: 'Generate tests', documents: [] }, item.skillMarkdown, [])
    assert.equal(result.status, 'failed'); assert.equal(result.registrationError, undefined)
    assert.equal(paths.some(path => path.includes('/developer/')), false)
  })
})

test('创建响应丢失后复用调用编号，成功后的下一次调用生成新编号', async () => {
  const ids = []
  await mocked(async (url, options) => {
    if (url.pathname.endsWith('get-skill')) return success(row())
    assert.equal(url.pathname, '/skills/catalog/create-test-run')
    const source = JSON.parse(options.body.get('source')); ids.push(source.request_id)
    if (ids.length === 1) throw new TypeError('Explicit lost response')
    return Response.json({ run_id: source.request_id, skill_id: 101, status: 'failed', error_message: 'Test failure', documents: [] })
  }, async () => {
    const item = { id: '101', catalog: true, buildId: 'published-build', skillVersionId: 30, resourceIds: [], build: { files: [] } }
    const input = { conversation: 'Idempotent request', documents: [] }
    await assert.rejects(runRealtimeDebug(item, input, '# Published', []), /lost response/)
    await runRealtimeDebug(item, input, '# Published', [])
    await runRealtimeDebug(item, input, '# Published', [])
    assert.equal(ids[0], ids[1]); assert.notEqual(ids[1], ids[2])
  })
})

test('整数实现及知识库编号转换为页面一致的选择值，统计原样显示', async () => {
  await mocked(async () => success(row({ id: 101, backend_skill_id: 101, resource_ids: [12],
    knowledge_bases: [{ id: 12, name: 'Knowledge', source: 'backend' }], call_count: 4, download_count: 8 })), async () => {
    const item = await getCatalogSkill('101')
    assert.equal(item.id, '101'); assert.equal(item.backendSkillId, '101')
    assert.deepEqual(item.resourceIds, ['12']); assert.equal(item.knowledgeBases[0].id, '12')
    assert.equal(item.callCount, 4); assert.equal(item.downloadCount, 8)
  })
})

test('目录测试在提交前重新核对下线状态，资源失败不创建沙箱任务', async () => {
  let offline = true
  await mocked(async url => {
    if (url.pathname.endsWith('get-skill')) return success(row({ status: offline ? '已下线' : '已上线' }))
    assert.equal(url.pathname, '/skills/catalog/download-resource')
    return Response.json({ message: '资源已变更' }, { status: 409 })
  }, async () => {
    const item = { ...row(), id: '101', catalog: true, buildId: 'published-build', skillVersionId: 30, resourceIds: [],
      build: { files: [{ path: 'references/missing.md' }] } }
    await assert.rejects(runRealtimeDebug(item, { conversation: 'Run', documents: [] }, '# Definition', []), /下线/)
    offline = false
    await assert.rejects(catalogResourceFiles(item), /资源已变更/)
  })
})

test('目录HTTP业务失败不回退到前端缓存', async () => {
  await mocked(async () => Response.json({ status: 'failure', message: '目录服务不可用' }), async () => {
    await assert.rejects(getCatalogSkill('101'), /目录服务不可用/)
  })
})
