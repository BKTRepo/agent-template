# 单技能挂载知识库与 MCP

用户于本次开发明确授权修改 WRQ 和 zhaoyunlong 沙箱；不新增前端页面、按钮或调用证据展示。

## 执行链路

1. 保存技能时复用 SkillResourceBinding，source_type=knowledge_base，source_id 为知识库编号，usage_text 保存资源用途；不增加版本策略字段。
2. 构建清单保存知识库编号，SKILL.md 包含工具使用说明。知识库不再展开为原文件附件；直接上传的脚本、图片等仍作为资源打包。
3. 创建沙箱任务时，multipart 同时提交 skill_id、skill_version_id、build_id；服务端核验本人及当前构建，读取服务端保存的 Skill 定义。
4. WRQ 根据真实绑定生成本次任务范围，只含可见且处理完成的知识库。短期访问凭据只保存哈希，容器凭据通过运行环境传入，不写入 Skill 包或模型提示词。
5. 容器中的 Claude Agent SDK 注册 knowledge_search。模型自主调用，stdio MCP 桥接器将请求发到知识库后端。后端先限制 Milvus 文档范围再搜索，不使用全库回退。
6. SDK 根据 ToolUseBlock / ToolResultBlock 关联调用和结果；模型未调用或无有效命中时，允许两次补充。仍缺证据则失败。普通模型文本中的“已查询”不能通过核验。
7. 宿主服务核对返回的 search_id 确实属于当前 run_id，并关联工具调用编号及返回记录时间，之后才能完成任务。任务结束后撤销凭据。

MCP 使用标准 stdio 协议，由容器内 SDK 启动受控桥接进程。知识库业务后端提供 POST JSON 检索入口，复用同一个权限函数。该方式不要求业务 Web 应用维护 MCP HTTP 会话。

## 后端接口

- POST /skills/knowledge/search：仅使用本次运行的 Bearer 凭据；JSON 为 query、top_k，不接受客户端指定用户和知识库范围。
- GET /skills/developer/list-knowledge-tool-calls?run_id=...&limit=20&offset=0：平台身份认证，仅本人查询。返回查询、命中文档分块、耗时、错误类型、工具编号和交付记录时间；不返回运行 Token。

查询为空和查询失败区分记录；有挂载知识库的任务至少需要一次成功且有命中的查询。知识库被更新、删除或撤权时，本次上下文失效，不静默查询其他批次。

## 部署

在后端目录执行两表迁移（不改挂载表）：

```powershell
.\.venv\Scripts\python.exe -m applications.wrq.migrations.knowledge_mcp_schema --apply
```

从 applications/zhaoyunlong/sandbox 构建新镜像，例如：

```powershell
docker build -t test-case-sandbox:local applications/zhaoyunlong/sandbox
```

容器安装的 MCP 版本为 1.27.2。KNOWLEDGE_SEARCH_URL 由后端启动进程环境配置，默认 http://host.docker.internal:8519/skills/knowledge/search，Linux 部署应配置容器实际可访问的后端地址。

Milvus 与嵌入模型沿用已迁移知识库的配置。需完成真实 Docker、模型和 Milvus 的联调后，才能宣布端到端验收通过。隔离测试和 MCP 协议测试不等于该项验收。
