// 0826 裁剪器本轮需求调整：需求编号、系统下拉、自动化资产回显、备注、文字准入和策略下载。
state.reqId = state.reqId || '';

const d82SystemCatalog = ['核心交易系统','渠道门户','数据服务','统一门户','业务中台','账务系统','数据交换平台','其他系统'];

function d82AutomationAsset(value){
  return String(value || '').includes('无') ? '无自动化资产' : '有自动化资产';
}

function d82SystemOptions(current){
  const list = current && !d82SystemCatalog.includes(current) ? [current, ...d82SystemCatalog] : d82SystemCatalog;
  return list.map(x => `<option value="${d82Esc(x)}" ${x === current ? 'selected' : ''}>${d82Esc(x)}</option>`).join('');
}

function d82NormalizeSystems(){
  state.systems = Array.isArray(state.systems) && state.systems.length ? state.systems : [{name:'核心交易系统',automation:'无自动化资产',testDept:'待确认'}];
  state.systems.forEach(x => {
    x.automation = d82AutomationAsset(x.automation);
    if (!x.name) x.name = '其他系统';
    if (!x.testDept) x.testDept = '待确认';
    delete x.ui;
    delete x.owner;
  });
}

function d82SystemTableRevision(){
  d82NormalizeSystems();
  return `<div class="design-section"><div class="signal-config-head"><div><h3>涉及系统与自动化水平</h3><p>选择本需求涉及的系统，并回显该系统是否已有可复用的接口/UI 自动化资产。</p></div><button id="d82AddSystem" class="mini-btn">＋ 新增系统</button></div><table class="design-table system-table"><thead><tr><th>涉及系统</th><th>接口/UI 自动化</th><th>是否测试部测试</th><th></th></tr></thead><tbody>${state.systems.map((x,i)=>`<tr><td><select data-d82-system-name="${i}">${d82SystemOptions(x.name)}</select></td><td><select data-d82-system-auto="${i}"><option ${x.automation==='有自动化资产'?'selected':''}>有自动化资产</option><option ${x.automation==='无自动化资产'?'selected':''}>无自动化资产</option></select></td><td><select data-d82-system-dept="${i}">${['是','部分','否','待确认'].map(v=>`<option ${v===(x.testDept||'待确认')?'selected':''}>${v}</option>`).join('')}</select></td><td><button class="mini-btn danger" data-d82-remove-system="${i}">移除</button></td></tr>`).join('')}</tbody></table></div>`;
}

d82RenderAnalysis = function(){
  d82NormalizeSystems();
  return `<div class="eyebrow">步骤 01 · 需求分析</div><h2>先把需求编号、改造对象和系统自动化画像说清楚</h2><p class="intro">本步骤只登记需求基本信息、五类信创技术栈和涉及系统的自动化资产状态，作为后续裁剪匹配依据。</p><div class="analysis-grid"><div class="design-section"><h3>基本信息</h3><div class="field-inline"><label>需求编号<input id="d82ReqId" placeholder="请输入需求编号" value="${d82Esc(state.reqId)}"/></label><label>需求名称<input id="d82Name" value="${d82Esc(state.name||'未命名信创需求')}"/></label><label>测试周期<select id="d82Duration">${['≤5个工作日','6-15个工作日','>15个工作日'].map(x=>`<option ${x===state.duration?'selected':''}>${x}</option>`).join('')}</select></label></div></div></div>${d82ChangeTypeSection()}${d82SystemTableRevision()}<div class="design-note"><b>本步骤输出：</b>需求编号、需求名称、测试周期、改造类型 / 信创技术栈和涉及系统自动化资产画像。</div>`;
};

d82BindAnalysis = function(){
  document.getElementById('d82ReqId')?.addEventListener('input', e => state.reqId = e.target.value);
  document.getElementById('d82Name')?.addEventListener('input', e => state.name = e.target.value);
  document.getElementById('d82Duration')?.addEventListener('change', e => state.duration = e.target.value);
  document.querySelectorAll('[data-d82-change]').forEach(x => x.onchange = e => { if(e.target.checked) state.changes.add(e.target.dataset.d82Change); else state.changes.delete(e.target.dataset.d82Change); d82RenderStep(); });
  document.getElementById('d82AddSystem')?.addEventListener('click', () => { state.systems.push({name:'其他系统',automation:'无自动化资产',testDept:'待确认'}); d82RenderStep(); });
  document.querySelectorAll('[data-d82-system-name]').forEach(x => x.onchange = e => state.systems[Number(e.target.dataset.d82SystemName)].name = e.target.value);
  document.querySelectorAll('[data-d82-system-auto]').forEach(x => x.onchange = e => state.systems[Number(e.target.dataset.d82SystemAuto)].automation = e.target.value);
  document.querySelectorAll('[data-d82-system-dept]').forEach(x => x.onchange = e => state.systems[Number(e.target.dataset.d82SystemDept)].testDept = e.target.value);
  document.querySelectorAll('[data-d82-remove-system]').forEach(x => x.onclick = () => { state.systems.splice(Number(x.dataset.d82RemoveSystem), 1); d82RenderStep(); });
};

d82RenderFunctional = function(){
  const ids = d82ActiveChanges();
  return `<div class="eyebrow">步骤 02 · 功能测试裁剪</div><h2>按 9.1 裁剪明细确定必测、条件测试和裁剪</h2><p class="intro">“裁剪”必须填写备注，并由测试经理确认。核心链路、关键数据和端到端风险不得以空白理由裁剪。</p>${ids.length ? `<table class="design-table matrix-table"><thead><tr><th>改造类型</th><th>建议纳入的功能测试内容</th><th>9.1裁剪参考</th><th>结论</th><th>备注</th></tr></thead><tbody>${ids.map(id=>{const x=d82FunctionalCatalog[id]||d82FunctionalCatalog.interface;const d=d82ChangeDecision(id,'必测');return `<tr><td><b>${x.title}</b></td><td>${x.content}</td><td>${x.cut}</td><td><select data-d82-func-status="${id}">${['必测','条件测试','裁剪'].map(v=>`<option ${v===d.status?'selected':''}>${v}</option>`).join('')}</select></td><td><textarea data-d82-func-reason="${id}" placeholder="填写本项裁剪或执行备注">${d82Esc(d.reason)}</textarea></td></tr>`}).join('')}</tbody></table>` : '<div class="design-note">尚未选择改造对象，请返回第 01 步补充改造对象识别。</div>'}<div class="design-note"><b>功能团队填充区：</b>功能团队可在本表基础上继续补充具体案例、数据要求、场景集和领域裁剪边界。</div>`;
};

d82RenderNonfunctional = function(){
  const ids = d82ActiveChanges().filter(id => d82NfCatalog[id]);
  const admissions = ['系统架构稳定，测试周期内不再发生影响专项结论的架构变更。','功能冒烟通过且无大面积功能变更，专项环境和关联应用连通性校验通过。','性能/高可用目标、容量模型、基线、监控、脚本、测试数据和支持人员已准备。','需要时已同步生产铺底数据，并已确认测试环境与生产配置差异。'];
  return `<div class="eyebrow">步骤 03 · 非功能测试裁剪</div><h2>按 9.2 裁剪专项范围、准入与备注</h2><p class="intro">非功能专项的阈值、负载模型和报告口径由非功能测试团队补充；本步骤完成触发判断和裁剪结论。</p><div class="design-section nf-admission-text"><h3>非功能测试准入确认</h3><p>以下为准入要求，采用文字确认，不设置勾选项：</p><ol>${admissions.map(x=>`<li>${x}</li>`).join('')}</ol></div>${ids.length ? `<table class="design-table matrix-table"><thead><tr><th>信创技术栈</th><th>性能及高可用测试策略</th><th>9.2裁剪参考</th><th>结论</th><th>备注</th></tr></thead><tbody>${ids.map(id=>{const x=d82NfCatalog[id],d=d82NfDecision(id);return `<tr><td><b>${x.title}</b></td><td>${x.strategy}</td><td>${x.cut}</td><td><select data-d82-nf-status="${id}">${['必测','条件测试','裁剪'].map(v=>`<option ${v===d.status?'selected':''}>${v}</option>`).join('')}</select></td><td><textarea data-d82-nf-reason="${id}" placeholder="填写本项裁剪或执行备注">${d82Esc(d.reason)}</textarea></td></tr>`}).join('')}</tbody></table>` : '<div class="design-note">当前改造对象未命中 9.2 专项，请保留“不适用”说明并由测试经理确认。</div>'}<div class="design-note"><b>专项结论要求：</b>未执行场景需说明 NA 原因；未达指标时必须经过分析调优、影响评估和书面处置，不能以口头承诺放行。</div>`;
};

function d82ListRevision(items){ return `<ul>${items.map(x=>`<li>${x}</li>`).join('')}</ul>`; }

function d82OutputDemandRevision(){
  const selectedTypes = d82FiveChangeTypes.map(x=>`<span class="history-badge">${d82Esc(x[1])}：${state.changes.has(x[0])?'已选择':'未选择'}</span>`).join('');
  const systems = state.systems.map(x=>`<tr><td>${d82Esc(x.name)}</td><td>${d82Esc(d82AutomationAsset(x.automation))}</td><td>${d82Esc(x.testDept||'待确认')}</td></tr>`).join('');
  return `<section class="output-section"><h3>一、需求分析工件</h3><div class="output-grid"><div class="output-cell"><strong>需求编号</strong><span>${d82Esc(state.reqId||'未填写')}</span></div><div class="output-cell"><strong>需求名称</strong><span>${d82Esc(state.name||'未命名信创需求')}</span></div><div class="output-cell"><strong>测试周期</strong><span>${d82Esc(state.duration||'未填写')}</span></div></div><h4>改造类型 / 信创技术栈勾选</h4><p>${selectedTypes}</p><h4>涉及系统与自动化资产</h4><table class="design-table"><thead><tr><th>涉及系统</th><th>接口/UI自动化</th><th>是否测试部测试</th></tr></thead><tbody>${systems||'<tr><td colspan="3">未填写</td></tr>'}</tbody></table></section>`;
}

function d82OutputFunctionalRevision(){
  const rows = d82ActiveChanges().filter(id=>d82FunctionalCatalog[id]).map(id=>{const x=d82FunctionalCatalog[id],d=d82ChangeDecision(id);return `<tr><td><b>${d82Esc(x.title)}</b></td><td>${d82Esc(x.content)}</td><td>${d82Esc(x.cut)}</td><td>${d82Esc(d.status)}</td><td>${d82Esc(d.reason||'无补充备注')}</td></tr>`}).join('');
  return `<section class="output-section"><h3>二、功能测试裁剪工件（参考 9.1）</h3><table class="design-table"><thead><tr><th>改造类型</th><th>测试要求</th><th>裁剪明细</th><th>裁剪结论</th><th>备注</th></tr></thead><tbody>${rows||'<tr><td colspan="5">未选择改造类型</td></tr>'}</tbody></table><h4>功能测试准入</h4>${d82ListRevision(['需求/设计评审通过，版本、环境、外部依赖可识别。','功能范围裁剪清单已确认，测试数据、账号、权限和核验规则已准备。','核心链路、历史事件、跨系统依赖和端到端范围已识别。'])}<h4>功能测试准出</h4>${d82ListRevision(['必测项均已执行并取得明确结果，裁剪项有备注或替代验证。','核心链路、关键数据、接口/落表和端到端证据完整。','缺陷、数据差异、阻塞和遗留风险已登记、复测或完成书面处置。'])}</section>`;
}

function d82OutputNfRevision(){
  const rows = d82ActiveChanges().filter(id=>d82NfCatalog[id]).map(id=>{const x=d82NfCatalog[id],d=d82NfDecision(id);return `<tr><td><b>${d82Esc(x.title)}</b></td><td>${d82Esc(x.strategy)}</td><td>${d82Esc(x.cut)}</td><td>${d82Esc(d.status)}</td><td>${d82Esc(d.reason||'无补充备注')}</td></tr>`}).join('');
  return `<section class="output-section"><h3>三、非功能测试裁剪工件（参考 9.2）</h3><h4>非功能测试准入确认</h4>${d82ListRevision(['系统架构稳定，专项环境和连通性校验通过。','功能冒烟通过，专项目标、基线、容量模型、监控、脚本、数据和支持人员已准备。','需要时已同步生产铺底数据，并确认测试环境与生产配置差异。'])}<table class="design-table"><thead><tr><th>信创技术栈</th><th>测试要求 / 策略</th><th>裁剪明细</th><th>裁剪结论</th><th>备注</th></tr></thead><tbody>${rows||'<tr><td colspan="5">未命中专项，需保留不适用说明</td></tr>'}</tbody></table><h4>非功能测试准出</h4>${d82ListRevision(['所有纳入场景完成；不适用场景有 NA 原因。','专项指标达标，或已完成分析调优、影响评估、责任人/期限和书面风险处置。','原始结果、专项报告、复测记录和遗留问题完整归档。'])}</section>`;
}

d82MakeOutput = function(){ return `${d82OutputDemandRevision()}${d82OutputFunctionalRevision()}${d82OutputNfRevision()}${d82OutputTools()}${d82OutputGates()}${d82OutputCollab()}`; };

d82SaveHistory = function(){
  const rows = d82HistoryRead();
  rows.unshift({id:`S-${Date.now()}`,reqId:state.reqId||'',name:state.name||'未命名信创需求',risk:d82ActiveChanges().length,createdAt:new Date().toISOString(),changes:d82ActiveChanges().map(x=>changeMeta[x]?.name||x),state:d82Snapshot()});
  d82HistoryWrite(rows);
};

d82RenderHistory = function(){
  const list=document.getElementById('d82HistoryList'); if(!list)return;
  const q=(document.getElementById('d82HistorySearch')?.value||'').toLowerCase();
  const rows=d82HistoryRead().filter(x=>!q||[x.reqId,x.name,...(x.changes||[])].join(' ').toLowerCase().includes(q));
  list.innerHTML=rows.length?rows.map(x=>`<div class="history-row"><div class="history-main"><b>${d82Esc(x.name)}</b><div class="history-meta"><span>${d82Esc(x.reqId||'未填写编号')}</span><span>${d82Esc(new Date(x.createdAt).toLocaleString('zh-CN'))}</span><span>${d82Esc((x.changes||[]).slice(0,3).join('、'))}</span></div></div><div class="history-actions"><button class="primary" data-d82-history-load="${d82Esc(x.id)}">载入编辑</button><button class="danger" data-d82-history-delete="${d82Esc(x.id)}">删除</button></div></div>`).join(''):'<div class="history-empty">暂无历史策略。完成第 06 步生成最终指引后，记录会自动保存。</div>';
  list.querySelectorAll('[data-d82-history-load]').forEach(b=>b.onclick=()=>d82LoadHistory(b.dataset.d82HistoryLoad));
  list.querySelectorAll('[data-d82-history-delete]').forEach(b=>b.onclick=()=>{d82HistoryWrite(d82HistoryRead().filter(x=>x.id!==b.dataset.d82HistoryDelete));d82RenderHistory();});
};

function d82DownloadStrategy(){
  const title = `《${state.name||'未命名信创需求'}测试策略》`;
  const safe = String(state.reqId||state.name||'信创测试策略').replace(/[\\/:*?"<>|]/g,'_');
  const css = `body{font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif;color:#243b4a;background:#fff;margin:32px;line-height:1.6}h1{font-size:24px;border-bottom:2px solid #168c83;padding-bottom:10px}h2{font-size:18px;color:#168c83;margin-top:28px}h3{font-size:16px;color:#168c83;margin-top:20px}h4{font-size:14px;color:#355766;margin-bottom:6px}table{width:100%;border-collapse:collapse;margin:10px 0 18px;font-size:12px}th,td{border:1px solid #c8d7df;padding:8px;vertical-align:top;text-align:left}th{background:#edf7f5;color:#244a56}td{background:#fff}ul{padding-left:22px}.output-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.output-cell{border:1px solid #c8d7df;border-radius:6px;padding:10px}.output-cell strong,.output-cell span{display:block}.output-cell strong{font-size:12px;color:#52707c}.output-cell span{font-size:13px}.history-badge{display:inline-block;border:1px solid #9acbc2;border-radius:14px;padding:3px 8px;margin:3px;color:#24695f;font-size:12px}.muted{color:#657f8a;font-size:12px}`;
  const doc = `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><title>${d82Esc(title)}</title><style>${css}</style></head><body><h1>${d82Esc(title)}</h1><p class="muted">依据《信创项目测试指引0826》生成，最终范围、责任和例外结论由测试经理确认。</p>${d82MakeOutput()}</body></html>`;
  const blob = new Blob([doc],{type:'text/html;charset=utf-8'});
  const url = URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=`${safe}-测试策略.html`; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000); toast('策略文档已下载');
}

function d82InjectRevisionUi(){
  const grade=document.getElementById('d82HistoryGrade'); if(grade) grade.remove();
  const search=document.getElementById('d82HistorySearch'); if(search) search.placeholder='搜索需求编号、需求名称或改造类型';
  const step0=document.querySelector('[data-step="0"] small'); if(step0) step0.textContent='需求编号、系统与自动化画像';
  const actions=document.querySelector('.output-actions');
  if(actions && !document.getElementById('d82Download')){const b=document.createElement('button');b.id='d82Download';b.className='btn primary';b.textContent='下载策略文档';actions.appendChild(b);b.addEventListener('click',d82DownloadStrategy);}
  const style=document.createElement('style'); style.textContent=`body.design-page,.design-page .app-shell,.design-page .workspace{background:#fff;color:#243b4a}.design-page .topbar,.design-page .stepbar,.design-page .editor,.design-page .preview-panel{background:#fff;border-color:#d6e1e5;box-shadow:0 8px 24px rgba(39,78,91,.06)}.design-page .topbar h1,.design-page .editor h2,.design-page .stepbar-title{color:#183c49}.design-page .topbar p,.design-page .intro,.design-page .muted{color:#607985}.design-page .step{color:#56717b}.design-page .step:hover{background:#f2f8f7}.design-page .step.active{background:#e9f7f4;color:#147d70}.design-page .role-note{background:#f5fbfa;color:#55737c}.design-page .role-note strong{color:#2b5d68}.design-page .design-section,.design-page .design-table td,.design-page .prereq-item,.design-page .principle-card,.design-page .output-cell,.design-page .history-row{background:#fff;color:#243b4a}.design-page .design-table input,.design-page .design-table select,.design-page .design-table textarea,.design-page .design-section input,.design-page .design-section select,.design-page .design-section textarea,.design-page .history-filters input,.design-page .history-filters select{background:#fff!important;color:#243b4a!important;border-color:#9db8c2}.design-page .design-table th{color:#52707c}.design-page .mini-btn{background:#f5fbfa;color:#176e64;border-color:#91c8c0}.design-page .mini-btn.danger{background:#fff4f3;color:#a6453e;border-color:#d9aaa5}.design-page .history-dialog{background:#fff;color:#243b4a}.design-page .history-head h2{color:#183c49}.design-page .history-close{background:#edf6f5;color:#38646d}.design-page .history-meta,.design-page .history-note{color:#607985}.design-page .history-meta span{background:#edf7f5;color:#39706b}.design-page .history-actions button{background:#f4f9fa;color:#315864;border-color:#b3c9d0}.design-page .history-actions button.primary{background:#168c83;color:#fff;border-color:#168c83}.design-page .nf-admission-text ol{margin:10px 0 0;padding-left:22px;color:#405f6c}.design-page .output-sheet{background:#fff;color:#243b4a}.design-page .output-section h3,.design-page .output-section h4{color:#196f68}`; document.head.appendChild(style);
}

d82InjectRevisionUi();
document.getElementById('d82HistorySearch')?.addEventListener('input',d82RenderHistory);
d82RenderStep();
