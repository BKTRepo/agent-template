import type { Implementation, Resource, SkillClass } from '@/types/developer'

export const skillClasses: SkillClass[] = [
  { id: 'SKILL-POINT-005', name: '测试要点生成', requiredInput: 'requirements', sample: {}, description: '从业务需求提炼测试范围、风险和关键检查项。', inputSchema: '需求文档 / 业务规则', outputSchema: 'TestPoint[] · 场景 / 风险 / 检查项', enabled: true },
  { id: 'SKILL-CASE-001', name: '智能用例生成', requiredInput: 'scene', sample: { scene: '转账需求用例生成', coverage: ['正向', '异常', '边界'], constraints: { 幂等: true, 权限边界: true } } },
  { id: 'SKILL-BUG-004', name: '历史缺陷案例推荐', requiredInput: 'requirements', sample: {}, description: '根据需求、异常现象检索相关历史缺陷案例。', inputSchema: '需求 / 异常现象 / 日志', outputSchema: 'DefectCase[] · 案例 / 相关性 / 建议', enabled: true },
  { id: 'SKILL-REPORT-006', name: '测试报告生成', requiredInput: 'results', sample: {}, description: '整理执行结果、覆盖情况与风险，生成测试报告。', inputSchema: '执行结果 / 缺陷统计 / 风险说明', outputSchema: 'TestReport · 摘要 / 覆盖率 / 风险 / 建议', enabled: true },
  { id: 'SKILL-DATA-002', name: '测试数据构造', requiredInput: 'scenario', sample: { scenario: '转账金额边界值', count: 10 } },
  { id: 'SKILL-UI-007', name: 'UI自动化脚本生成', requiredInput: 'scenario', sample: {}, description: '根据页面操作与断言要求生成可复核的自动化脚本。', inputSchema: '页面描述 / 操作步骤 / 断言', outputSchema: 'Script · 脚本 / 环境说明 / 使用步骤', enabled: true },
]
export const resources: Resource[] = [
  { id: 'kb-core', name: '核心交易知识库', kind: 'knowledge', team: '平台', scope: 'public', meta: '聚合交易字典 + 产品规范，供用例生成检索引用' },
  { id: 'kb-defect', name: '缺陷归因知识库', kind: 'knowledge', team: '测试一组', scope: 'team', meta: '历史缺陷案例 + 根因模式，供缺陷分析检索引用' },
  { id: 'kb-standard', name: '用例设计规范知识库', kind: 'knowledge', team: '平台', scope: 'public', meta: '8 个文件 · 通识知识' },
  { id: 'kb-credit', name: '信用卡业务知识库', kind: 'knowledge', team: '信用卡中心', scope: 'team', meta: '6 个文件 · v2.0' },
  { id: 'file-dictionary', name: '核心系统字段字典.xlsx', kind: 'file', team: '测试一组', scope: 'team', meta: 'Excel · 128 KB · v1.0' },
  { id: 'file-history', name: '历史用例样例.pdf', kind: 'file', team: '平台', scope: 'public', meta: 'PDF · 2.4 MB · v1.2' },
  { id: 'file-api', name: '接口契约样例.json', kind: 'file', team: '测试二组', scope: 'team', meta: 'JSON · 16 KB · v1.0' },
]
const seedImplementations: Implementation[] = [
  { id: 'impl-credit', classId: 'SKILL-CASE-001', name: '信用卡用例生成 V2', technicalName: 'credit-case-generator', system: '信用卡系统', team: '信用卡中心', version: '2.1.0', modelTier: 'standard', description: '根据信用卡业务需求和测试规范生成结构化用例。', instructions: '读取需求，分析业务场景，生成正向、异常和边界用例。', resourceIds: ['kb-credit', 'file-history'], status: '已上线', updatedAt: '2026-10-08T14:21:00+08:00', buildId: 'build-credit-210' },
  { id: 'impl-core', classId: 'SKILL-CASE-001', name: '核心系统用例生成', technicalName: 'core-case-generator', system: '核心系统', team: '测试一组', version: '1.8.2', modelTier: 'standard', description: '针对支付核心业务需求生成结构化测试用例，覆盖正向、异常、边界场景。', instructions: '读取需求与字段字典，结合历史用例，输出测试场景、步骤和预期结果。', resourceIds: ['file-dictionary', 'file-history'], status: '调试中', updatedAt: '2026-10-08T15:03:00+08:00', buildId: 'build-core-182' },
  { id: 'impl-ledger', classId: 'SKILL-BUG-004', name: '账务流水缺陷分析', technicalName: 'ledger-defect-analysis', system: '核心系统', team: '测试一组', version: '0.4.0', modelTier: 'reasoning', description: '分析账务流水中的异常并提供定位建议。', instructions: '检查日志与账务规则，识别异常并给出依据。', resourceIds: [], status: '已上线', updatedAt: '2026-10-07T18:10:00+08:00', buildId: 'build-ledger-040' },
  { id: 'impl-scanner', classId: 'SKILL-API-003', name: '接口契约扫描器', technicalName: 'api-contract-scanner', system: '测试平台', team: '测试一组', version: '0.2.1', modelTier: 'fast', description: '解析接口契约，检查参数和响应格式。', instructions: '读取接口定义，检查必填、类型和边界约束。', resourceIds: [], status: '草稿', updatedAt: '2026-10-07T10:26:00+08:00' },
]
export const initialImplementations: Implementation[] = seedImplementations.map(item => ({ ...item, classId: item.classId === 'SKILL-API-003' ? 'SKILL-POINT-005' : item.classId, applicationIds: [item.system], creatorId: item.id === 'impl-credit' ? 'zhang' : item.id === 'impl-ledger' ? 'li' : 'he', creatorName: item.id === 'impl-credit' ? '张工' : item.id === 'impl-ledger' ? '李明' : '何安涵' }))
