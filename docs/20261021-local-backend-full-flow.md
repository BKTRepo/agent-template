# 本地后端与同事调试接口全流程联调

## 当前服务

| 服务 | 地址 | 用途 |
| --- | --- | --- |
| React 前端 | http://localhost:5175/ | 新建技能、上传文件、调试和下载 |
| 本项目后端 | http://127.0.0.1:8520 | 真实认证、Skill 记录、表单生成、定义编辑、ZIP |
| 同事调试服务 | http://172.20.10.2:8519 | 真实运行调试和 Excel 文档下载 |

本项目后端从当前 `znfwdd` 工作目录启动已有 `examples.platform_backend_server`。它复用本项目业务实现，使用 `output/platform-integration` 中已有的 SQLite、构建和上传目录；本次没有配置团队 MySQL，也没有修改后端业务源码。知识库向量模型未配置，本次测试使用实际需求文件，不依赖向量化。

本地联调身份是已有的 `skill-dev`。前端不增加独立登录页面，本机代理携带该身份的真实 token。两个服务各用自己的 token，均只写入忽略提交的 `.env.local`，不进入浏览器构建产物。此代理身份用于本机联调；正式平台仍应使用真实登录会话。

## 启动与恢复

后端：在 `agent-template` 中执行 `.venv/Scripts/python.exe -m examples.platform_backend_server`，端口8520。健康检查为 `/health`。

前端：在前端目录执行 `node output/start-preview.py`，当前使用5175。若5175已有服务，不要再次启动以免换端口。

本次启动辅助程序为 `output/start-local-backend.py`，使用隐藏窗口并保留运行日志。需要更新本地测试 token 时，先确认后端正常，再执行 `node output/configure-local-backend.mjs`；这会保留同事接口的 token 和地址配置，并更新本地 Skill 代理配置。

## 请求与字段

1. `POST /skills/` 创建真实记录。
2. `POST /skills/form/builds` 提交 `source` 和实际 `files`。补齐 `skill_class_id`、`application`、与文件顺序一致的 `resource_categories`；编辑时传服务器旧版本作为 `expected_version`。
3. 以服务端返回的 `version` 和 `build_id` 更新页面，不用本地预估版本覆盖。
4. `GET /skills/{id}/definition` 读取服务端实际 Markdown。调试提交的是这份定义。
5. `POST /realtime-test-case-gen/generate` 提交定义、对话、需求文档和挂载原文件。
6. 用返回的 `run_id` 调用 `GET /realtime-test-case-gen/runs/{run_id}/document`，下载真实 Excel。

真实模式遇到无会话、示例知识库或接口错误时明确报错，不悄悄切换到模拟 Skill 生成。当前知识库选择器仍使用示例目录；本轮测试请取消示例挂载，使用资源上传或调试文档输入。知识库管理页面未在本轮接入真实接口。

直接上传的资源在浏览器保留原文件，供跨服务调试和刷新后恢复。生成前会恢复并核对文件清单，避免旧资源元信息存在而原文件未提交。服务器的 `PUT /skills/{id}/definition` 已用于真实 Skill 定义保存，保存后重新读取服务器版本和 Markdown。

## 实际测试证据

通过 React 页面新建“登录权限全流程联调9905002”，使用真实本地后端生成：

- Skill ID：`1792549906-DDC1D0FFA3EF4A71A9078342D32D02D6`
- Build ID：`ff14aeab366842d79da03c74572e96ae`
- 服务端版本：`1.0.0`
- 需求文件：`模拟需求文档_登录与权限管理.md`，6790字节。
- 真实调试运行编号：`a2c0f7ee4a2f4e30a164f7376b04a5da`
- 结果：`调试结果文档.xlsx`，7928字节，3条用例。

检查 XLSX 压缩包与工作表有效，工作表“功能测试用例”共4行，含表头和3条记录。结果文件、截图与响应证据保存在忽略提交的 `output/` 中。

另用真实附件验证本地生成、分类、定义保存至1.0.1、刷新查询及完整 ZIP 下载。向调试接口提交最新定义与挂载原文件的检查使用受控响应，避免重复调用远端模型。首次附加检查曾遇到后端 Windows 目录重命名拒绝访问；后续两次定义保存通过，错误日志在后端 `output/platform-integration/logs/20261021-ERROR-执行日志.log`，本轮没有改动其目录实现。

当前服务用于新建至调试下载的联调。草稿和页面列表仍沿用浏览器存储；正式上线/下线及服务器列表同步不属于这次接口接入。
