/**
 * 复制文本到剪贴板。
 *
 * navigator.clipboard 仅在安全上下文（HTTPS / localhost）可用, 本应用常以
 * http://<内网IP> 方式部署, 此时 navigator.clipboard 为 undefined, 直接调用
 * writeText 会抛错导致"复制失败"。因此优先用 Clipboard API, 不可用或失败时
 * 回退到传统 execCommand('copy')（临时 textarea + 选中复制）。
 *
 * 注意: execCommand 回退依赖用户手势（点击）上下文, 调用方应在事件回调中
 * 直接调用本方法, 不要在多次 await 之后再调。
 *
 * @returns 是否复制成功
 */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      /* 有 API 但被拒（iframe 权限/失焦等）, 继续走下方回退 */
    }
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    // 固定定位到视口内且不可见: 避免短暂闪现、不挤压页面布局;
    // 部分浏览器要求元素在视口内才能成功复制
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    ta.style.top = '0'
    ta.style.opacity = '0'
    ta.setAttribute('readonly', '')
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
