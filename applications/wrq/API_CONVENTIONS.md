# WRQ 接口开发规范与当前清单

## 悬浮对话台测试案例产出物联调

以下接口以 `/assistant/artifacts` 为前缀，均使用平台 token，按登录人定位样例文件。仅配置 `ASSISTANT_ARTIFACT_MOCK_DIR` 时启用，不涉及 `chat_artifact` 或资产数据库表。

| 方法 | 路径后缀 | 参数与行为 |
|---|---|---|
| POST | /create-demo | JSON 可选 `kind`，默认 `test_cases`，支持 `docx`、`xlsx`、`py`、`js`、`ts`、`sh`、`sql`、`md`、`json`。已存在时打开当前原件 |
| GET | /detail | 查询 `artifact_id`。返回 `is_test_case`、格式和 `base_hash`。测试案例返回案例与分组，普通文件返回 `editor` 及对应的 `blocks`、`sheets` 或 `text` |
| GET | /sheet | 查询 `artifact_id`、`base_hash`、`sheet_index`、行列偏移与上限，返回普通 XLSX 工作表的一页单元格 |
| POST | /save-content | JSON `artifact_id`、`base_hash`，另传 `cases`、`paragraphs`、`cells` 或 `text` 四者之一。锁内校验原文件哈希，冲突返回 409 |
| GET | /download | 查询 `artifact_id`、可选 `base_hash`、可选 `archived`。下载整份原格式文件或归档快照 |
| GET | /asset-status | 查询 `artifact_id`。返回样例是否已归档 |
| POST | /submit-to-assets | JSON `artifact_id`、`base_hash`、`name`、`application_identify`。重复提交返回已有样例归档 |

样例 XLSX 有「测试案例」「操作步骤」两张表，分别按案例编号和案例编号加步骤编号定位。写回前校验生成后的工作簿，在原文件所在目录用临时文件替换原件。已归档快照独立保存。正式接入时用同事的产出物查询替换 mock 元数据，用真实输出样本确定工作簿适配方式，再将样例归档替换为正式资产查询和创建接口。

导图按验证目标归纳，支持把不同场景的相似案例合入同一测试要点。归纳结果单独放在共享目录的 `.case-groups/<用户ID>/<产出物ID>.json`。其中记录 `schema_version`、`artifact_id`、`source_sha256`、`mode` 和 `groups`，文件哈希变化时重新生成。默认使用样例规则，设置 `ASSISTANT_ARTIFACT_MODEL_GROUPING=true` 后复用现有模型配置，验证模型覆盖全部原案例且每条只出现一次。模型失败时回退到样例规则。JSON 不写入 XLSX，也不参与导出或归档。

普通文件编辑使用同一原文件定位与保存事务。DOCX 按段落编号修改正文及表格内文本，复杂段落只读，保留其他文档部件。XLSX 按 `sheet_index` 和 `address` 修改单元格，支持文本、数字、布尔、普通公式和清空，保留原工作表样式与未修改部件，复杂公式和合并区域的从属格只读。文本支持 UTF-8、带 BOM 的 UTF-16 和 GB18030，保存保留编码、BOM 和原换行风格；JSON 写入前检查语法。样例原文件最大 10 MiB，文本最多 2 Mi 字符，Office 解压最多 64 MiB。


知识库附件预览：GET `/knowledge-bases/documents/preview?kb_id=1&doc_id=2` 返回格式与文档代次；GET `/knowledge-bases/documents/preview-pdf?kb_id=1&doc_id=2&generation=1` 返回原PDF/Word转换PDF；GET `/knowledge-bases/documents/preview-sheet?kb_id=1&doc_id=2&generation=1&sheet_index=0&offset=0&limit=100&column_offset=0&column_limit=50` 返回Excel分页。原下载接口增加可选generation。平台token均在请求头。详见 [附件预览](../../docs/document-preview.md)。

2026-11-06 知识库更新提醒新增：GET `/skills/developer/get-knowledge-update-summary`，GET `/skills/developer/get-knowledge-updates?skill_id=14`，POST `/skills/developer/mark-knowledge-updates-read`（JSON：`skill_id`、`items:[{notification_id,seen_revision}]`）。均验证平台身份及本人技能，列表增加批量查询的 `knowledge_update_count`；已读仅确认用户看到的版本，不修改技能修订号或发布状态。完整语义和显式迁移见 [知识库更新提醒](../../docs/knowledge-integration.md#知识库更新的持久化提醒)。

适用范围：`applications/wrq`；2026-11-03 按用户要求统一。此次只调整接口契约，复用原有权限、修订号冲突、发布状态及文件处理业务。

1. 只使用 GET / POST。查询、下载使用 GET；创建、修改、删除、上下线、构建使用 POST。
2. 路径不含动态占位符。GET 参数放在 URL 末尾查询字符串中，例如 `?file_id=1`，多个参数使用 `&`。
3. POST 所有业务参数（包括技能编号）放在 JSON 请求体中；上传文件的编号、source、分类和文件统一放 multipart 请求体中。
4. 英文路径说明资源及动作，中文 summary 包含可搜索的业务关键词。
5. 所有接口继续要求平台身份认证；认证信息在请求头中，不是业务查询参数。
6. 技能编号 `skill_id` 为有符号 INT(11)，有效业务编号为 1～2147483647；JSON 使用数字，例如 `{"skill_id":1}`。GET 查询字符串和 multipart 中传 `1`，后端转换并校验。技能主键由数据库自增生成。

## 开发者中心

下列路径均以 `/skills/developer` 开头。

列表条件同时成立：`name` 为实现名称模糊搜索，`class_id` 为技能类编号，`application` 为应用代码（具体应用包含全应用适用 `*`），`status` 为 `DRAFT`、`DEBUGGING`、`DEBUG_SUCCESS`、`DEBUG_FAILED`、`ONLINE` 或 `OFFLINE`。省略或清空条件表示不限；仅返回当前用户的有效技能，筛选后统计总数再分页，超出末页时保留全部条件回退到末页。状态筛选前同步当前构建的调试结果，避免已结束任务仍被归为调试中。前端状态选项在字典加载前也提供这六种状态。

| 方法 | 路径后缀 | 功能与参数 |
|---|---|---|
| GET | /get-current-user | 当前登录身份 |
| GET | /get-form-metadata | 技能类、应用、资源用途字典；filter_skill_classes 包含停用技能类供列表筛选，statuses 返回状态代码与名称 |
| GET | /list-skills | 本人技能分页；page、page_size、name、class_id、status、application 为查询参数 |
| GET | /get-skill | 按 skill_id 查询本人技能及当前知识库引用；只读、不递增修订或改变技能状态 |
| POST | /create-skill-draft | JSON：DeveloperSkillForm；新建必选所属应用（application_ids 选择一个有效 identify，或 application_paso），缺失/空白返回 application_paso 字段错误；已有历史技能不补写默认应用 |
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

## 应用目录及知识库标签配置（2026-11-05）

开发者中心、技能中心和知识库共用 applications/wrq/platform_catalog.py。
默认 APPLICATION_CATALOG_MODE=mock，数据位于 data/mock_applications.json，采用正式接口的 retCd/retMsg/data 格式。
前端显示 subApplicationName，保存 subApplicationIdentify；不会保存数字 subApplicationId 或显示名称。
切换 APPLICATION_CATALOG_MODE=remote 后，后端 POST APPLICATION_CATALOG_URL，JSON 请求体为 {}，
默认地址 http://10.240.105.84:9999/selfTest/queryAllApplication。retCd 必须为 000000；失败不会静默回退 mock。
APPLICATION_CATALOG_CACHE_SECONDS 默认 60 秒。原 WRQ_PORTAL_APPLICATIONS_URL/PLATFORM_APPLICATIONS 配置不再作为目录来源。

- GET /knowledge-bases/applications：具体应用目录；技能目录另保留 *（全应用适用）。
- GET /knowledge-bases/get-form-metadata：返回 applications 及已启用 tags。
- GET /knowledge-bases/tags?include_disabled=true：管理员可包含停用项；普通用户仅能读取启用项。
- POST /knowledge-bases/tags/save：管理员 JSON 请求体包含可选 id、code、name、is_enabled、sort_order。
  code 创建后固定，支持名称、排序和启用状态修改。未启用标签不能新选，已有知识库可保留原标签。
- 知识库保存 tag 为配置代码，详情附 tag_name；修改标签显示名称不改知识库里的稳定代码。
- 知识库列表和详情返回 can_retry 权限；失败项在列表及详情显示“重试”，无权限时置灰并提示仅创建者可重试。
  有转换任务的失败文档调用 POST /api/convert/retry，JSON 为 job_id；旧文档使用 POST /knowledge-bases/retry，JSON 为整数 kb_id。
  前端防止重复提交，重试后刷新进度；部分成功也刷新，下一次仅重试剩余失败项。重试不增加知识库版本。
- 新建 POST /knowledge-bases/create 的 source 中 description、tag、application 必须提供非空值，纯空白同样拒绝。
  tag 使用已启用标签代码，application 使用应用 identify。前端在上传转换任务前校验，后端创建模型和服务入口均校验。
- 编辑 POST /knowledge-bases/save 在事务内比较名称、描述、标签、应用、可见范围及最终文件名/内容哈希集合。
  无实际变更时保留版本、编辑历史、维护人和知识库更新时间；仅填写 change_summary 或调整保留文件顺序不产生新版本。
  同名同内容重传可修复原件存储，但不增加知识库版本或重建已完成索引；真实文件或元数据变更才递增一次。
- POST /api/convert 每次上传创建独立 job_id，文件名不做全局查重；不同知识库允许上传相同文件。
  任务的原文件、解析产物、向量及权限按任务/知识库隔离，同一知识库内部仍保留重复附件校验。
  旧库部署前显式执行 `python -m applications.knowledge_base.migrations.rag_filename_scope --apply`，
  仅移除 rag_document 的单列文件名唯一索引，保留 job_id 唯一索引和现有文档。默认不带 --apply 只展示计划。

新增 keenrobot_knowledge_tags，id 为 INT 自增。显式执行
`python -m applications.knowledge_base.migrations.knowledge_tag_schema --apply` 建表并添加 general/通识类、custom/自定义。
重复执行不会覆盖管理员修改；不改现有知识库、技能或资源分类表。默认不带 --apply 只展示计划。

## MCP 服务配置管理接口

以下是配置 CRUD，不是 MCP 协议工具调用入口。路径以 `/mcp-servers` 开头。

| 方法 | 路径后缀 | 功能与参数 |
|---|---|---|
| GET | /list-mcp-servers | 查询参数：search、manage |
| GET | /get-mcp-server | 查询参数：mcp_id |
| POST | /create-mcp-server | JSON：原 McpServerCreate |
| POST | /update-mcp-server | JSON：mcp_id + 原修改字段，未填写字段保持原值 |
| POST | /delete-mcp-server | JSON：mcp_id；复用原软删除业务 |

## 迁移说明

2026-11-04：以实际库为准，技能主键和关联编号使用正整数；GET `?skill_id=...`、POST请求体中的skill_id由整数模型校验。新增 `POST /skills/catalog/create-test-run`，multipart的source为JSON：skill_id、build_id、request_id（32位小写十六进制）、conversation_input，另有可选documents。任务、关联和计数同事务，重复request_id返回原任务。技能统计及大类字段已通过SSL显式加列，详细口径见 docs/skill-catalog-integration.md。

技能中心新增 `/skills/catalog/get-metadata`、`get-class`、`list-skills`、`get-skill`、`get-build`、`download-skill`、`download-resource`，均为 GET 查询参数接口。参数、发布权限和 `keenrobot_skill_classes` 四个新增字段的显式迁移见 [技能中心接入](../../docs/skill-catalog-integration.md)。

- 原带 `{skill_id}`、`{file_id}`、`{build_id}` 的 WRQ 路由及 PUT / DELETE 路由已替换，不保留旧方法别名。调用方应同步更新。
- 后端生成的 downloadUrl 已变更；当前前端会把缓存中的旧资源下载地址转换为新查询参数地址。
- 前后端应同步部署；历史文档和旧验收脚本不能代替本文件的当前契约。
- 同事的 `/realtime-test-case-gen` 沙箱接口及其他模块不在本次变更范围内。

## 检查命令

在保留本地验收脚本的开发目录中执行（测试文件不随本次业务代码发布）：

```powershell
.\.venv\Scripts\python.exe -m pytest applications/wrq/tests/test_api_conventions.py -q
```

技能中心调用入口：POST `/skills/catalog/create-test-run`，form-data source JSON包含整数skill_id、build_id、request_id、conversation_input，可选documents；固定发布定义和资源由服务端读取。相同request_id仅创建/累计一次。
