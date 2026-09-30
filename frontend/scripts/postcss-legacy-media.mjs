/**
 * PostCSS 兼容插件（Chrome/Edge < 104 离线环境）——把 CSS Media Queries
 * Level 4 的【区间语法】降级为传统 min-/max- 前缀写法。
 *
 * Tailwind v4 的响应式断点（sm:/md:/…）输出 `@media (width >= 40rem)`;
 * 区间写法 Chrome 104+ 才支持, 旧浏览器解析失败会把整个 @media 块丢弃,
 * 导致全部 sm/md 响应式规则失效——分页竖排换行、弹窗丢失 my-auto 贴底、
 * 表格/布局尺寸停留在移动端形态等。
 *
 * 转换规则（尽量保持语义等价）:
 *   (width >= X)       →  (min-width: X)
 *   (width > X)        →  (min-width: calc(X + 1px))   // 严格不等以 1px 近似
 *   (width <= X)       →  (max-width: X)
 *   (width < X)        →  (max-width: calc(X - 1px))
 *   (X <= width <= Y)  →  (min-width: X) and (max-width: Y)
 * 同时支持反写形 `(X <= width)` 以及 height / inline-size / block-size。
 * 不含比较运算符的条件（如 (hover: hover)、(prefers-reduced-motion: reduce)）原样保留。
 */

/** 允许做区间比较的特征名（其余特征不做转换, 原样保留） */
const FEATURES = new Set(['width', 'height', 'inline-size', 'block-size'])

/** 特征名 + 比较运算符 → 传统 min-/max- 条件 */
function toLegacy(feature, op, value) {
  if (!FEATURES.has(feature)) return null
  const side = op[0] === '>' ? 'min' : 'max' // '>'/'>=' → min; '<'/'<=' → max
  const strict = op.length === 1
  if (!strict) return `(${side}-${feature}: ${value.trim()})`
  // 严格不等: 媒体查询没有排他写法, 以 ±1px 近似（断点值通常为 rem, 误差可忽略）
  const epsilon = side === 'min' ? `calc(${value.trim()} + 1px)` : `calc(${value.trim()} - 1px)`
  return `(${side}-${feature}: ${epsilon})`
}

/** 转换单个括号条件; 无法识别时原样返回 */
function transformCondition(inner) {
  // 双侧区间: (A <= width <= B) / (A >= width >= B)
  let m = inner.match(/^(.+?)\s*(<=|>=|<|>)\s*([a-zA-Z-]+)\s*(<=|>=|<|>)\s*(.+)$/)
  if (m && FEATURES.has(m[3])) {
    const lo = toLegacy(m[3], flipOp(m[2]), m[1]) // (A <= width) ≡ (width >= A)
    const hi = toLegacy(m[3], flipOp(m[4]), m[5])
    if (lo && hi) return `${lo} and ${hi}`
  }
  // 单侧正写: (width >= X)
  m = inner.match(/^([a-zA-Z-]+)\s*(<=|>=|<|>)\s*(.+)$/)
  if (m && FEATURES.has(m[1])) {
    return toLegacy(m[1], m[2], m[3]) ?? inner
  }
  // 单侧反写: (X <= width)
  m = inner.match(/^(.+?)\s*(<=|>=|<|>)\s*([a-zA-Z-]+)$/)
  if (m && FEATURES.has(m[3])) {
    return toLegacy(m[3], flipOp(m[2]), m[1]) ?? inner
  }
  return inner
}

/** 反写形式的运算符翻转: (A <= width) ≡ (width >= A) */
function flipOp(op) {
  return { '<=': '>=', '>=': '<=', '<': '>', '>': '<' }[op]
}

export default function postcssLegacyMedia() {
  return {
    postcssPlugin: 'postcss-legacy-media',
    OnceExit(root) {
      root.walkAtRules('media', (atRule) => {
        if (!/[<>]=?/.test(atRule.params)) return
        atRule.params = atRule.params.replace(/\(([^()]*)\)/g, (whole, inner) => {
          const out = transformCondition(inner.trim())
          return out === inner.trim() ? whole : out
        })
      })
    },
  }
}
postcssLegacyMedia.postcss = true
