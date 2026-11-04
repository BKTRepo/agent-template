# WRQ 接口开发规范与当前清单

适用范围：`applications/wrq`；2026-11-03 按用户要求统一。此次只调整接口契约，复用原有权限、修订号冲突、发布状态及文件处理业务。

1. 只使用 GET / POST。查询、下载使用 GET；创建、修改、删除、上下线、构建使用 POST。
2. 路径不含动态占位符。GET 参数放在 URL 末尾查询字符串中，例如 `?file_id=1`，多个参数使用 `&`。
3. POST 所有业务参数（包括技能编号）放在 JSON 请求体中；上传文件的编号、source、分类和文件统一放 multipart 请求体中。
4. 英文路径说明资源及动作，中文 summary 包含可搜索的业务关键词。
5. 所有接口继续要求平台身份认证；认证信息在请求头中，不是业务查询参数。
6. 技能编号 `skill_id` 为有符号 INT(11)，有效业务编号为 1～2147483647；JSON 使用数字，例如 `{"skill_id":1}`。GET 查询字符串和 multipart 中传 `1`，后端转换并校验。技能主键由数据库自增生成。

## 开发者中心

下列路径均以 `/skills/developer` 开头。

| 方法 | 路径后缀 | 功能与参数 |
|---|---|---|
| GET | /get-current-user | 当前登录身份 |
| GET | /get-form-metadata | 技能类、应用、资源用途字典 |
| GET | /list-skills | 本人技能分页；page、page_size 为查询参数 |
| POST | /create-skill-draft | JSON：原 DeveloperSkillForm |
| POST | /save-skill | JSON：skill_id + 原表单，包括 expected_revision |
| POST | /delete-skill-draft | JSON：skill_id；仍仅软删除草稿 |
| POST | /offline-skill | JSON：skill_id、reason_code、reason_text |
| POST | /publish-skill | JSON：skill_id；仍由服务端核验调试结果 |
| POST | /register-debug-run | JSON：skill_id、run_id、build_id/skill_version_id 及原登记字段 |
| GET | /get-debug-run | 查询参数：skill_id、run_id |
| POST | /upload-resource-files | multipart：files、categories（JSON 数组字符串） |
| GET | /download-resource-file | 查询参数：file_id |
| POST | /upload-resource-version | 已停用旧功能，仅保留明确的停用提示；multipart：source_id、files、categories |

示例：

```http
GET /skills/developer/download-resource-file?file_id=123
GET /skills/developer/get-debug-run?skill_id=skill-001&run_id=run-001
POST /skills/developer/offline-skill
Content-Type: application/json

{"skill_id":"skill-001","reason_code":"OTHER","reason_text":"维护升级"}
```

## Skill 包

下列路径均以 `/skills/packages` 开头。

| 方法 | 路径后缀 | 功能与参数 |
|---|---|---|
| POST | /build-from-form | multipart：source（SkillDeveloperForm JSON，包含 skill_id）、files |
| GET | /get-definition | 查询参数：skill_id |
| POST | /save-definition | JSON：skill_id、markdown、expected_version |
| POST | /validate | JSON：skill_id + 原 SkillPackageSource 字段 |
| POST | /build-from-documents | JSON：skill_id + 原 SkillPackageSource 字段 |
| POST | /build-from-uploads | multipart：skill_id、source（原 SkillPackageSource JSON）、files |
| POST | /build-from-entries | multipart：skill_id、source、reference_files、script_files |
| GET | /get-build | 查询参数：skill_id、build_id |
| GET | /list-builds | 查询参数：skill_id、limit、offset |
| GET | /download-build | 查询参数：skill_id、build_id；返回 ZIP |

## 通用技能管理

下列路径均以 `/skills` 开头。

| 方法 | 路径后缀 | 功能与参数 |
|---|---|---|
| GET | /check-skill-name | 查询参数：name、exclude_id |
| GET | /list-skills | 查询参数：search、manage |
| GET | /get-skill | 查询参数：skill_id |
| POST | /create-skill | 原入口仍提示改用开发者中心完整表单，不新增不完整技能 |
| POST | /update-skill | JSON：skill_id + SkillUpdate；仍提示使用完整表单 |
| POST | /delete-skill | JSON：skill_id；复用原草稿删除业务 |

## MCP 服务配置管理

以下是配置 CRUD，不是 MCP 协议工具调用入口。路径以 `/mcp-servers` 开头。

| 方法 | 路径后缀 | 功能与参数 |
|---|---|---|
| GET | /list-mcp-servers | 查询参数：search、manage |
| GET | /get-mcp-server | 查询参数：mcp_id |
| POST | /create-mcp-server | JSON：原 McpServerCreate |
| POST | /update-mcp-server | JSON：mcp_id + 原修改字段，未填写字段保持原值 |
| POST | /delete-mcp-server | JSON：mcp_id；复用原软删除业务 |

## 迁移说明

- 原带 `{skill_id}`、`{file_id}`、`{build_id}` 的 WRQ 路由及 PUT / DELETE 路由已替换，不保留旧方法别名。调用方应同步更新。
- 后端生成的 downloadUrl 已变更；当前前端会把缓存中的旧资源下载地址转换为新查询参数地址。
- 前后端应同步部署；历史文档和旧验收脚本不能代替本文件的当前契约。
- 同事的 `/realtime-test-case-gen` 沙箱接口及其他模块不在本次变更范围内。

## 检查命令

在保留本地验收脚本的开发目录中执行（测试文件不随本次业务代码发布）：

```powershell
.\.venv\Scripts\python.exe -m pytest applications/wrq/tests/test_api_conventions.py -q
```
