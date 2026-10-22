// 必须最先加载: 旧浏览器（Chrome/Edge 90~110）Web API 垫片
// （checkVisibility / structuredClone, core-js 不覆盖 DOM API）
import '@/lib/legacy-shims'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
// 样式不在此处 import: 由 scripts/build-css.mjs 预编译为 public/app.css,
// index.html 以 <link> 直接加载（dev / build 同一机制, 兼容旧浏览器）

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
