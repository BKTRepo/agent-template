// 最终输出完整版：把六步中收集的内容完整沉淀为可交付工件。
function d82List(items){return `<ul>${items.map(x=>`<li>${x}</li>`).join('')}</ul>`}
function d82OutputDemand(){
  const selectedTypes=d82FiveChangeTypes.map(x=>`<span class="history-badge">${d82Esc(x[1])}：${state.changes.has(x[0])?'已选择':'未选择'}</span>`).join('');
  const systems=state.systems.map(x=>`<tr><td>${d82Esc(x.name)}</td><td>${d82Esc(x.automation)}</td><td>${d82Esc(x.ui)}</td><td>${d82Esc(x.testDept||'待确认')}</td><td>${d82Esc(x.owner||'待确认')}</td></tr>`).join('');
  const prereqs=d82DefaultPrereqs.map(x=>`<li>${state.prereqs[x[0]]?'已确认':'未确认'}：${d82Esc(x[1])}</li>`);
  const signalMap={probe:'精准测试工具',stableApi:'接口自动化测试',stableUi:'UI自动化测试',core:'核心业务主线',money:'账务 / 资金',multi:'跨系统 / 异步'};
  const signals=state.signalCatalog.map(x=>`<tr><td>${x.enabled?'启用':'停用'}</td><td>${d82Esc(x.title)}</td><td>${d82Esc(x.desc)}</td><td>${x.selected?'本次命中':'未命中'}</td><td>${d82Esc(signalMap[x.ruleKey]||'仅记录')}</td></tr>`).join('');
  return `<section class="output-section"><h3>一、需求分析工件</h3><div class="output-grid"><div class="output-cell"><strong>需求名称</strong><span>${d82Esc(state.name||'未命名信创需求')}</span></div><div class="output-cell"><strong>需求类型</strong><span>${d82Esc(state.category)}</span></div><div class="output-cell"><strong>测试周期</strong><span>${d82Esc(state.duration)}</span></div><div class="output-cell"><strong>系统重要性</strong><span>${d82Esc(state.importance)}</span></div></div><h4>改造类型 / 信创技术栈勾选</h4><p>${selectedTypes}</p><h4>涉及系统自动化水平与测试部承接情况</h4><table class="design-table"><thead><tr><th>系统</th><th>接口自动化</th><th>UI自动化</th><th>是否测试部测试</th><th>责任团队</th></tr></thead><tbody>${systems}</tbody></table><h4>前道环节提供物确认</h4>${d82List(prereqs)}<h4>业务与技术信号</h4><table class="design-table"><thead><tr><th>配置</th><th>信号</th><th>说明</th><th>本次命中</th><th>映射</th></tr></thead><tbody>${signals}</tbody></table></section>`;
}
function d82OutputFunctional(){
  const rows=d82ActiveChanges().filter(id=>d82FunctionalCatalog[id]).map(id=>{const x=d82FunctionalCatalog[id],d=d82ChangeDecision(id);return `<tr><td><b>${d82Esc(x.title)}</b></td><td>${d82Esc(x.content)}</td><td>${d82Esc(x.cut)}</td><td>${d82Esc(d.status)}</td><td>${d82Esc(d.reason||'无补充说明')}</td></tr>`}).join('');
  return `<section class="output-section"><h3>二、功能测试裁剪工件（参考 9.1）</h3><table class="design-table"><thead><tr><th>改造类型</th><th>测试要求</th><th>裁剪明细</th><th>裁剪结论</th><th>裁剪依据</th></tr></thead><tbody>${rows||'<tr><td colspan="5">未选择改造类型</td></tr>'}</tbody></table><h4>功能测试准入</h4>${d82List(['需求/设计评审通过，版本、环境、外部依赖可识别。','功能范围裁剪清单已确认，测试数据、账号、权限和核验规则已准备。','核心链路、历史事件、跨系统依赖和端到端范围已识别。'])}<h4>功能测试准出</h4>${d82List(['必测项均已执行并取得明确结果，裁剪项有依据或替代验证。','核心链路、关键数据、接口/落表和端到端证据完整。','缺陷、数据差异、阻塞和遗留风险已登记、复测或完成书面处置。'])}</section>`;
}
function d82OutputNf(){
  const rows=d82ActiveChanges().filter(id=>d82NfCatalog[id]).map(id=>{const x=d82NfCatalog[id],d=d82NfDecision(id);return `<tr><td><b>${d82Esc(x.title)}</b></td><td>${d82Esc(x.strategy)}</td><td>${d82Esc(x.cut)}</td><td>${d82Esc(d.status)}</td><td>${d82Esc(d.reason||'无补充说明')}</td></tr>`}).join('');
  return `<section class="output-section"><h3>三、非功能测试裁剪工件（参考 9.2）</h3><table class="design-table"><thead><tr><th>信创技术栈</th><th>测试要求 / 策略</th><th>裁剪明细</th><th>裁剪结论</th><th>裁剪依据</th></tr></thead><tbody>${rows||'<tr><td colspan="5">未命中专项，需保留不适用依据</td></tr>'}</tbody></table><h4>非功能测试准入</h4>${d82List(['系统架构稳定，功能冒烟通过，专项环境和连通性校验通过。','专项目标、性能/高可用指标、容量模型、基线、监控、脚本、数据和支持人员已准备。','需要时已同步生产铺底数据，并确认测试环境与生产配置差异。'])}<h4>非功能测试准出</h4>${d82List(['所有纳入场景完成；不适用场景有 NA 原因。','专项指标达标，或已完成分析调优、影响评估、责任人/期限和书面风险处置。','原始结果、专项报告、复测记录和遗留问题完整归档。'])}</section>`;
}
function d82OutputTools(){
  const rows=d82Tools.map(x=>{const d=d82ToolChoice(x.id);return `<tr><td><b>${d82Esc(x.name)}</b></td><td>${d82Esc(x.scene)}</td><td>${d82Esc(x.pre)}</td><td>${d82Esc(x.when)}</td><td>${d82Esc(x.input)}</td><td>${d82Esc(x.output)}</td><td>${d82Esc(d.decision)}</td></tr>`}).join('');
  return `<section class="output-section"><h3>四、工具选择与能力描述（参考 9.3）</h3><table class="design-table"><thead><tr><th>工具</th><th>能力 / 适合场景</th><th>使用前提</th><th>建议介入时机</th><th>输入</th><th>输出</th><th>是否采用</th></tr></thead><tbody>${rows}</tbody></table><h4>工具使用边界</h4>${d82List(['工具采用范围和结果采纳方式由测试经理裁定。','项目测试团队内具备能力的人员执行；技术测试支撑团队负责工具、培训、技能支持、排障和新场景评估。','工具结果必须结合版本、环境、数据、规则和业务/专项结论复核。'])}</section>`;
}
function d82OutputGates(){
  const main=d82HardGates.map(x=>`<tr><td><b>${d82Esc(x.name)}</b></td><td>${d82Esc(x.formula)}</td><td>${d82Esc(x.threshold)}</td><td class="gate-readonly">默认硬性门禁</td></tr>`).join('');
  const extra=(state.extraGates||[]).map(x=>`<tr><td>${d82Esc(x.name)}</td><td>${d82Esc(x.rule)}</td><td>${d82Esc(x.kind)}</td><td>${x.checked?'已确认':'未确认'}</td></tr>`).join('');
  return `<section class="output-section"><h3>五、全部质量门禁指标</h3><table class="design-table"><thead><tr><th>指标 / 条款</th><th>计算方式或判定方式</th><th>阈值 / 类型</th><th>状态</th></tr></thead><tbody>${main}${extra}</tbody></table><p class="muted">6项默认硬性门禁不需要勾选，直接纳入最终指引；额外硬性条款需完成确认。</p></section>`;
}
function d82OutputCollab(){
  const principles=['测试经理统一裁定测试范围、工具组合、门禁、例外与最终结论。','功能/非功能测试团队按裁定执行并对业务或专项结果负责。','技术测试支撑团队提供工具、培训、技能支持、排障和新场景评估，不代替项目执行。','研发、运维、数据及其他责任方前置提供版本、环境、权限、数据、监控和回退条件。'];
  return `<section class="output-section"><h3>六、干系人和协作总结</h3><h4>协作原则</h4>${d82List(principles.map(x=>d82Esc(x)))}<h4>干系人确认</h4><table class="design-table"><thead><tr><th>角色</th><th>姓名 / 团队</th><th>本需求承担事项</th></tr></thead><tbody>${state.stakeholders.map(x=>`<tr><td>${d82Esc(x.role)}</td><td>${d82Esc(x.name)}</td><td>${d82Esc(x.duty)}</td></tr>`).join('')}</tbody></table><p class="muted">协作确认状态：${state.collabConfirmed?'已确认':'未确认'}。</p></section>`;
}
d82MakeOutput = function(){ return `${d82OutputDemand()}${d82OutputFunctional()}${d82OutputNf()}${d82OutputTools()}${d82OutputGates()}${d82OutputCollab()}`; };
d82RenderStep();
