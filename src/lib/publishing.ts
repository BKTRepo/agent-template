import type { Implementation } from '@/types/developer'

export function assertReadyToPublish(item: Implementation) {
  if (!['调试中', '已生成'].includes(item.status)) throw new Error('只有未上线的调试版本才能上线，请刷新状态后重试。')
  if (!item.buildId || !item.debug?.id || item.debug.status !== 'passed' || item.debug.buildId !== item.buildId) throw new Error('当前构建须自测调试通过后才能上线。')
}
