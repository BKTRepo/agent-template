/**
 * 旧浏览器（Chrome/Edge 90~110）运行时 API 垫片。
 * 必须在所有业务代码之前加载（main.tsx 首行 import）。
 *
 * - Object.hasOwn —— ES2022, Chrome 93+。lowlight(rehype-highlight 代码高亮)、
 *   react-markdown、framer-motion、react-dom(dev 构建) 均直接调用;
 *   缺失时打开聊天记录渲染 Markdown 即抛 TypeError。
 *   构建产物里 plugin-legacy 的 core-js 已含 es.object.has-own,
 *   但 dev 模式不注入 polyfill, 此处统一兜底（幂等, 与 core-js 不冲突）。
 *
 * core-js 只覆盖 ECMAScript 标准 API, 以下两个属于 Web/DOM API, 需手动补齐:
 * - Element.prototype.checkVisibility —— Chrome 105+, react-aria 使用;
 * - structuredClone —— Chrome 98+, react-markdown/rehype 链路使用。
 */

// ---------------------------------------------------------------------------
// Object.hasOwn: Object.prototype.hasOwnProperty.call 的标准化替代。
// 必须放在文件最前: 依赖模块（lowlight 等）在自身模块求值/首次渲染时即调用。
// ---------------------------------------------------------------------------
if (!Object.hasOwn) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(Object as any).hasOwn = function hasOwn(obj: object, prop: PropertyKey): boolean {
    return Object.prototype.hasOwnProperty.call(obj, prop)
  }
}

// ---------------------------------------------------------------------------
// crypto.randomUUID: 较旧浏览器，以及通过 http://局域网IP 访问的非安全上下文，
// 可能没有该 API。页面仅用它生成本地表单/文件 ID，缺失时生成 RFC 4122 v4 格式 ID。
// ---------------------------------------------------------------------------
if (typeof globalThis !== 'undefined' && typeof globalThis.crypto?.randomUUID !== 'function') {
  const cryptoTarget = globalThis.crypto ?? ({} as Crypto)
  if (!globalThis.crypto) Object.defineProperty(globalThis, 'crypto', { value: cryptoTarget, configurable: true })
  const randomUUID = () => {
    const bytes = new Uint8Array(16)
    try { cryptoTarget.getRandomValues?.(bytes) } catch { /* 无安全随机源时仅生成前端本地标识。 */ }
    if (!bytes.some(byte => byte !== 0)) for (let index = 0; index < bytes.length; index++) bytes[index] = Math.floor(Math.random() * 256)
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0'))
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`
  }
  Object.defineProperty(cryptoTarget, 'randomUUID', { value: randomUUID, configurable: true })
}

// ---------------------------------------------------------------------------
// checkVisibility: 判断元素是否可见。垫片实现覆盖常见场景:
// display:none（offsetParent 为 null 且非 fixed/根元素）、visibility:hidden、
// 尺寸为 0。不透支 content-visibility / opacity 精细判断, 对 react-aria 的
// 焦点/滚动用途已足够。
// ---------------------------------------------------------------------------
if (typeof Element !== 'undefined' && !Element.prototype.checkVisibility) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(Element.prototype as any).checkVisibility = function (this: Element): boolean {
    const el = this as HTMLElement
    // getClientRects 为空 => display:none 或不在渲染树中
    if (!el.getClientRects().length) return false
    // visibility:hidden / collapse
    const style = window.getComputedStyle(el)
    if (style.visibility === 'hidden' || style.visibility === 'collapse') return false
    // offsetParent 为 null: 除 position:fixed / <body> 外即 display:none
    if (el.offsetParent === null && style.position !== 'fixed') return false
    return true
  }
}

// ---------------------------------------------------------------------------
// structuredClone: 深拷贝（结构化克隆）。垫片覆盖 JSON 安全值与常见内置类型,
// 不处理循环引用/函数/DOM 节点（依赖方为 AST/纯数据克隆, 不会遇到）。
// ---------------------------------------------------------------------------
if (typeof globalThis !== 'undefined' && typeof (globalThis as { structuredClone?: unknown }).structuredClone !== 'function') {
  const deepClone = (value: unknown): unknown => {
    if (value === null || typeof value !== 'object') return value
    if (value instanceof Date) return new Date(value.getTime())
    if (value instanceof RegExp) return new RegExp(value.source, value.flags)
    if (value instanceof Map) {
      const m = new Map()
      value.forEach((v, k) => m.set(deepClone(k), deepClone(v)))
      return m
    }
    if (value instanceof Set) {
      const s = new Set()
      value.forEach((v) => s.add(deepClone(v)))
      return s
    }
    if (Array.isArray(value)) return value.map(deepClone)
    if (value instanceof ArrayBuffer) return value.slice(0)
    if (ArrayBuffer.isView(value)) {
      const Ctor = value.constructor as new (buffer: ArrayBuffer) => typeof value
      return new Ctor((value as unknown as { buffer: ArrayBuffer; byteOffset: number; byteLength: number }).buffer.slice(0))
    }
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) out[k] = deepClone(v)
    return out
  }
  ;(globalThis as { structuredClone?: unknown }).structuredClone = deepClone
}

export {}
