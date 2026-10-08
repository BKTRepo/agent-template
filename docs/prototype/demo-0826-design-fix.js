// 修订版：五类改造类型前置选择，并作为后续裁剪匹配依据。
const d82FiveChangeTypes = [
  ['framework','基座替换或研发框架升级','系统基座、运行时、研发框架或公共组件变化'],
  ['database','数据库替换','数据库产品替换、迁移或读写兼容改造'],
  ['middleware','中间件升级替换','消息、缓存、RPC、网关、连接池等变化'],
  ['os','服务器 / 操作系统替换','服务器、操作系统、部署和运行环境变化'],
  ['browser','终端 / 浏览器适配','浏览器、客户端、终端和前端控件变化']
];
state.changes = new Set(Array.from(state.changes||[]).map(x=>x==='interface'?'middleware':x).filter(x=>d82FiveChangeTypes.some(y=>y[0]===x)));
function d82ChangeTypeSection(){return `<div class="design-section"><h3>改造类型 / 信创技术栈（五类）</h3><p>改造类型和信创技术栈为同一字段；第 01 步选择后，后续功能与非功能裁剪将自动匹配对应策略明细。</p><div class="d82-change-type-grid">${d82FiveChangeTypes.map(x=>`<label class="d82-change-type"><input type="checkbox" data-d82-change="${x[0]}" ${state.changes.has(x[0])?'checked':''}/><span><b>${x[1]}</b><small>${x[2]}</small></span></label>`).join('')}</div></div>`}
const d82RenderAnalysisOld = d82RenderAnalysis;
d82RenderAnalysis = function(){ const html=d82RenderAnalysisOld(); const marker='<div class="design-section"><div class="signal-config-head"><div><h3>涉及系统与自动化水平'; return html.includes(marker) ? html.replace(marker,d82ChangeTypeSection()+marker) : html+d82ChangeTypeSection(); };
const d82BindAnalysisOld = d82BindAnalysis;
d82BindAnalysis = function(){
  d82BindAnalysisOld();
  document.querySelectorAll('[data-d82-change]').forEach(x=>x.onchange=e=>{if(e.target.checked)state.changes.add(e.target.dataset.d82Change);else state.changes.delete(e.target.dataset.d82Change);d82RenderStep();});
};
const d82MakeOutputOld = d82MakeOutput;
d82MakeOutput = function(){
  const names = d82FiveChangeTypes.filter(x=>state.changes.has(x[0])).map(x=>x[1]).join('、') || '未选择';
  return `<section class="output-section"><h3>改造类型 / 信创技术栈</h3><div class="output-cell"><strong>本次选择</strong><span>${d82Esc(names)}</span></div></section>${d82MakeOutputOld()}`;
};
d82RenderStep();
