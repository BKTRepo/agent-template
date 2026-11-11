# 悬浮对话、产出物、资产和总览接入（2026-11-11）

所有接口使用平台登录 token；GET 参数在查询字符串，POST 参数在 JSON 或 form-data 请求体。

## 部署前迁移

`python -m applications.wrq.migrations.assistant_integration` 仅输出增量 SQL 计划；审核目标连接后，通过 `--apply` 显式执行。服务启动不自动执行本迁移。

新增 `keenrobot_overview_events`，仅记录原来没有持久事实源的登录、智能对话请求、新增知识库挂载。`event_key` 唯一，挂载随技能保存事务提交，仅新关联计数，复制版本不重复计数。

为 `chat_skill_calls` 增加调用人工号、技能名称快照；为 `chat_artifact_counts` 增加真实生成时间及明细 JSON；为 `keenrobot_online_debug_runs` 增加实际任务发起人 `owner_id`。复用原有调用和产物计数表，不增加 `chat_artifacts` 字段。

远端迁移需要单独授权，本次联调只在隔离测试库执行。

## 真实产出物

`/chat/task`、`/chat/events` 和 `/chat/message/list` 的回复包含 `artifacts`：`artifact_id`（字符串）、`file_name`、`artifact_type`。复用 `ChatArtifact` 与其所属任务/会话，只有本人当前有效会话的成功任务原件可预览、编辑和归档。清空会话使原件失效；已归档文件是独立副本。

复用 `/assistant/artifacts/detail`、`/sheet`、`/save-content`、`/download`，真实编号直接进入相同编辑链路。样例只在显式配置 mock 目录及前端开关后可用。

测试案例复用工作簿编辑器：支持原双工作表格式，也支持常见单表格式（案例/用例编号、案例名称、前置条件、操作步骤、预期结果）。保持额外工作表、列和格式。案例生成落盘后调用现有模型客户端归纳测试要点并分类；分组按文件哈希缓存，不改案例正文。节点显示案例名称，支持编辑字段、删除案例和删减步骤；保存按原格式原子覆盖 Excel，并刷新对应产物数量及派生导图。模型失败明确返回 `grouping_error`，保留文件，重新打开可重试。

## 助手上下文和任务

发送接口支持 `context={module, object_type?, object_id?}`，由服务器验证业务对象权限并读取数据，随原请求存入会话 JSONL 的 `request_snapshot`。客户端不能提交可信业务对象正文。模型读取发起时快照；页面切换不会覆盖它。`source_task_id` 用于修改原请求后重发；历史请求缺少快照时明确拒绝冒充原上下文。

资源选择复用技能目录 `online_only=true` 和知识库列表 `ready_only=true`，服务端过滤后分页，每页最多10条。应用展示名称，筛选传 identify；技能类来自真实目录。知识库权限及转换完成状态在服务端检查。

`GET /chat/tasks` 返回本人有效会话的近期任务状态和结果。不同会话可并行，同一会话仍只允许一个活动任务。重试创建新任务并保留原回复，替换附件继续使用 `/chat/retry-with-files`。历史消息返回任务、反馈、原因及请求快照。反馈复用 `/chat/feedback` 的 `reason`。

## 调试权限

查询和下载统一校验实际任务发起人，管理员沿用原下载管理权限。历史任务使用可信元数据或精确任务登记关系确认归属，不依据显示姓名猜测。

- `GET /realtime-test-case-gen/runs/get?run_id=...`
- `GET /realtime-test-case-gen/skills/latest-run?skill_id=...`
- `GET /realtime-test-case-gen/runs/document?run_id=...&filename=...`

最近任务接口对普通用户只返回本人任务；技能中心在线测试同样记录实际发起人。登记调试结果也校验任务权限。

## 资产和总览口径

资产 `content_quantity` 从当前归档文件读取：测试案例按案例条数；技能大类3的 Excel 按每个工作表去掉首行表头后的非空行数求和；其他文件按份。`POST /api/assets/export` 返回 ZIP 原文件，不再导出 CSV 清单；先验证全部资产权限，保留格式和文件字节，响应完成清理临时 ZIP。

总览八项指标、趋势、Top5 和明细复用事实源。累计指标不受日期筛选影响；期间按 Asia/Shanghai 的开始日00:00（含）到结束日次日00:00（不含）。趋势按日/双日/周展示。Skill 累计调用及最近调用时间来自真实模型工具调用事件，与技能中心在线测试计数分开。AI 产出只计成功最终文件及其真实内容数量；Top5 产出关联同一任务实际调用技能，用于并列排序。

登录、挂载缺失的历史明细不估算；旧产物缺生成时间/来源时不混入期间。用户表缺部门，字段留空并显示说明。新事件和已有事实由唯一业务编号去重。用户接入累计以已登录记录为准，无法确认的历史首次时间、累计登录次数留空。F06、A01、A04 的既有行为本次保持原样。
