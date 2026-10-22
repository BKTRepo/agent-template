/**
 * PostCSS 兼容插件（Chrome/Edge < 104 离线环境）——须在
 * @csstools/postcss-cascade-layers 之后运行（依赖其已剥离 @layer 的产物）。
 *
 * 解决两类旧浏览器无法解析的 CSS:
 *
 * 1. calc(infinity * 1px)（Tailwind v4 的 rounded-full 实现）
 *    infinity 关键字 Chrome 105+ 才支持, 92 上整条 border-radius 声明被丢弃,
 *    圆角回退为直角。在原声明前插入等价的 9999px 回退（现代浏览器仍以
 *    原 infinity 声明覆盖生效）。
 *
 * 2. translate / rotate / scale 独立 transform 属性（Chrome 104+ 才支持）
 *    Tailwind v4 的 translate- / scale- 工具类、HeroUI 的滑块/箭头样式、
 *    toast 关键帧都直接使用它们; 92 上声明被丢弃 => 元素错位、不旋转/缩放。
 *    由于 transform 与独立属性是【不同属性】（现代浏览器会叠加二者, 不能
 *    简单用 cascade 覆盖）, 回退必须对现代浏览器不可见:
 *
 *    - 普通样式规则: 在原规则后插入
 *        @supports not (translate: 0 0) { <同选择器> { transform: ... } }
 *      现代浏览器（104+）条件为假 => 跳过, 行为零变化;
 *      旧浏览器条件为真 => 命中 transform 回退。
 *      @supports 块跟随原规则所处位置（@media / 其他 @supports 内同样生效）。
 *    - @keyframes 内的关键帧规则: 关键帧内不允许嵌 @supports, 且单个关键帧
 *      块是自包含的（无跨规则合成问题）, 故直接把独立属性合并改写为一条
 *      transform 声明（对所有浏览器语义等价）。
 *
 *    合成顺序遵循规范: translate → rotate → scale。
 *    引用 --tw-translate-x/-y、--tw-scale-x/-y 的 var() 补充与 @property
 *    注册值一致的默认值, 避免变量缺失时回退失效。
 *
 * 3. transition / transition-property / will-change 中引用独立属性的声明
 *    如 HeroUI 抽屉的 `transition: translate 250ms ...`。旧浏览器上
 *    translate 不是可过渡属性 => 过渡永不触发, 抽屉开合变成瞬间出现/消失
 *    （上面第 2 条生成的 transform 回退也因此失去动画）。在同一
 *    @supports not (translate: 0 0) 回退块中补写把属性名替换为 transform
 *    的等价声明（原声明对现代浏览器保持不变）。transition 简写按逗号段
 *    处理, 段内裸 ident 即属性名; 与第 2 条的回退合并进同一个块, 保持
 *    每条规则至多一个回退块。
 */
import postcss from 'postcss'

/** 顶层按空白拆分（括号内的空白不算, 兼容 var(--x, 0) / calc(a * b)） */
function splitTopLevelSpaces(str) {
  const tokens = []
  let depth = 0
  let cur = ''
  for (const ch of str) {
    if (ch === '(' || ch === '[') depth++
    else if (ch === ')' || ch === ']') depth--
    if (depth === 0 && /\s/.test(ch)) {
      if (cur) {
        tokens.push(cur)
        cur = ''
      }
    } else {
      cur += ch
    }
  }
  if (cur) tokens.push(cur)
  return tokens
}

/** 顶层按逗号拆分（括号内的逗号不算） */
function splitTopLevelCommas(str) {
  const parts = []
  let depth = 0
  let cur = ''
  for (const ch of str) {
    if (ch === '(' || ch === '[') depth++
    else if (ch === ')' || ch === ']') depth--
    if (depth === 0 && ch === ',') {
      parts.push(cur)
      cur = ''
    } else {
      cur += ch
    }
  }
  parts.push(cur)
  return parts
}

/** transition 简写中段内裸 ident 可能是属性名, 也可能是时序关键字; 后者不参与替换判定 */
const TIMING_KEYWORDS = new Set(['ease', 'ease-in', 'ease-out', 'ease-in-out', 'linear', 'step-start', 'step-end'])
const INDIVIDUAL_PROP_RE = /^(translate|rotate|scale)$/i

/** transition / transition-property / will-change 值中把 translate/rotate/scale 属性名替换为 transform。
 *  替换后重复的 transform 段合并（保留首个, 与旧浏览器原本忽略 translate 段的语义一致）。 */
function rewritePropList(value) {
  let transformKept = false
  const outSegments = []
  for (const rawSegment of splitTopLevelCommas(value)) {
    const tokens = splitTopLevelSpaces(rawSegment.trim())
    let isTransformSegment = false
    const outTokens = tokens.map((token) => {
      if (INDIVIDUAL_PROP_RE.test(token)) {
        isTransformSegment = true
        return 'transform'
      }
      if (!TIMING_KEYWORDS.has(token.toLowerCase()) && /^transform$/i.test(token)) isTransformSegment = true
      return token
    })
    if (isTransformSegment) {
      if (transformKept) continue
      transformKept = true
    }
    outSegments.push(outTokens.join(' '))
  }
  return outSegments.join(', ')
}

/** 快速判定值中是否含 translate/rotate/scale 裸 ident（- 连接的 ident 如 --tw-translate-x 不命中） */
const HAS_INDIVIDUAL_PROP_RE = /(^|[\s,])(?:translate|rotate|scale)([\s,]|$)/i

/** 无回退值的 var(--tw-translate-x) 等补上与 @property 一致的默认值 */
const VAR_DEFAULTS = {
  '--tw-translate-x': '0',
  '--tw-translate-y': '0',
  '--tw-scale-x': '1',
  '--tw-scale-y': '1',
}
function withVarDefaults(value) {
  return value.replace(/var\(\s*(--tw-[a-z-]+)\s*\)/g, (whole, name) =>
    VAR_DEFAULTS[name] != null ? `var(${name}, ${VAR_DEFAULTS[name]})` : whole,
  )
}

/** 把一条 translate/rotate/scale 声明的值转成等价的 transform 函数 */
function toTransformFn(decl) {
  const tokens = splitTopLevelSpaces(withVarDefaults(decl.value.trim()))
  if (decl.prop === 'translate') {
    return tokens.length >= 2 ? `translate(${tokens[0]}, ${tokens.slice(1).join(' ')})` : `translateX(${tokens[0]})`
  }
  if (decl.prop === 'rotate') {
    // 单值旋转; 多值（3D 场景）旧浏览器本就无对应能力, 取首值兜底
    return `rotate(${tokens[0]})`
  }
  // scale
  return tokens.length >= 2 ? `scale(${tokens[0]}, ${tokens[1]})` : `scale(${tokens[0]})`
}

export default function postcssLegacyTransform() {
  return {
    postcssPlugin: 'postcss-legacy-transform',
    OnceExit(root) {
      // ---------- 1. calc(infinity * 1px) → 9999px 回退 ----------
      root.walkDecls((decl) => {
        if (!/calc\(\s*infinity/i.test(decl.value)) return
        const replaced = decl.value.replace(/calc\(\s*infinity\s*\*\s*1px\s*\)/gi, '9999px')
        if (replaced !== decl.value) decl.cloneBefore({ value: replaced })
      })

      // ---------- 2. 独立 transform 属性 → transform 回退 ----------
      // （含 transition / transition-property / will-change 中引用独立属性的声明,
      //   否则旧浏览器上针对 translate 等的过渡永不触发, 抽屉开合无动画）
      // 先收集再改写, 避免遍历中改动树导致漏处理
      const targets = []
      root.walkRules((rule) => {
        const decls = []
        const refDecls = []
        rule.walkDecls((d) => {
          if (d.prop === 'translate' || d.prop === 'rotate' || d.prop === 'scale') {
            decls.push(d)
          } else if (
            (d.prop === 'transition' || d.prop === 'transition-property' || d.prop === 'will-change') &&
            HAS_INDIVIDUAL_PROP_RE.test(d.value)
          ) {
            const rewritten = rewritePropList(d.value)
            if (rewritten !== d.value) refDecls.push({ prop: d.prop, value: rewritten })
          }
        })
        if (decls.length || refDecls.length) targets.push({ rule, decls, refDecls })
      })

      const ORDER = { translate: 0, rotate: 1, scale: 2 }
      for (const { rule, decls, refDecls } of targets) {
        let transform = null
        if (decls.length) {
          decls.sort((a, b) => ORDER[a.prop] - ORDER[b.prop])
          transform = decls.map(toTransformFn).join(' ')
        }

        // @keyframes 内: 直接改写为 transform（关键帧块自包含, 语义等价）;
        // transition / will-change 出现在关键帧内无意义, 不生成回退
        if (rule.parent && rule.parent.type === 'atrule' && rule.parent.name === 'keyframes') {
          if (!transform) continue
          const first = decls[0]
          first.replaceWith(postcss.decl({ prop: 'transform', value: transform }))
          for (const d of decls.slice(1)) d.remove()
          continue
        }

        // 普通规则: @supports not (...) 包裹, 仅旧浏览器命中
        const fallbackRule = rule.clone({ nodes: [] })
        if (transform) fallbackRule.append(postcss.decl({ prop: 'transform', value: transform }))
        for (const { prop, value } of refDecls) fallbackRule.append(postcss.decl({ prop, value }))
        const supports = postcss.atRule({ name: 'supports', params: 'not (translate: 0 0)' })
        supports.append(fallbackRule)
        rule.parent.insertAfter(rule, supports)
      }
    },
  }
}
postcssLegacyTransform.postcss = true
