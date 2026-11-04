---
title: 技能中心前端接入
status: 技能字段已迁移，计数与整数编号已接入
last_updated: 2026-11-04
---

# 技能中心

`SkillsPage.tsx` 不再读取开发者中心当前页缓存或前端示例类定义，独立调用 `/skills/catalog` 查询已发布目录，保留原型的分类展开、名称/分类/应用/维护人筛选、详情、在线测试和下载。提供真实分页、刷新、加载、空结果和错误重试；切换平台身份清理显示数据。

具体实现仍来自开发者中心原有表。类描述、input_schema、output_schema、template 直接加入后端 `keenrobot_skill_classes`，目标库已按用户授权通过SSL完成这四列及统计列迁移。未配置时展示“未配置”，不生成伪Schema或模板。

目录以 published_version_id 对应表单呈现；个人草稿和调试中记录不可见。已下线仍可详情和下载；只有已上线且大类启用才能测试。下载走固定发布构建，不使用示例ZIP。

实现类call_count/download_count读取服务端累计值，初始0；列表显示调用数，详情显示两项统计，下载后/关闭测试后刷新。调用统计当前涵盖技能中心实际接受的测试任务，开发者私人调试和未来正式执行入口尚未纳入。维护人显示服务端工号；应用名称由门户字典映射。

以下查询均GET，参数用URLSearchParams编码，token沿用平台请求头：

- `/skills/catalog/get-metadata`
- `/skills/catalog/get-class?class_id=...`
- `/skills/catalog/list-skills?name=...&class_id=...&application=...&maintainer=...&page=1&page_size=20`
- `/skills/catalog/get-skill?skill_id=...`
- `/skills/catalog/get-build?skill_id=...&build_id=...`
- `/skills/catalog/download-skill?skill_id=...&build_id=...`
- `/skills/catalog/download-resource?skill_id=...&build_id=...&path=...`

在线测试复用既有DebugDialog和同事沙箱。打开/提交前核对发布状态和构建；通过POST /skills/catalog/create-test-run提交source JSON与需求documents；source包含整数skill_id、build_id、32位request_id和conversation_input，发布定义与资源由后端固定ZIP快照读取。响应丢失重试复用原request_id，成功后的新调用使用新编号。目录测试不会调用开发者的保存、调试登记或上线接口；不改变实现版本或状态。沙箱只接收普通文件名，若不同目录存在同名原件会明确阻止，要求维护人调整，不静默覆盖；最多20个挂载文件。目录不将无法确认构建的latest-run自动挂到当前发布版。

开启真实沙箱仍需既有 `VITE_REALTIME_DEBUG_ENABLED=true` 和代理配置；未配置时显示错误，不使用模拟成功。目标技能列已迁移，知识库七表也按用户后续授权从空表迁为INT自增主键，关联列同步为INT，代码与库一致；job_id仍为字符串业务任务号。真实模型和Docker执行仍需目标环境联调。创建知识库先convert再create，只关联文档；技能挂载仍单独调用技能保存接口。

验证：`npm test` 55项通过，`npm run build`通过。浏览器使用明确测试接口验证展开/收起、过滤/重置、发布详情、类Schema与缺省值、模板和ZIP下载、下线禁用及在线测试失败显示，页面错误0。后端另有真实SQLite/HTTP与ZIP定向测试。
