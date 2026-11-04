import test from 'node:test'
import assert from 'node:assert/strict'
import { useAuthStore } from '../src/stores/authStore.ts'
import { useAccessStore } from '../src/stores/accessStore.ts'
import { useKnowledgeStore } from '../src/stores/knowledgeStore.ts'
import { saveKnowledgeBase, getConversionStatus, retryConversion, toKnowledge } from '../src/api/knowledge.ts'
import { mountKnowledge } from '../src/api/knowledgeMount.ts'
import { canMountKnowledge } from '../src/lib/access.ts'

const success = data => Response.json({ status: 'success', data })
const knowledge = (status = 'completed') => ({ id: 'kb-real', knowledge_name: 'Business rules', description: '', tag: 'general',
  application: '', version: 'V1.0.0', user_id: 1, creator_login_name: 'owner', maintainer: 'Owner',
  is_public: false, can_edit: true, status, reference_count: 0, updated_time: '2026-11-04T10:00:00Z',
  documents: [{ id: 'document-1', filename: 'rules.md', file_size: 5, status: status === 'completed' ? 'completed' : 'processing',
    updated_time: '', conversion_job_id: 'doc-real', conversion_status: status === 'completed' ? 'complete' : 'embedding' }], history: [] })
async function mocked(handler, work) {
  const original = globalThis.fetch
  useAuthStore.getState().setSession({ token: 'test-token', username: 'owner', alias: 'Owner' })
  useAccessStore.getState().setIdentity({ id: 'owner', name: 'Owner' })
  globalThis.fetch = async (url, options = {}) => {
    assert.ok(['GET', 'POST'].includes(options.method || 'GET'))
    return handler(url, options)
  }
  try { await work() } finally {
    globalThis.fetch = original; useAuthStore.getState().setSession(null)
    useAccessStore.getState().setIdentity({ id: '', name: '' }); useKnowledgeStore.getState().reset()
  }
}

test('创建逐文件调用convert，元数据保存失败后复用job_id，不重复入库', async () => {
  let conversions = 0, saves = 0
  const uploads = [{ id: 'upload-a', file: new File(['rules'], 'rules.md') }, { id: 'upload-b', file: new File(['more'], 'more.txt') }]
  const form = { name: 'Business rules', description: '', tag: '通识类', scope: 'team', applicationIds: [],
    files: uploads.map(row => ({ id: row.id, name: row.file.name, size: row.file.size })) }
  await mocked(async (url, options) => {
    assert.equal(options.headers.token, 'test-token')
    if (url === '/api/convert') {
      assert.equal(options.method, 'POST'); assert.ok(options.body instanceof FormData)
      assert.equal(options.headers['Content-Type'], undefined)
      assert.ok(options.body.get('file') instanceof File)
      return success({ job_id: `doc-${++conversions}`, status: 'embedding' })
    }
    assert.equal(url, '/knowledge-bases/create'); assert.equal(options.method, 'POST')
    const source = JSON.parse(options.body.get('source'))
    assert.deepEqual(source.conversion_job_ids, ['doc-1', 'doc-2'])
    assert.equal(source.user_id, undefined); assert.equal(options.body.getAll('files').length, 0)
    return ++saves === 1 ? Response.json({ status: 'failure', message: 'metadata unavailable' }, { status: 503 }) : success(knowledge('processing'))
  }, async () => {
    await assert.rejects(saveKnowledgeBase(form, uploads), /metadata unavailable/)
    const saved = await saveKnowledgeBase(form, uploads)
    assert.equal(conversions, 2); assert.equal(saved.id, 'kb-real')
    assert.equal(saved.processingStatus, '知识处理中')
    assert.equal(canMountKnowledge(saved, { id: 'owner' }), false)
  })
})

test('仅complete且知识库真实完成才可挂载，重试发送原job_id', async () => {
  const requests = []
  await mocked(async (url, options) => {
    requests.push(url)
    if (options.method === 'POST') {
      assert.equal(url, '/api/convert/retry'); assert.deepEqual(JSON.parse(options.body), { job_id: 'doc/with space' })
      return success({ job_id: 'doc/with space', status: 'parsing' })
    }
    const query = new URL(url, 'http://local')
    assert.equal(query.pathname, '/api/convert/status'); assert.equal(query.searchParams.get('job_id'), 'doc/with space')
    return success({ status: 'embedding' })
  }, async () => {
    assert.equal((await getConversionStatus('doc/with space')).status, 'embedding')
    assert.equal((await retryConversion('doc/with space')).status, 'parsing')
    assert.equal(canMountKnowledge(toKnowledge(knowledge('processing')), { id: 'owner' }), false)
    assert.equal(canMountKnowledge(toKnowledge(knowledge('failed')), { id: 'owner' }), false)
    assert.equal(canMountKnowledge(toKnowledge(knowledge()), { id: 'owner' }), true)
    assert.equal(useKnowledgeStore.persist, undefined)
  })
})

const skill = (id, changes = {}) => ({ id, name: id, class_id: 1, creator_login_name: 'owner', creator_name: 'Owner',
  description: 'Keep description', instructions: 'Keep instructions', application_ids: [],
  resource_ids: ['old-kb'], knowledge_bases: [{ id: 'old-kb', name: 'Old', source: 'backend' }],
  uploaded_resources: [{ id: 'file:8', fileId: 8, category: '脚本', name: 'run.py' }], resource_usage: 'Keep usage',
  compatibility: 'Python 3.12', technical_name: 'same-technical-name', skill_markdown: '# Existing definition',
  version: '1.0.0', current_revision: 4, skill_version_id: 10, status: '已上线', updated_at: '', ...changes })

test('多选抽象类读取全部本人分页，完整调用技能更新接口，部分失败可仅重试失败项', async () => {
  const rows = new Map([['one', skill('one')], ['two', skill('two')], ['existing', skill('existing', { resource_ids: ['kb-real'] })],
    ['other', skill('other', { creator_login_name: 'someone-else' })], ['unselected', skill('unselected', { class_id: 2 })]])
  let fail = true
  const saved = [], pages = []
  await mocked(async (url, options) => {
    if (url.startsWith('/knowledge-bases/detail?')) return success(knowledge())
    if (url.startsWith('/skills/developer/list-skills?')) {
      const page = Number(new URL(url, 'http://local').searchParams.get('page')); pages.push(page)
      return success({ items: page === 1 ? [rows.get('one'), rows.get('other')] : [rows.get('two'), rows.get('existing'), rows.get('unselected')], page, pages: 2, page_size: 100, total: 5 })
    }
    assert.equal(url, '/skills/developer/save-skill'); assert.equal(options.method, 'POST')
    const body = JSON.parse(options.body); saved.push(body.skill_id)
    assert.equal(body.expected_revision, 4); assert.equal(body.description, 'Keep description')
    assert.equal(body.instructions, 'Keep instructions'); assert.equal(body.compatibility, 'Python 3.12')
    assert.equal(body.uploaded_resources[0].fileId, 8); assert.equal(body.skill_markdown, '# Existing definition')
    assert.deepEqual(body.resource_ids, ['old-kb', 'kb-real']); assert.equal(body.resource_usage, 'Keep usage')
    if (fail && body.skill_id === 'two') return Response.json({ status: 'failure', message: 'revision conflict' }, { status: 409 })
    rows.set(body.skill_id, { ...rows.get(body.skill_id), resource_ids: body.resource_ids, current_revision: 5, status: '草稿' })
    return success(rows.get(body.skill_id))
  }, async () => {
    const result = await mountKnowledge('kb-real', ['1'])
    assert.deepEqual(pages, [1, 2]); assert.equal(result.matched, 3)
    assert.equal(result.saved, 1); assert.equal(result.skipped, 1)
    assert.equal(result.failures[0].id, 'two'); assert.deepEqual(saved, ['one', 'two'])
    fail = false
    const repeated = await mountKnowledge('kb-real', ['1'])
    assert.equal(repeated.saved, 1); assert.equal(repeated.skipped, 2); assert.deepEqual(repeated.failures, [])
    assert.deepEqual(saved, ['one', 'two', 'two'])
  })
})

test('知识库未完成不调用技能保存接口', async () => {
  await mocked(async url => { assert.ok(url.startsWith('/knowledge-bases/detail?')); return success(knowledge('processing')) }, async () => {
    await assert.rejects(mountKnowledge('kb-real', ['1']), /尚未入库完成/)
  })
})

test('编辑保留原文档，同名新文件使用知识库保存合同而非重复convert', async () => {
  const upload = { id: 'replacement', file: new File(['new rule'], 'rules.md') }
  await mocked(async (url, options) => {
    assert.equal(url, '/knowledge-bases/save'); assert.equal(options.method, 'POST')
    assert.equal(options.body.get('kb_id'), 'kb-real')
    assert.equal(options.body.get('files').name, 'rules.md')
    const source = JSON.parse(options.body.get('source'))
    assert.deepEqual(source.retained_document_ids, ['document-1'])
    assert.deepEqual(source.conversion_job_ids, []); assert.equal(source.expected_version, 'V1.0.0')
    return success(knowledge('processing'))
  }, async () => {
    const form = { ...toKnowledge(knowledge()), files: [{ id: 'document-1' }, { id: upload.id }], changeSummary: 'Replace rules' }
    const result = await saveKnowledgeBase(form, [upload], 'kb-real')
    assert.equal(result.processingStatus, '知识处理中')
  })
})
