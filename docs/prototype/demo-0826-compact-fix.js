// 0826 裁剪器紧凑排版与提示文案调整。
const d82CompactStyle = document.createElement('style');
d82CompactStyle.textContent = `
  body.design-page{font-size:13px}
  .design-page .app-shell{max-width:1440px;padding:16px 20px}
  .design-page .topbar{gap:16px;margin-bottom:12px;align-items:flex-start}
  .design-page .topbar h1{font-size:24px;margin:0 0 2px}
  .design-page .topbar p{font-size:12px;line-height:1.4}
  .design-page .workspace{grid-template-columns:220px minmax(0,1fr)!important;gap:12px}
  .design-page .stepbar{padding:11px 8px}
  .design-page .stepbar-title{padding:0 8px 7px}
  .design-page .step{padding:7px 8px;gap:8px}
  .design-page .step small{font-size:10px}
  .design-page .role-note{margin:10px 4px 1px;padding:8px;font-size:10px}
  .design-page .editor{min-height:620px;padding:18px}
  .design-page .editor h2{font-size:19px;margin:2px 0 4px}
  .design-page .intro{font-size:12px;margin-bottom:12px;line-height:1.45}
  .design-page .analysis-grid{gap:8px;margin-top:8px}
  .design-page .design-section{margin-top:10px;padding:10px;border-radius:11px}
  .design-page .design-section h3{font-size:14px;margin-bottom:5px}
  .design-page .design-section>p{font-size:11px;line-height:1.4}
  .design-page .field-inline{gap:7px}
  .design-page .field-inline label{min-width:150px;font-size:11px}
  .design-page .field-inline input,.design-page .field-inline select{padding:6px 8px}
  .design-page .d82-change-type-grid{gap:7px;margin-top:8px}
  .design-page .d82-change-type{padding:8px;gap:7px}
  .design-page .d82-change-type small{font-size:10px;line-height:1.35}
  .design-page .design-table{font-size:11px;margin-top:6px;border-spacing:0 4px}
  .design-page .design-table th{padding:0 5px;font-size:11px}
  .design-page .design-table td{padding:5px}
  .design-page .design-table input,.design-page .design-table select,.design-page .design-table textarea{padding:6px;min-width:84px;font-size:11px}
  .design-page .design-table textarea{min-height:42px}
  .design-page .system-table th:nth-child(1){min-width:132px}
  .design-page .system-table th:nth-child(2){min-width:126px}
  .design-page .system-table th:nth-child(3){min-width:112px}
  .design-page .matrix-table th:nth-child(1){min-width:122px}
  .design-page .matrix-table th:nth-child(2){min-width:205px}
  .design-page .matrix-table th:nth-child(3){min-width:220px}
  .design-page .matrix-table th:nth-child(4){min-width:94px}
  .design-page .matrix-table th:nth-child(5){min-width:150px}
  .design-page .design-note{margin:8px 0;padding:8px 10px;font-size:11px;line-height:1.45}
  .design-page .nf-admission-text ol{margin:6px 0 0;padding-left:20px;font-size:11px;line-height:1.45}
  .design-page .nav-actions{padding-top:12px}
  .design-page .output-section{margin-top:12px}
  .design-page .output-section h3{font-size:14px}
  .design-page .output-section h4{font-size:13px;margin:8px 0 4px}
  .design-page .output-grid{gap:7px}
  .design-page .output-cell{padding:8px}
  @media(max-width:840px){.design-page .workspace{grid-template-columns:1fr!important}.design-page .app-shell{padding:12px}.design-page .editor{padding:14px}}
`;
document.head.appendChild(d82CompactStyle);

const d82CompactNfBase = d82RenderNonfunctional;
d82RenderNonfunctional = function(){
  return d82CompactNfBase().replace('以下为准入要求，采用文字确认，不设置勾选项：','');
};

const d82TopbarDesc = document.querySelector('.topbar p');
if(d82TopbarDesc) d82TopbarDesc.textContent = '策略裁剪依据：《信创项目测试指引》0826版；按六步完成裁剪、工具选择、门禁与协作确认。';

d82RenderStep();
