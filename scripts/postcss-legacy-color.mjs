/**
 * PostCSS 兼容插件（Chrome/Edge 90~110 离线环境）——须在
 * @csstools/postcss-oklab-function / postcss-color-mix-function 之后运行。
 *
 * 解决旧浏览器不支持 color-mix() 的问题（oklch 已由前置插件转为 rgb 回退）:
 *
 * 1. 收集主题变量的 rgb 三值:
 *    前置插件会把 `--x: oklch(...)` 转成「rgb 回退 + 原 oklch」两条声明,
 *    本插件解析其中的 rgb/hex 回退值, 记录 --x -> "r g b" 三值,
 *    并在同规则内补发 `--x-rgb: r g b;`（供第 2 条的 alpha 混色使用）。
 *    值为 var(--y) 的变量建立别名, 解析时递归跟随。
 *
 * 2. 改写动态混色为旧浏览器可用的等价语法（保留原声明供现代浏览器使用）:
 *      color-mix(in oklab, var(--x) N%, transparent)
 *      =>  先插入  rgb(var(--x-rgb) / N%)   （旧浏览器生效）
 *          再保留  color-mix(...)           （111+ 覆盖生效）
 *    「与 transparent 按 N% 混合」视觉上等价于「该颜色 N% 不透明度」。
 *    支持 var(--a, var(--b)) 形式的回退链与参数顺序颠倒的写法。
 *
 * 3. 拆分含 :has() 的选择器列表:
 *    Chrome 105 才支持 :has(); 且选择器列表中任一选择器无法解析时整条规则
 *    被废弃——HeroUI 的规则普遍形如「:has() 变体, 等价的属性选择器变体」,
 *    拆成两条规则后, 旧浏览器可命中不含 :has() 的等价变体。
 */

/** 将颜色字符串解析为 "r g b" 三值; 不支持的格式返回 null。 */
function parseRgbTriplet(value) {
  const v = value.trim()
  // hex: #rgb / #rrggbb / #rgba / #rrggbbaa
  let m = v.match(/^#([0-9a-f]{3,8})$/i)
  if (m) {
    let h = m[1]
    if (h.length === 3 || h.length === 4) h = h.split('').map((c) => c + c).join('')
    const r = parseInt(h.slice(0, 2), 16)
    const g = parseInt(h.slice(2, 4), 16)
    const b = parseInt(h.slice(4, 6), 16)
    if ([r, g, b].some(Number.isNaN)) return null
    return `${r} ${g} ${b}`
  }
  // rgb()/rgba(): 逗号或空格分隔均可
  m = v.match(/^rgba?\(\s*([^)]+)\)$/i)
  if (m) {
    const parts = m[1].includes(',')
      ? m[1].split(',').map((s) => s.trim())
      : m[1].split(/\s+/).filter(Boolean)
    const [r, g, b] = parts.slice(0, 3).map((p) => parseFloat(p))
    if ([r, g, b].some(Number.isNaN)) return null
    return `${Math.round(r)} ${Math.round(g)} ${Math.round(b)}`
  }
  // 命名色: 仅处理本项目用到的少数几个
  const named = { white: '255 255 255', black: '0 0 0', transparent: null }
  if (Object.prototype.hasOwnProperty.call(named, v.toLowerCase())) return named[v.toLowerCase()]
  return null
}

/** 解析 var() 引用链: 返回 { vars: ['--a','--b'] }（回退链顺序）或 null */
function parseVarChain(colorArg) {
  const t = colorArg.trim()
  const m = t.match(/^var\(\s*(--[a-zA-Z0-9-]+)\s*(?:,\s*(.+)\s*)?\)$/)
  if (!m) return null
  const vars = [m[1]]
  if (m[2]) {
    const inner = parseVarChain(m[2])
    if (inner) vars.push(...inner.vars)
  }
  return { vars }
}

/** 顶层按逗号拆分（括号内的逗号不算, 兼容 var(--a, var(--b)) 嵌套） */
function splitTopLevelCommas(str) {
  const parts = []
  let depth = 0
  let cur = ''
  for (const ch of str) {
    if (ch === '(') depth++
    if (ch === ')') depth--
    if (ch === ',' && depth === 0) {
      parts.push(cur.trim())
      cur = ''
    } else {
      cur += ch
    }
  }
  parts.push(cur.trim())
  return parts
}

/**
 * 匹配 color-mix 中「var() 颜色与 transparent 混合」的参数对,
 * 返回 { vars: 变量回退链, percent: 颜色占比 } 或 null。
 * 兼容: 「var(--x) N%, transparent」「transparent N%, var(--x) M%」
 *       「transparent N%, var(--x)」（颜色占比取 100-N）。
 */
function matchTransparentMix(argsStr) {
  const args = splitTopLevelCommas(argsStr)
  if (args.length !== 2) return null
  const parsed = args.map((a) => {
    const m = a.match(/^(.+?)\s+(\d+(?:\.\d+)?)%$/s)
    return m ? { base: m[1].trim(), pct: parseFloat(m[2]) } : { base: a.trim(), pct: null }
  })
  const ti = parsed.findIndex((p) => /^transparent$/i.test(p.base))
  if (ti === -1) return null
  const color = parsed[1 - ti]
  const chain = parseVarChain(color.base)
  if (!chain) return null
  let percent
  if (color.pct != null) percent = color.pct
  else if (parsed[ti].pct != null) percent = 100 - parsed[ti].pct
  else return null
  if (percent <= 0 || percent > 100) return null
  return { vars: chain.vars, percent: Math.round(percent * 100) / 100 }
}

export default function postcssLegacyColor() {
  return {
    postcssPlugin: 'postcss-legacy-color',
    OnceExit(root) {
      // ---------- 1. 全局常量收集 ----------
      // 同一变量若处处同值（如 --white / --eclipse / --snow）记为全局常量;
      // 在不同规则中取值不同的（如明暗主题各自的 --background）不作为常量,
      // 改在各自规则上下文内解析。
      const constants = new Map()
      const conflicted = new Set()
      root.walkDecls((decl) => {
        if (!decl.prop.startsWith('--')) return
        const t = parseRgbTriplet(decl.value)
        if (!t) return
        if (constants.has(decl.prop) && constants.get(decl.prop) !== t) conflicted.add(decl.prop)
        else constants.set(decl.prop, t)
      })
      for (const p of conflicted) constants.delete(p)

      // ---------- 2. 按规则上下文为变量补发 --x-rgb ----------
      // 每个规则内: 静态值优先取前置插件生成的 rgb 回退; var(--y) 形式先在本规则内
      // 递归解析, 解析不到再退回全局常量——保证明/暗主题各自拿到正确的三值。
      root.walkRules((rule) => {
        const byProp = new Map()
        rule.walkDecls((d) => {
          if (!d.prop.startsWith('--')) return
          if (!byProp.has(d.prop)) byProp.set(d.prop, [])
          byProp.get(d.prop).push(d)
        })
        if (!byProp.size) return
        // 本规则内每个变量的静态三值（第一条可解析声明, 即 rgb 回退）
        const localValue = new Map()
        for (const [prop, decls] of byProp) {
          for (const d of decls) {
            const t = parseRgbTriplet(d.value)
            if (t) {
              localValue.set(prop, t)
              break
            }
          }
        }
        const resolve = (prop, depth = 0) => {
          if (depth > 8) return null
          if (localValue.has(prop)) return localValue.get(prop)
          const decls = byProp.get(prop)
          if (decls) {
            for (const d of decls) {
              const m = d.value.match(/^var\(\s*(--[a-zA-Z0-9-]+)/)
              if (m) {
                const r = resolve(m[1], depth + 1)
                if (r) return r
              }
            }
          }
          return constants.get(prop) ?? null
        }
        for (const [prop, decls] of byProp) {
          if (prop.endsWith('-rgb')) continue
          const t = resolve(prop)
          if (!t) continue
          decls[decls.length - 1].cloneAfter({ prop: prop + '-rgb', value: t })
        }
      })

      // ---------- 3. 改写 color-mix(var() N%, transparent) ----------
      // 色彩空间对「与 transparent 混合 = 加透明度」的等价换算无影响, 全部空间通用。
      // 注: 落在 @supports (color: color-mix(...)) 块内的声明旧浏览器本就整块跳过
      // （HeroUI/Tailwind 已在块前提供实色回退）, 此处改写仅对未受保护的声明生效。
      root.walkDecls((decl) => {
        if (!decl.value.includes('color-mix(')) return
        const replaced = decl.value.replace(
          /color-mix\(\s*in\s+[a-z-]+\s*,\s*((?:[^()]|\([^()]*(?:\([^()]*\))*[^()]*\))*)\)/gi,
          (whole, argsStr) => {
            const mix = matchTransparentMix(argsStr)
            if (!mix) return whole
            const rgbVars = mix.vars.map((v) => v + '-rgb')
            // var 回退链保持同构: rgb(var(--a-rgb, var(--b-rgb)) / N%)
            let inner = `var(${rgbVars[rgbVars.length - 1]})`
            for (let i = rgbVars.length - 2; i >= 0; i--) inner = `var(${rgbVars[i]}, ${inner})`
            return `rgb(${inner} / ${mix.percent}%)`
          },
        )
        if (replaced !== decl.value) {
          // 回退声明供旧浏览器使用。前置插件（@csstools/postcss-color-mix-function）
          // 对含 var() 的混色无法静态求值, 会把原声明包进
          //   @supports (color: color-mix(...)) { <同选择器规则> { 原声明 } }
          // 并在块外留下粗暴的实色回退（如 background: var(--foreground), 旧浏览器
          // 下呈现为高反差的纯色）。旧浏览器整块跳过 @supports, 因此精确回退必须以
          // 【同选择器的独立规则】插到 @supports 块之前、与其同层（可能嵌在 @media
          // 等之内）。此时级联顺序为:
          //   实色回退 → 本精确回退（同特异性、后出现者胜）→ @supports 内 color-mix（现代浏览器）
          // 注意: decl.parent 永远是规则节点, @supports 是规则的父级, 而非声明的父级。
          const rule = decl.parent
          const supports = rule && rule.parent
          const inMixSupports =
            rule &&
            rule.type === 'rule' &&
            supports &&
            supports.type === 'atrule' &&
            supports.name === 'supports' &&
            /color-mix\(/.test(supports.params)
          if (inMixSupports) {
            const fallbackRule = rule.clone({ nodes: [] })
            fallbackRule.append(decl.clone({ value: replaced }))
            supports.parent.insertBefore(supports, fallbackRule)
          } else {
            decl.cloneBefore({ value: replaced })
          }
        }
      })

      // ---------- 4. 拆分含 :has() 的选择器列表 ----------
      root.walkRules((rule) => {
        if (!rule.selector.includes(':has(')) return
        // 顶层逗号拆分（括号内的逗号不算, 如 :is(a, b) / :has([x=y])）
        const selectors = []
        let depth = 0
        let cur = ''
        for (const ch of rule.selector) {
          if (ch === '(' || ch === '[') depth++
          if (ch === ')' || ch === ']') depth--
          if (ch === ',' && depth === 0) {
            selectors.push(cur.trim())
            cur = ''
          } else {
            cur += ch
          }
        }
        selectors.push(cur.trim())
        const plain = selectors.filter((s) => !s.includes(':has('))
        const hasOnes = selectors.filter((s) => s.includes(':has('))
        if (!plain.length || !hasOnes.length) return
        // 原规则只保留 :has() 选择器（105+ 生效）, 前面插入纯选择器版本（全版本生效）
        rule.cloneBefore({ selector: plain.join(', ') })
        rule.selector = hasOnes.join(', ')
      })
    },
  }
}
postcssLegacyColor.postcss = true
