import test from 'node:test'
import assert from 'node:assert/strict'
import { debugDocumentLimits, documentExtensions, skillResourceExtensions, validateSkillForm, validateResourceFiles, knowledgeFileLimits, knowledgeExtensions } from '../src/lib/skillForm.ts'
import { nextVersion } from '../src/lib/version.ts'
import { withSystemVersion } from '../src/lib/skillModel.ts'
const form = (changes = {}) => ({ classId: 'SKILL-CASE-001', name: '新技能', description: '生成业务用例', version: '', instructions: '生成业务用例', resourceIds: [], uploadedResources: [], ...changes })
test('名称唯一性覆盖空格、大小写和全半角，编辑自身不冲突', () => {
 const existing = [{ id: 'one', name: ' Skill ABC ' }]
 assert.ok(validateSkillForm(form({ name: 'ＳＫＩＬＬ ａｂｃ' }), existing).name)
 assert.equal(validateSkillForm(form({ name: 'skill abc' }), existing, 'one').name, undefined)
 assert.match(validateSkillForm(form({ name: '' }), []).name, /不能为空/)
})
test('定稿必填项在保存与调试时均校验，版本由系统生成，不要求输入', () => {
 assert.deepEqual(validateSkillForm(form(), []), {})
 for(const draft of [true, false]) {
  const issues=validateSkillForm(form({ classId:'', description:' ', instructions:'' }), [], undefined, draft)
  assert.ok(issues.classId && issues.description && issues.instructions)
  assert.equal(issues.version, undefined)
 }
})
test('每份资源分类与资源使用说明必填，所属应用不可多选', () => {
 assert.ok(validateSkillForm(form({ resourceIds:['kb'] }), []).resourceUsage)
 assert.ok(validateSkillForm(form({ uploadedResources:[{ name:'a.py',size:1 }], resourceUsage:'校验' }), []).uploadedResources)
 for(const category of ['参考资料','模板','静态资源','脚本']) assert.deepEqual(validateSkillForm(form({ uploadedResources:[{ name:'a.py',size:1,category }],resourceUsage:'校验' }), []),{})
 assert.ok(validateSkillForm(form({ applicationIds:['ATPM','FNP'] }), []).applicationIds)
})
test('资源单文件与总量50MB，支持超过5个小文件并累计已有文件', () => {
 const mb=1024*1024
 assert.equal(validateResourceFiles([{name:'a.zip',size:50*mb}],[]).accepted.length,1)
 assert.match(validateResourceFiles([{name:'a.zip',size:50*mb+1}],[]).errors[0],/50 MB/)
 assert.equal(validateResourceFiles([{name:'a.zip',size:30*mb},{name:'b.zip',size:21*mb}],[]).accepted.length,1)
 assert.equal(validateResourceFiles([{name:'new.md',size:2}], [{name:'old.zip',size:50*mb-1}]).accepted.length,0)
 assert.equal(validateResourceFiles(Array.from({length:8},(_,i)=>({name:`${i}.md`,size:1})),[]).accepted.length,8)
 assert.match(validateSkillForm(form({ uploadedResources:[{name:'a.zip',size:51*mb,category:'静态资源'}],resourceUsage:'参考' }),[]).uploadedResources,/50 MB/)
})
test('技能资源和沙箱需求文档分别按定稿格式校验', () => {
 assert.equal(validateResourceFiles([new File(['x'], 'script.py'), new File(['x'], 'image.png')], [], skillResourceExtensions).accepted.length, 2)
 assert.equal(validateResourceFiles([new File(['x'], 'archive.zip'), new File(['x'], 'manual.pdf')], [], skillResourceExtensions).accepted.length, 0)
 assert.equal(validateResourceFiles([new File(['x'], 'requirement.pdf'), new File(['x'], 'data.json')], [], documentExtensions, debugDocumentLimits).accepted.length, 2)
 assert.equal(validateResourceFiles([new File(['x'], 'image.png')], [], documentExtensions, debugDocumentLimits).accepted.length, 0)
 assert.equal(validateResourceFiles(Array.from({ length: 11 }, (_, index) => new File(['x'], `requirement-${index}.md`)), [], documentExtensions, debugDocumentLimits).accepted.length, 10)
 const mb = 1024 * 1024
 assert.equal(validateResourceFiles([new File([new Uint8Array(50 * mb + 1)], 'large.pdf')], [], documentExtensions, debugDocumentLimits).accepted.length, 0)
})
test('知识库取消大小和个数控制，格式与空文件校验保留', () => {
 assert.equal(validateResourceFiles([{name:'large.pdf',size:800*1024*1024}],[],knowledgeExtensions,knowledgeFileLimits).accepted.length,1)
 assert.equal(validateResourceFiles(Array.from({length:101},(_,i)=>({name:`${i}.txt`,size:1})),[],knowledgeExtensions,knowledgeFileLimits).accepted.length,101)
 assert.equal(validateResourceFiles([{name:'empty.txt',size:0}],[],knowledgeExtensions,knowledgeFileLimits).accepted.length,0)
})
test('图片与文档可上传，非法路径、未知格式、同名及空文件拒绝', () => {
 const result=validateResourceFiles(['png','JPG','jpeg','gif','svg','webp','docx'].map(ext=>new File(['x'],`file.${ext}`)),[])
 assert.equal(result.accepted.length,7)
 const rejected=validateResourceFiles([new File([],'empty.md'),new File(['x'],'bad.exe'),new File(['x'],'../file.png'),new File(['x'],'CON.jpg')],[])
 assert.equal(rejected.errors.length,4)
 assert.equal(validateResourceFiles([new File(['x'],'A.md')],[{name:'a.MD',size:1}]).accepted.length,0)
})
test('版本只递增补丁位，保留历史主次版本并统一知识库V前缀',()=>{
 assert.equal(nextVersion('1.0.0'),'1.0.1')
 assert.equal(nextVersion('v2.3','V'),'V2.3.1')
 assert.equal(nextVersion('V2.3.9','V'),'V2.3.10')
 assert.throws(()=>nextVersion('unknown'),/历史版本/)
})
test('Markdown换行与重复版本字段不能覆盖系统生成版本',()=>{
 const result=withSystemVersion('---\r\nname: demo\r\nversion: 999\r\nversion: 888\r\n---\r\n# 正文','1.0.2')
 assert.doesNotMatch(result,/999|888|\r/)
 assert.equal((result.match(/version: "1.0.2"/g)??[]).length,2)
})
