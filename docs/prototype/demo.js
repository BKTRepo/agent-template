const state = {
  step: 0,
  name: '核心交易系统信创改造',
  category: '项目需求',
  importance: '核心系统',
  duration: '6-15个工作日',
  flags: { core: true, money: true, sensitive: true, multi: true, code: true, probe: true, stableApi: true, stableUi: false },
  changes: new Set(['database', 'middleware', 'os']),
  scope: {},
  gates: {},
};

const changeMeta = {
  database: { name: '数据库替换 / 数据迁移', desc: '兼容性、数据一致性、SQL / 事务与性能基线', risk: 23, code: 'DB_REPLACE_001' },
  middleware: { name: '中间件升级 / 替换', desc: '接口、会话、消息、事务与异常补偿', risk: 18, code: 'MIDDLEWARE_CHANGE_001' },
  os: { name: '操作系统 / 服务器替换', desc: '部署、文件权限、网络、运行稳定性', risk: 16, code: 'OS_REPLACE_001' },
  framework: { name: '研发框架 / 运行时替换', desc: '代码兼容、调用链与影响范围', risk: 20, code: 'FRAMEWORK_CHANGE_001' },
  browser: { name: '浏览器 / 终端替换', desc: '页面兼容、控件、下载与交互链路', risk: 10, code: 'BROWSER_CHANGE_001' },
  interface: { name: '接口、报文或批处理改造', desc: '契约、格式、落表、对账与异步处理', risk: 17, code: 'INTERFACE_CHANGE_001' },
};

const baseScopes = [
  { id: 'main', title: '核心业务主流程', detail: '覆盖核心交易、关键状态流转及关键业务规则', status: '必测' },
  { id: 'exception', title: '异常、回退与补偿场景', detail: '覆盖超时、重复、失败重试、回滚与补偿处理', status: '条件测试', when: '多系统交互、中间件或接口改造时升级为必测' },
  { id: 'history', title: '历史事件与回归案例', detail: '关联同类生产事件、历史缺陷及高频回归案例', status: '必测' },
];

function has(id) { return state.changes.has(id); }
function selectedChanges() { return [...state.changes]; }
function riskScore() {
  let score = selectedChanges().reduce((sum, id) => sum + changeMeta[id].risk, 0);
  if (state.importance === '核心系统') score += 15;
  if (state.flags.money) score += 12;
  if (state.flags.sensitive) score += 8;
  if (state.flags.multi) score += 8;
  if (selectedChanges().length >= 3) score += 10;
  return Math.min(score, 100);
}
function depth() { const s = riskScore(); return s >= 65 ? '深度验证' : s >= 35 ? '重点验证' : '基础验证'; }
function rules() { return ['BASELINE_001', ...selectedChanges().map(id => changeMeta[id].code), state.flags.multi ? 'E2E_REQUIRED_001' : '', state.flags.code && state.flags.probe ? 'PRECISE_TEST_001' : ''].filter(Boolean); }
function getScopes() {
  const out = [...baseScopes];
  if (has('database')) out.push({ id:'data', title:'数据一致性与迁移校验', detail:'关键字段、账务余额、状态、落表及允许差异说明', status:'必测' });
  if (has('middleware') || has('interface')) out.push({ id:'contract', title:'接口契约与消息链路', detail:'请求响应、消息顺序、重复消费、超时与补偿', status:'必测' });
  if (has('os')) out.push({ id:'deploy', title:'部署与运行环境适配', detail:'安装、配置、权限、网络、日志、启停与故障恢复', status:'必测' });
  if (has('framework')) out.push({ id:'impact', title:'变更影响范围与补测', detail:'调用链、变更代码路径、未覆盖高风险路径', status:'条件测试', when:'具备源码、分支一致及可采集探针时执行精准测试' });
  if (has('browser')) out.push({ id:'ui', title:'页面与终端兼容性', detail:'关键页面、控件、下载、权限提示与交互体验', status:'必测' });
  if (state.flags.multi) out.forEach(x => { if (x.id === 'exception') x.status = '必测'; });
  return out.map(x => ({ ...x, status: state.scope[x.id] || x.status }));
}
function tools() {
  const out = [];
  const add = (name, level, phase, precondition, input, output, reason) => out.push({name, level, phase, precondition, input, output, reason});
  if (state.flags.stableApi || has('middleware') || has('interface')) add('接口自动化', '必用', '功能测试执行与回归', '接口契约、环境、账号、稳定数据与断言齐备', '接口清单、请求样例、断言规则、测试数据', '脚本执行报告、失败明细、接口证据', '稳定高频接口或消息链路应优先自动化回归');
  if (has('database') || has('interface') || has('middleware')) add('测试工具箱 · 数据/报文核验', '必用', '联调、迁移验证与结果检查', '字段映射、比对规则、样例、允许差异、只读权限齐备', '源/目标数据、报文、字段映射、比对口径', '差异清单、比对报告、造数与核验记录', '涉及落表、对账、消息、文件或迁移时必须核验数据一致性');
  if (has('framework') || (state.flags.code && state.flags.probe)) add('精准测试平台', '条件使用', '影响分析、补测与回归', '源码、版本、分支、探针与调用轨迹基线一致', '变更集、版本信息、探针数据、历史覆盖基线', '影响分析、覆盖路径、候选补测清单', '仅在前置一致时可用于补测建议；不以工具结果直接替代测试结论');
  if (has('browser') && state.flags.stableUi) add('UI 自动化', '条件使用', '高频回归', '元素定位稳定、页面规则稳定、可重复数据', '页面流程、元素定位、断言、数据准备', '执行报告、截图、失败日志', '适合稳定黄金页面；频繁变更或一次性场景不强行自动化');
  if (state.flags.multi || has('middleware') || has('interface')) add('调用链 / 日志辅助定位', '条件使用', '端到端执行与异常定位', '链路 ID、日志可观测、环境权限与关键节点清晰', '核心链路、流水号、日志范围、节点清单', '链路轨迹、定位线索、异常证据', '多系统、异步消息和异常补偿场景用于取证与定位');
  if (out.length === 0) add('人工验证 + 工具箱辅助', '条件使用', '测试执行', '测试环境、数据、账号与业务口径齐备', '案例、数据、验证口径', '执行记录、截图或日志证据', '当前改造特征未命中强制工具组合，保留人工验证为主');
  return out;
}
function nonfunctional() {
  const out = [];
  if (has('database') || has('middleware') || has('os')) out.push(['性能与容量', '关键交易响应、吞吐、资源使用与改造前基线对比', '条件测试']);
  if (has('os') || has('middleware')) out.push(['稳定性与恢复', '启停、故障恢复、连接重建、日志与告警', '条件测试']);
  if (has('browser')) out.push(['兼容性与体验', '目标浏览器/终端、关键控件、下载与交互', '必测']);
  if (state.flags.sensitive) out.push(['安全与数据保护', '权限、敏感数据展示、传输与脱敏要求', '条件测试']);
  return out.length ? out : [['非功能专项', '结合系统等级、容量与监管要求，由专项团队补充裁剪依据', '条件测试']];
}
function gates() {
  const hard = [
    {id:'h_scope', text:'已裁定为“必测”的核心链路均有执行证据', note:'案例、结果、日志/截图或流水可追溯'},
    {id:'h_defect', text:'无未处置的阻塞或严重缺陷', note:'遗留项必须进入风险或例外处置'},
    {id:'h_tool', text:'工具结果的版本、环境、数据与脚本/探针信息完整', note:'前置不满足不得标记为已覆盖'},
  ];
  if (has('database')) hard.push({id:'h_data', text:'关键数据差异已关闭或形成经确认的差异说明', note:'禁止以未解释的数据差异通过'});
  if (state.flags.multi) hard.push({id:'h_e2e', text:'端到端案例、流水/截图与结论完整', note:'多系统核心链路不可裁剪'});
  const soft = [
    {id:'s_auto', text:'已裁定的自动化任务通过率达到项目阈值', note:'阈值由测试经理结合项目基线确认'},
    {id:'s_cover', text:'高风险变更影响路径已分析并完成补测', note:'具备精准测试前提时，附影响分析报告'},
  ];
  const red = [
    {id:'r_core', text:'核心业务主流程未验证即申请准出', note:'触碰即阻断并补测'},
    {id:'r_evidence', text:'以工具“通过”替代业务/专项测试结论', note:'触碰即整改，必须交叉核验'},
  ];
  return {hard, soft, red};
}
function esc(s) { return String(s).replace(/[&<>"]/g, c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c])); }
function tag(text, kind='') { return `<span class="tag ${kind}">${esc(text)}</span>`; }
function options(items, selected) { return items.map(x=>`<option ${x===selected?'selected':''}>${x}</option>`).join(''); }
function checked(b) { return b ? 'checked' : ''; }

function renderStep() {
  const c = document.getElementById('stepContent');
  const renderers = [renderPersona, renderChanges, renderScope, renderTools, renderNonFunctional, renderGates];
  c.innerHTML = renderers[state.step]();
  bindCurrentStep();
  document.querySelectorAll('.step').forEach(b => b.classList.toggle('active', Number(b.dataset.step) === state.step));
  document.getElementById('prevBtn').disabled = state.step === 0;
  const next = document.getElementById('nextBtn');
  next.textContent = state.step === 5 ? '生成执行细则' : '下一步 →';
  document.getElementById('stepHint').textContent = `${state.step + 1} / 6`;
}
function renderPersona() { return `
  <div class="eyebrow">步骤 01 · 需求画像</div><h2>先识别需求的“风险底色”</h2><p class="intro">需求画像决定测试深度与后续裁剪。此处的选择可以在项目承接时由测试经理补全。</p>
  <div class="form-grid"><div class="field"><label>需求名称</label><input id="nameInput" value="${esc(state.name)}" /></div><div class="field"><label>计划测试周期</label><select id="durationInput">${options(['≤5个工作日','6-15个工作日','>15个工作日'],state.duration)}</select></div></div>
  <div class="form-section"><h3>需求类型</h3><div class="choice-row" data-choice="category">${['项目需求','常规变更','紧急修复'].map(x=>`<button class="chip ${state.category===x?'selected':''}" data-value="${x}">${x}</button>`).join('')}</div></div>
  <div class="form-section"><h3>系统重要性</h3><div class="choice-row" data-choice="importance">${['核心系统','重要系统','一般系统'].map(x=>`<button class="chip ${state.importance===x?'selected':''}" data-value="${x}">${x}</button>`).join('')}</div></div>
  <div class="form-section"><h3>业务与技术信号</h3><div class="toggle-grid">
    ${toggle('core','涉及核心业务主线','主交易、主流程或监管关键链路')}${toggle('money','涉及账务/资金','余额、金额、对账或清结算')}${toggle('sensitive','涉及敏感数据','客户信息、权限或敏感字段')}${toggle('multi','跨系统/异步交互','消息、文件、接口、多系统协同')}${toggle('code','存在应用代码变更','可提供变更集、分支或代码评审')}${toggle('probe','具备探针/轨迹条件','版本、分支、探针与基线可保持一致')}${toggle('stableApi','接口适合重复执行','契约、数据与断言可稳定维护')}${toggle('stableUi','页面适合重复执行','元素定位和页面规则稳定')}
  </div></div>
  <div class="hint-box">提示：系统画像只用于规则建议。测试范围、工具是否采用及结论由测试经理最终裁定。</div>`; }
function toggle(id, title, desc) { return `<label class="toggle-card ${state.flags[id]?'selected':''}"><input type="checkbox" data-flag="${id}" ${checked(state.flags[id])}/><b>${title}</b><small>${desc}</small></label>`; }
function renderChanges() { return `
  <div class="eyebrow">步骤 02 · 改造特征</div><h2>选择本次改造真正触及的对象</h2><p class="intro">可多选。系统会将改造类型映射为测试场景、工具组合与门禁要求。</p>
  <div class="toggle-grid">${Object.entries(changeMeta).map(([id,x])=>`<label class="toggle-card ${has(id)?'selected':''}"><input type="checkbox" data-change="${id}" ${checked(has(id))}/><b>${x.name}</b><small>${x.desc}</small></label>`).join('')}</div>
  <div class="form-section"><div class="decision-note"><b>当前识别：</b>${selectedChanges().length?selectedChanges().map(id=>changeMeta[id].name).join('、'):'尚未选择改造对象'}。${selectedChanges().length>=3?'多类改造叠加，系统将自动提高端到端、数据核验和环境适配的优先级。':'可继续补充改造对象，策略会实时更新。'}</div></div>`; }
function renderScope() { const scopes = getScopes(); return `
  <div class="eyebrow">步骤 03 · 功能测试裁剪</div><h2>明确“必测、条件测试、裁剪”</h2><p class="intro">预置结论来自已命中的规则；“裁剪”必须留下不测依据、替代验证或基线证据，并由测试经理确认。</p>
  <div class="scenario-list">${scopes.map(x=>`<div class="scenario"><div><b>${x.title}</b><small>${x.detail}${x.when?`；规则：${x.when}`:''}</small></div><select class="status-select ${x.status==='必测'?'required':x.status==='条件测试'?'conditional':''}" data-scope="${x.id}">${options(['必测','条件测试','裁剪'],x.status)}</select></div>`).join('')}</div>
  <div class="form-section"><div class="hint-box">当前版本只演示裁剪框架；功能团队可在后续版本补充每类场景的详细案例、覆盖口径和裁剪条件。</div></div>`; }
function renderTools() { const list = tools(); return `
  <div class="eyebrow">步骤 04 · 工具组合</div><h2>按已见能力集选择辅助测试方式</h2><p class="intro">工具是辅助测试的手段。是否采用、在哪个阶段采用、采用范围和结果采纳方式均由测试经理裁定；实际操作由项目测试团队中具备能力的人员完成。</p>
  ${list.map(t=>`<div class="tool-card"><div class="tool-top"><b>${t.name}</b><span class="badge ${t.level==='必用'?'must':'conditional'}">${t.level}</span></div><p>${t.reason}</p><div class="tool-meta"><span><b>介入时机：</b>${t.phase}</span><span><b>使用前提：</b>${t.precondition}</span><span><b>输入：</b>${t.input}</span><span><b>输出：</b>${t.output}</span></div></div>`).join('')}
  <div class="decision-note"><b>能力缺口处理：</b>仅在现有工具无法覆盖、人工验证的风险/成本/周期不可接受时，提交新增工具需求；技术工具支撑团队评估可行性、接入条件、交付周期和替代方案，测试经理据此裁定。</div>`; }
function renderNonFunctional() { const list = nonfunctional(); return `
  <div class="eyebrow">步骤 05 · 非功能裁剪</div><h2>识别需要专项验证的非功能风险</h2><p class="intro">本页给出裁剪方向，不替代性能、安全、体验等专业领域的测试标准及具体阈值。</p>
  <div class="scenario-list">${list.map(([title,detail,status],i)=>`<div class="scenario"><div><b>${title}</b><small>${detail}</small></div><select class="status-select ${status==='必测'?'required':'conditional'}" data-nf="${i}">${options(['必测','条件测试','裁剪'],status)}</select></div>`).join('')}</div>
  <div class="form-section"><div class="hint-box">建议由非功能测试团队补充：性能基线、容量目标、安全要求、兼容环境及专项报告模板；测试经理将专项结论纳入整体准出判断。</div></div>`; }
function gateHTML(group, title, cls) { return `<div class="gate-group"><h3>${title}</h3>${group.map(x=>`<label class="gate-item"><input type="checkbox" data-gate="${x.id}" ${state.gates[x.id]===false?'':'checked'} /><span>${x.text}<small>${x.note}</small></span></label>`).join('')}</div>`; }
function renderGates() { const g=gates(); return `
  <div class="eyebrow">步骤 06 · 门禁与输出</div><h2>检查准出条件，生成执行细则</h2><p class="intro">硬性卡点不满足则流程阻断；软性卡点触发后需人工确认；质量红线触碰后需立即整改。指标阈值由领域细则和项目基线补充。</p>
  ${gateHTML(g.hard,'硬性卡点 · 必须满足','hard')}${gateHTML(g.soft,'软性卡点 · 触发需确认','soft')}${gateHTML(g.red,'质量红线 · 触碰即整改','red')}
  <div class="decision-note"><b>输出工件：</b>需求分析卡、范围裁剪清单、工具使用裁定记录、执行报告/差异明细、门禁检查单、风险或例外处置记录。</div>`; }

function bindCurrentStep() {
  if (state.step===0) {
    document.getElementById('nameInput').oninput=e=>{state.name=e.target.value;renderPreview();};
    document.getElementById('durationInput').onchange=e=>{state.duration=e.target.value;renderPreview();};
    document.querySelectorAll('[data-choice]').forEach(w=>w.onclick=e=>{const b=e.target.closest('button');if(!b)return;state[w.dataset.choice]=b.dataset.value;renderStep();renderPreview();});
    document.querySelectorAll('[data-flag]').forEach(x=>x.onchange=e=>{state.flags[e.target.dataset.flag]=e.target.checked;renderStep();renderPreview();});
  }
  if (state.step===1) document.querySelectorAll('[data-change]').forEach(x=>x.onchange=e=>{e.target.checked?state.changes.add(e.target.dataset.change):state.changes.delete(e.target.dataset.change);renderStep();renderPreview();});
  if (state.step===2) document.querySelectorAll('[data-scope]').forEach(x=>x.onchange=e=>{state.scope[e.target.dataset.scope]=e.target.value; e.target.className=`status-select ${e.target.value==='必测'?'required':e.target.value==='条件测试'?'conditional':''}`;renderPreview();});
  if (state.step===5) document.querySelectorAll('[data-gate]').forEach(x=>x.onchange=e=>{state.gates[e.target.dataset.gate]=e.target.checked;renderPreview();});
}
function renderPreview() {
  const score=riskScore(), g=gates(), chosenScopes=getScopes(), list=tools();
  document.getElementById('previewTitle').textContent=state.name || '未命名信创需求';
  document.getElementById('riskTags').innerHTML=[tag(state.importance, state.importance==='核心系统'?'high':''), ...selectedChanges().map(x=>tag(changeMeta[x].name,'medium')), state.flags.multi?tag('端到端链路','high'):''].join('');
  document.getElementById('depthText').textContent=depth();document.getElementById('scoreText').textContent=`风险评分 ${score} / 100`;document.getElementById('scoreBar').style.width=`${score}%`;
  document.getElementById('scopePreview').innerHTML=chosenScopes.filter(x=>x.status!=='裁剪').slice(0,6).map(x=>`<li>${x.title}<small> · ${x.status}</small></li>`).join('') || '<li>待选择改造特征</li>';
  document.getElementById('toolPreview').innerHTML=list.map(x=>`<div class="compact-row"><span>${x.name}</span><small>${x.level} · ${x.phase}</small></div>`).join('');
  const enabled=arr=>arr.filter(x=>state.gates[x.id]!==false);document.getElementById('hardCount').textContent=enabled(g.hard).length;document.getElementById('softCount').textContent=enabled(g.soft).length;document.getElementById('redCount').textContent=enabled(g.red).length;
  document.getElementById('gatePreview').innerHTML=enabled(g.hard).slice(0,3).map(x=>`<li>${x.text}</li>`).join('');document.getElementById('ruleTrace').textContent=rules().join(' · ');
}
function outputData() { const g=gates(), list=tools(), scopes=getScopes(), nf=nonfunctional(); return {g,list,scopes,nf}; }
function makeOutputHTML() { const {g,list,scopes,nf}=outputData(); const active=a=>a.filter(x=>state.gates[x.id]!==false); return `
  <section class="output-section"><h3>一、需求画像与裁剪结论</h3><div class="output-grid"><div class="output-cell"><strong>风险画像</strong><span>${state.importance} · ${depth()} · 风险评分 ${riskScore()}</span></div><div class="output-cell"><strong>改造范围</strong><span>${selectedChanges().map(id=>changeMeta[id].name).join('、') || '待确认'}</span></div><div class="output-cell"><strong>功能测试</strong><span>${scopes.filter(x=>x.status==='必测').map(x=>x.title).join('、') || '待裁定'}</span></div><div class="output-cell"><strong>非功能方向</strong><span>${nf.filter(x=>x[2]!=='裁剪').map(x=>x[0]).join('、')}</span></div></div></section>
  <section class="output-section"><h3>二、工具使用裁定建议</h3><ul>${list.map(x=>`<li><b>${x.name}（${x.level}）</b>：${x.phase}介入。前置：${x.precondition}。输入：${x.input}。输出：${x.output}。</li>`).join('')}</ul></section>
  <section class="output-section"><h3>三、分阶段执行与最小工件</h3><ul><li><b>承接/分析：</b>需求分析卡、核心链路清单、范围裁剪清单、工具使用裁定记录。</li><li><b>执行：</b>按已裁定范围执行；保留版本、环境、数据/流水、脚本/规则/探针版本、结果和证据链接；失败项分类为缺陷、补测、风险或例外。</li><li><b>检查/准出：</b>汇总工具报告、业务执行证据、专项结论与未覆盖项；由测试经理组织交叉核验后给出测试结论。</li><li><b>后督/沉淀：</b>沉淀复用脚本、规则、样例、适用边界与维护责任；生产事件按要求转化为回归案例。</li></ul></section>
  <section class="output-section"><h3>四、质量门禁</h3><ul>${active(g.hard).map(x=>`<li><b>硬性卡点：</b>${x.text}（${x.note}）</li>`).join('')}${active(g.soft).map(x=>`<li><b>软性卡点：</b>${x.text}（${x.note}）</li>`).join('')}${active(g.red).map(x=>`<li><b>质量红线：</b>${x.text}（${x.note}）</li>`).join('')}</ul></section>`; }
function markdownOutput() { const {g,list,scopes,nf}=outputData(), enabled=a=>a.filter(x=>state.gates[x.id]!==false); return `# ${state.name || '信创需求'} 测试执行细则\n\n## 需求画像\n- 系统等级：${state.importance}\n- 建议深度：${depth()}（风险评分 ${riskScore()}）\n- 改造范围：${selectedChanges().map(id=>changeMeta[id].name).join('、')}\n\n## 测试范围\n${scopes.map(x=>`- [${x.status}] ${x.title}：${x.detail}`).join('\n')}\n\n## 非功能方向\n${nf.map(x=>`- [${x[2]}] ${x[0]}：${x[1]}`).join('\n')}\n\n## 工具组合\n${list.map(x=>`- ${x.name}（${x.level}）：${x.phase}介入；前置：${x.precondition}；输入：${x.input}；输出：${x.output}`).join('\n')}\n\n## 门禁\n${[...enabled(g.hard).map(x=>`- 硬性：${x.text}`),...enabled(g.soft).map(x=>`- 软性：${x.text}`),...enabled(g.red).map(x=>`- 红线：${x.text}`)].join('\n')}\n\n> 说明：工具采用范围、执行人及结果采纳方式均须由测试经理裁定；项目测试团队内具备能力的人员执行工具，技术工具支撑团队提供培训、指导、排障和新场景评估。`; }
function showOutput() { document.getElementById('outputTitle').textContent=`《${state.name || '未命名信创需求'}测试执行细则》`;document.getElementById('outputBody').innerHTML=makeOutputHTML();document.getElementById('outputDialog').showModal(); }
function toast(text) { const t=document.getElementById('toast');t.textContent=text;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),1800); }
function saveDraft() { localStorage.setItem('xinchuang-demo-state',JSON.stringify({...state,changes:[...state.changes]}));toast('当前策略草稿已保存在此浏览器'); }
function restoreDraft() { try { const x=JSON.parse(localStorage.getItem('xinchuang-demo-state'));if(x){Object.assign(state,x);state.changes=new Set(x.changes||[]);toast('已恢复本地草稿');} } catch {} }

document.querySelectorAll('.step').forEach(b=>b.onclick=()=>{state.step=Number(b.dataset.step);renderStep();});
document.getElementById('prevBtn').onclick=()=>{if(state.step){state.step--;renderStep();}};
document.getElementById('nextBtn').onclick=()=>{if(state.step===5)showOutput();else{state.step++;renderStep();}};
document.getElementById('saveBtn').onclick=saveDraft;
document.getElementById('closeDialog').onclick=()=>document.getElementById('outputDialog').close();
document.getElementById('copyBtn').onclick=async()=>{try{await navigator.clipboard.writeText(markdownOutput());toast('已复制 Markdown 文本');}catch{toast('浏览器未允许写入剪贴板');}};
document.getElementById('downloadBtn').onclick=()=>{const blob=new Blob([markdownOutput()],{type:'text/markdown;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${(state.name||'信创需求').replace(/[\\/:*?"<>|]/g,'_')}_测试执行细则.md`;a.click();URL.revokeObjectURL(a.href);};
restoreDraft();renderStep();renderPreview();
