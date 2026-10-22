import type { KnowledgeBase } from '@/types/developer'
const seed = (id: string, name: string, description: string, team: string, scope: 'public' | 'team', files: [string, string][]): KnowledgeBase => ({
  id, name, description, team, scope, version: 'V1.0.0', tag: '通识类', vectorized: true, model: 'text-embedding-3-large', updatedAt: '2026-10-12T10:00:00+08:00',
  applicationIds: [team === '信用卡中心' ? '信用卡系统' : team === '平台' ? '*' : '核心系统'], creatorId: team === '平台' ? 'platform' : team === '信用卡中心' ? 'zhang' : 'he', creatorName: team === '平台' ? '平台运维组' : team === '信用卡中心' ? '张工' : '何安涵', maintainer: team === '平台' ? '平台运维组' : team === '信用卡中心' ? '张工' : '何安涵', processingStatus: id === 'kb-defect' ? '知识处理失败' : '知识处理完成', history: [{ id: `${id}-initial`, version: 'V1.0.0', summary: '初始创建', maintainer: team === '平台' ? '平台运维组' : team === '信用卡中心' ? '张工' : '何安涵', updatedAt: '2026-10-12T10:00:00+08:00' }],
  files: files.map(([filename, content], i) => ({ id: `${id}-seed-${i}`, name: filename, size: new TextEncoder().encode(content).length, lastModified: 0, sampleContent: content })),
})
export const initialKnowledgeBases: KnowledgeBase[] = [
  seed('kb-core', '核心交易知识库', '聚合交易字典 + 产品规范，供用例生成检索引用', '平台', 'public', [['交易字典.md', '# 交易字典（示例）\n账户、金额、币种、交易流水号。'], ['产品规范.md', '# 产品规范（示例）\n测试需覆盖幂等、权限、余额不足和超时场景。']]),
  seed('kb-defect', '缺陷归因知识库', '历史缺陷案例 + 根因模式，供缺陷分析检索引用', '测试一组', 'team', [['根因模式.md', '# 根因模式（示例）\n从输入、日志、依赖和数据一致性分析异常。']]),
  seed('kb-standard', '用例设计规范知识库', '测试用例编写规范和输出格式', '平台', 'public', [['用例设计规范.md', '# 用例设计规范（示例）\n输出标题、前提条件、步骤与预期结果；覆盖正向、异常、边界。']]),
  seed('kb-credit', '信用卡业务知识库', '信用卡交易与分期业务规则', '信用卡中心', 'team', [['信用卡规范.md', '# 信用卡规范（示例）\n检查额度、分期条件和还款周期。']]),
]
