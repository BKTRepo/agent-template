# WRQ 接口开发规范与当前清单

## 新建技能润色

`POST /skills/developer/polish-form` 使用平台 token。JSON 请求体和响应 `data` 使用 `description`、`instructions`、`resource_usage`、`compatibility` 四个字符串字段。允许留空，至少填写一项。请求内容合计最多 12,000 个 UTF-8 字节，超过上限返回 422。字段长度沿用技能表单。

接口复用现有模型连接，空白字段返回空字符串。超时返回 504，模型不可用或建议无效返回 502。建议只供用户预览和确认，应用后由原有草稿保存或调试流程提交表单。

## 悬浮对话台测试案例产出物联调

产出物和资产管理接口的业务异常使用平台默认失败响应（HTTP 200、业务码 `999999`、`status: "failure"`），具体原因见 `message`。源文件 SHA-256 与 `base_hash` 不一致时，提示重新打开产出物。

以下接口以 `/assistant/artifacts` 为前缀，均使用平台 token，按登录人定位样例文件。仅配置 `ASSISTANT_ARTIFACT_MOCK_DIR` 时启用，不涉及 `chat_artifact` 或资产数据库表。

平台悬浮窗的纳入状态与归档走 `/api/assets/source-status` 和 `/api/assets/create`。原样例的本地快照接口用于单独联调。正式资产查询及归档契约见 [资产管理接口](../../docs/asset-management.md#接口)。

| 方法 | 路径后缀 | 参数与行为 |
|---|---|---|
| POST | /create-demo | JSON 可选 `kind`，默认 `test_cases`，支持 `docx`、`xlsx`、`py`、`js`、`ts`、`sh`、`sql`、`md`、`json`。已存在时打开当前原件 |
| GET | /detail | 查询 `artifact_id`。返回 `is_test_case`、格式和 `base_hash`。测试案例返回案例与分组，普通文件返回 `editor` 及对应的 `blocks`、`sheets` 或 `text` |
| GET | /sheet | 查询 `artifact_id`、`base_hash`、`sheet_index`、行列偏移与上限，返回普通 XLSX 工作表的一页单元格 |
| POST | /save-content | JSON `artifact_id`、`base_hash`，另传 `cases`、`paragraphs`、`cells` 或 `text` 四者之一。锁内校验原文件哈希，冲突返回 409 |
| GET | /download | 查询 `artifact_id`、可选 `base_hash`、可选 `archived`。下载整份原格式文件或归档快照 |
| GET | /asset-status | 查询 `artifact_id`。返回样例是否已归档 |
| POST | /submit-to-assets | JSON `artifact_id`、`base_hash`、`name`、`application_identify`。重复提交返回已有样例归档 |

测试用例工作簿逐个识别有效案例工作表，标准生成文件仍校验十八列表头。说明页、统计页等不符合案例表头的工作表保留在原件中。至少一个工作表包含有效表头时读取其中的案例，否则沿用格式错误响应。案例返回 `sheet_index`、`sheet_name`，多表时内部案例编号按工作表区分，允许不同工作表复用案例编号或序号。单表内部编号沿用已有规则。全部案例合计最多 5000 条。导图以各工作表名称为根，按表调用模型归纳测试要点。保存按服务端解析的工作表和原行定位，整份导出保留全部工作表。

技能中心在线测试重新打开时调用现有 GET `/realtime-test-case-gen/skills/latest-run?skill_id=...`，由后端验证账号权限并返回最新任务。恢复任务状态和文件清单，结果下载仍验证任务编号、文件名和有效期。暂无任务时清空旧展示，最新任务运行中或失败时显示对应状态。该查询与恢复流程复用在线测试权限，展示历史结果不登记当前开发者版本的调试通过状态。后端按任务保留历史产物，过期清理规则沿用已有配置。

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
| GET | /list-skills | 本人技能分页；page、page_size、name、class_id、status、application 为查询参数。列表中的 `skill_markdown` 为空字符串，原文通过详情接口获取 |
| GET | /get-skill | 按 skill_id 查询本人技能及当前知识库引用；只读、不递增修订或改变技能状态 |
| POST | /create-skill-draft | JSON：DeveloperSkillForm；新建必选所属应用（application_ids 选择一个有效 identify，或 application_paso），缺失/空白返回 application_paso 字段错误；已有历史技能不补写默认应用 |
| POST | /save-skill | JSON：skill_id + 原表单，包括 expected_revision |
| POST | /delete-skill-draft | JSON：skill_id；仍仅软删除草稿 |
| POST | /offline-skill | JSON：skill_id、reason_code、reason_text |
| POST | /publish-skill | JSON：skill_id；仍由服务端核验调试结果 |
| POST | /register-debug-run | JSON：skill_id、run_id、build_id/skill_version_id 及原登记字段 |
| GET | /get-debug-run | 查询参数：skill_id、run_id |
| GET | /list-knowledge-tool-calls | 本人任务的 MCP 调用记录，查询参数 run_id、limit、offset |
| GET | /get-knowledge-tool-call | 查询参数 search_id，对应调用记录 id。返回本人调用记录及召回、融合、重排明细，详见 [MCP 单次检索明细](KNOWLEDGE_MCP.md#单次检索明细) |
| POST | /upload-resource-files | multipart：files、categories（JSON 数组字符串） |
| GET | /download-resource-file | 查询参数：file_id |
| POST | /upload-resource-version | 已停用旧功能，仅保留明确的停用提示；multipart：source_id、files、categories |

`get-form-metadata` 的 `resource_categories` 从 `keenrobot_resource_categories` 查询已启用项，包含 `id`、`code`、`name`。上传下拉框显示字典名称，上传时传当前名称，构建时映射为当前字典代码。空字典提示管理员配置。停用项保留历史显示，重新保存前需选择已启用项。构建按已持久化附件的分类读取代码，分类名称或代码均支持配置。`reference`、`template`、`asset`、`script` 保持原有目录分配，其余分类按文件类型分配到现有资料、脚本或静态资源目录。

技能表单的 `description` 取消字符数上限，持久化到 LONGTEXT，现有库迁移见 `docs/migrations/20261119-skill-description-longtext.sql`。`resource_usage` 始终必填，纯空白视为空。普通保存与草稿保存均使用相同规则，上传资源为空时也需要填写。

案例数据包含可选 `description`，标准模板读取「描述」列。导图案例叶节点优先显示该字段，长文本单行省略并提供完整悬停提示，旧文件缺少描述时显示案例名称。原产物编辑保存可再次同步到已归档资产，资产预览页面只读。保存时未携带新增描述字段的旧客户端沿用原描述。

示例：

```http
GET /skills/developer/download-resource-file?file_id=123
GET /skills/developer/get-debug-run?skill_id=skill-001&run_id=run-001
POST /skills/developer/offline-skill
Content-Type: application/json

{"skill_id":"skill-001","reason_code":"OTHER","reason_text":"维护升级"}
```

## Skill 包

技能中心在线测试弹窗重新打开时，调用既有 GET `/realtime-test-case-gen/skills/latest-run?skill_id=101`，按当前身份恢复可访问的最新任务及文件清单。无任务的 HTTP 404 清空原显示，执行中或失败时展示该任务状态，完成时重新读取该任务的结果文档。恢复只读展示流程复用沙箱查询和下载接口，任务仍按既有有效期清理。

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

## 总览页面查询

| 方法 | 路径 | 查询参数与返回 |
| --- | --- | --- |
| GET | /overview/cumulative-summary | 返回 `connected_user_count`、`online_skill_count`、`skill_call_count`、`knowledge_mount_count` |
| GET | /overview/period-summary | `start_date`、`end_date`。返回日期、`active_user_count`、`test_artifact_count`、`new_skill_count`、`new_knowledge_base_count`、`trend`、`top_skills` |
| GET | /overview/metric-detail | `metric`、`page`、`page_size`。期间指标须带日期。返回 `items`、`total`、`page`、`page_size`、`pages` |

两个 Skill 指标只统计当前有效且已上线的 Skill。日期使用 `YYYY-MM-DD`，按北京时间包含结束日全天。新增按首次创建时间筛选，计数和明细共用筛选条件。

- `null` 表示对应数据源尚未接入，`0` 或空数组表示成功查询且没有记录。当前真实指标为 `online_skill_count` 和 `new_skill_count`。其他指标的明细查询返回 HTTP 503，接入后使用下表字段。
- `trend` 包含 `bucket_days` 和 `points`。按包含首尾的自然日数分组，14 天内为 1 天，15–30 天为 2 天，超过 30 天为 7 天。每组从所选开始日顺次切分，最后一组截到结束日。每个数据点返回 `start_date`、`end_date`、`artifact_count`、`skill_call_count`，按日期升序。一个系列尚未接入时对应值为 `null`。
- `top_skills` 每项包含 `skill_id`、`name`、`call_count`、`artifact_count`。按调用量降序、产出物数量降序、技能 ID 升序返回前五名。
- 明细的时间值以 ISO 日期时间返回，优先带时区偏移。多行可属于同一个 Skill 时，每行提供独立的 `id`。

| metric | 明细字段 |
| --- | --- |
| `connected_users` | `department`、`username`、`employee_no`、`first_access_at`、`last_login_at`、`login_count` |
| `online_skills` | `skill_id`、`name`、`skill_class_name`、`application_name`、`published_at`、`version`、`status`、`call_count`、`last_called_at`。正式调用数据源接入前最后两项为 `null` |
| `skill_calls` | `skill_name`、`operator_login_name`、`called_at` |
| `knowledge_mounts` | `knowledge_base_name`、`knowledge_base_version`、`target_name`、`operator_login_name`、`mounted_at` |
| `active_users` | `department`、`username`、`employee_no`、`conversation_call_count`、`first_called_at`、`last_called_at` |
| `test_artifacts` | `generated_at`、`employee_no`、`department`、`artifact_type`、`skill_name`、`artifact_count`、`duration_ms`、`status` |
| `new_skills` | `skill_id`、`name`、`skill_class_name`、`application_name`、`created_time`、`creator_login_name`、`version`、`status` |
| `new_knowledge_bases` | `name`、`application_name`、`creator_login_name`、`created_time`、`version`、`file_count`、`updated_at` |

## 检查命令

在保留本地验收脚本的开发目录中执行（测试文件不随本次业务代码发布）：

技能中心调用入口：POST `/skills/catalog/create-test-run`，form-data source JSON包含整数skill_id、build_id、request_id、conversation_input，可选documents；固定发布定义和资源由服务端读取。相同request_id仅创建/累计一次。


## Skill 一键导入

上线前显式执行 `python -m applications.wrq.migrations.skill_import --apply`，不带 `--apply` 只查询结构并打印待执行 SQL。迁移增加导入批次/明细、附件相对路径及自定义资源分类，并调整附件唯一索引。MySQL DDL 不支持整组事务回滚，应按部署流程备份并在维护窗口执行。

- `GET /skills/import/get-limits` 查询上传限制。
- `POST /skills/import/prepare` 使用 multipart：`files` 为文件数组，`manifest` 为 JSON 字符串，包含 `upload_mode`（file/directory/zip）和 `files:[{index,path}]`。目录路径使用 `/`，索引对应文件顺序。单文件仅接受 SKILL.md，ZIP 和目录递归识别技能根目录。
- `POST /skills/import/confirm` 使用 JSON：`{import_id,items:[{item_id,name,class_id,application_paso}]}`。创建人由 token 确定，分类、描述、正文及附件均由后端校验及读取。返回每项的状态、errors 和 skill_id；批内部分失败以明细表达。对相同 item_id 重试不会重复创建。
- `GET /skills/import/status?import_id=...` 返回本人批次状态，包含过期标志和逐项导入结果。

暂存默认24小时、批次总量200MiB、单文件50MiB、每技能附件合计50MiB、单技能最多100个文件、批次最多1000个文件/50个技能。`SKILL_IMPORT_MAX_BATCH_BYTES` 和 `SKILL_IMPORT_EXPIRE_HOURS` 可配置。定时任务及上传时清理临时文件，成功草稿和正式导入结果保留。

附件详情新增 `relativePath`，保存技能时必须回传；`definition_origin` 表示 platform/import。每个技能最多导入 50 个附件（不含 SKILL.md）。导入附件默认使用资源字典 `custom`（自定义资源）。开发者调试和技能中心在线测试都由服务端从已校验的构建包读取导入附件，按原相对路径写入沙箱的 `/input/resources`，浏览器无需再提交 `mounted_resources`。导入技能构建时保留正文里的原始附件引用，平台不另加附件清单。导入后 DRAFT、revision=1、version=NULL，首次调试前不产生构建或发布记录。

目录导入支持同一文件夹下的多个ZIP技能包，及Skill子目录与ZIP混合。ZIP独立保留来源路径，解压后累计校验批次大小和文件数。发现外层PDF等未归属任何Skill的文件，或ZIP中没有SKILL.md时，整批拒绝并返回具体路径；Skill根目录内的附带文件保留为附件。
### 导入完成后返回编辑

- `POST /skills/import/restart`，JSON：`{"import_id":"原批次编号"}`。校验归属、有效期后恢复同一批次、同一候选为可填写状态；保留 `skill_id`，返回当前草稿归属信息及 `selection.expected_revision`。
- 再次确认：已有 `skill_id` 的条目通过原技能保存逻辑更新，必须回传 `expected_revision`；未成功创建的条目才新增。权限、名称冲突及并发版本校验沿用开发者中心。已进入调试、发布流程的技能通过详情页处理，不从旧导入窗口覆盖。
- 返回选择文件后重新上传，manifest 可带 `replaces_import_id`。服务端按原目录、技术名称等逐条匹配并保留原技能编号；数量不同或无法唯一匹配则拒绝，不猜测对应关系、不新增记录。关闭后重新打开的新一轮导入不带该字段。
- `POST /skills/import/check-names`：JSON `{"import_id":"批次编号","items":[{"item_id":"候选编号","name":"名称"}]}`，返回 `{valid,errors:{候选编号:[错误文本]}}`。点击“开始导入”后调用并提示，进入填写页及修改输入时不调用；支持临时文件回执，不写业务表，并排除原 `skill_id`。真正保存仍在事务内复核名称和归属。

### 上传校验、系统临时目录与正式导入（当前交互）

- 选择文件后按技能调用 `POST /skills/import/stage`，multipart manifest 与 prepare 相同。服务端校验并抽取到临时文件，候选、归属及抽取结果以 `stage.json` 暂存，**不写技能、附件、导入批次/条目等业务表**。格式不合格的条目显示原因并拦截，合法项可进入填写页；全部不合法时清除本批临时文件。
- Linux默认 `/tmp/keenrobot-skill-import`；Windows默认系统Temp下的同名专用子目录。`SKILL_IMPORT_TMP_DIR` 可配置为独立临时挂载目录，禁止指向 `/tmp`、系统Temp根目录或产物目录。`SKILL_IMPORT_EXPIRE_HOURS=24`、`SKILL_IMPORT_CLEANUP_SECONDS=300`、`SKILL_IMPORT_TMP_MAX_BYTES=2147483648`、`SKILL_IMPORT_TMP_MIN_FREE_BYTES=134217728`。定时及上传时优先清过期目录，压力下回收最旧的闲置暂存；跨进程锁跳过正在处理的批次，空间仍不足返回明确错误。只删除专用目录内受控批次，正式附件和定义不受影响。
- 点击“开始导入”后检查名称（含批内重名），排除自己的 `skill_id`；不通过时在填写页标注错误。校验通过才调用 `POST /skills/import/confirm`，将临时回执正式写入导入表并创建/更新草稿。保存时复核名称、归属、权限、文件摘要及版本，防止并发覆盖。
- `POST /skills/import/discard` JSON `{"import_id":"批次编号"}` 移除本人临时文件，删除单项、清空或关闭弹窗时调用；不删除正式技能。过期或被容量清理的暂存需重新上传。
- ZIP按技能根目录分行；stage manifest 的 `selected_root` 限定提取范围。原ZIP由服务端解压和验证，不信任客户端解压数据。每项保留 `{import_id,item_id,skill_id,revision}`；返回编辑复用原编号，文件替换通过 replaces_import_id 关联原技能。确认响应中断先查同一回执，避免重复新增。正式导入后的纯信息修改无需临时文件，清理不影响原草稿。
