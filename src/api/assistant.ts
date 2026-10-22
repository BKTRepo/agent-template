export interface AssistantSkill { id: string; name: string; description?: string; input?: string; output?: string }
export interface AssistantMessage { id: string; role: 'user' | 'assistant'; text: string; attachments?: string[]; skills?: AssistantSkill[] }
export interface AssistantRequest { messages: { role: AssistantMessage['role']; text: string }[]; files: File[]; skills: AssistantSkill[] }

// 每次请求只带本次手动选择的文件；前文仅带对话文本，不复用附件对象。
export function createAssistantRequest(history: AssistantMessage[], text: string, files: File[], skills: AssistantSkill[]): AssistantRequest {
  if (!text.trim() && !files.length) throw new Error('请输入需求或手动上传文件。')
  return { messages: [...history.map(({ role, text }) => ({ role, text })), { role: 'user', text: text.trim() || '请结合本次上传文件协助分析。' }], files: [...files], skills: skills.map(row => ({ ...row })) }
}
export async function replyWithDemo(request: AssistantRequest, signal: AbortSignal): Promise<string> {
  await new Promise<void>((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('已取消', 'AbortError')); return }
    const cancel = () => { clearTimeout(timer); reject(new DOMException('已取消', 'AbortError')) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve() }, 800)
    signal.addEventListener('abort', cancel, { once: true })
  })
  const round = request.messages.filter(row => row.role === 'user').length
  const last = request.messages.at(-1)!.text
  return `【模拟回复 · 第 ${round} 轮】\n${request.skills.length ? `本轮已加载：${request.skills.map(row => row.name).join('、')}。` : '可点击“加载 Skill”选择测试辅助能力。'}\n${request.files.length ? `本轮文件：${request.files.map(file => file.name).join('、')}。` : '本轮未上传文件；前轮附件不会自动带入。'}\n\n针对“${last.slice(0, 160)}”，建议先明确输入和业务约束，再补充正向、异常与边界场景，最后核对预期结果。${round > 1 ? '\n你可以继续补充要求，当前窗口会保留本次连续对话。' : ''}\n\n当前仅展示前端对话流程，尚未解析文件、执行 Skill 或调用大模型。`
}
