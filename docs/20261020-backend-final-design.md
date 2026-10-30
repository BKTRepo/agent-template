# 定稿后端实施与接口交接：Skill 解析引擎、知识库

2026-10-21 更新：此前未迁入的知识库完整删除机制已完成本项目适配，完整后端 268 项通过，真实 Redis／双 Worker 自动重试验证通过。本文旧的“尚未迁入／单进程”描述保留为历史，请以 [最新迁移方案](20261021-knowledge-deletion-migration.md) 为准。


最新边界修复：新增 39 项、完整后端 246 项通过。解析中移除采用代次失效、同文档单进程互斥；向量确认无残留、严格清理原文件后才删除 SQL，失败保留记录。详情增加 cleanup_tasks（删除状态、错误、can_retry），创建者显式 retry。原 RAG 完整 Celery／Redis 删除队列未迁入，多 Worker／自动恢复仍待验收。见 [边界测试报告](20261020-backend-boundary-tests.md) 和 [最新手册](../../deliverables/开发者中心_前后端实施与联调交接手册_最终版.md)。

更新：2026-10-20。后端仓库分支：`znfwdd`。本轮仅修改后端；前端由“定位前端项目”对话维护。

依据：`智能服务调度平台MVP需求_定稿.docx`、`20261016调整内容.docx`、新版 HTML，以及用户确认的个人权限和知识库真实后端范围。文档中的页面规则用于确定输入输出；下面的 HTTP 路由是本仓库实现合同，不把它们冒充产品文档已经给出的接口。

## 1. 本轮做到哪里了

| 步骤 | 实施内容 | 当前结果 |
| --- | --- | --- |
| 1 | 核对定稿、保存旧代码快照、检查 RAG 工作目录 | 已完成；保留原有未提交改动 |
| 2 | 更新 Skill 输入合同、版本、应用和资源分类、上传校验 | 已实现，并有接口回归 |
| 3 | 复用 RAG，补齐个人知识库上传、查看、修改、版本历史和重试 | 已实现，并验证实际文件解析 |
| 4 | 验证知识库真实向量化与 Skill 生成、挂载、查询、下载 | 已通过本机真实 HTTP、真实 Embedding、独立 Chroma 链路 |
| 5 | 整理接口、配置、迁移和联调资料 | 本文及配套材料 |
| 6 | 前端真实接口接入、团队 MySQL 验证、服务器部署 | 仍需后续执行；本轮没有修改前端或服务器数据库 |

赵负责的沙箱执行、动态依赖安装、自测结果及真实上线判断不在这份后端中实现。生成成功不会自动上线，也不会执行上传脚本。审批环节已取消。

## 2. 先理解两个独立流程

**Skill 解析引擎：表单和附件 → 校验 → 生成 SKILL.md → 原文件归档 → 完整 ZIP。**

这里“解析”主要指整理字段、生成 YAML/Markdown、建立资源相对路径。上传一张图片，不会把图片识别成文字，也不会把脚本执行一遍。普通 Skill 附件不要求先创建知识库。

**知识库后端：上传文档 → 提取文本 → 按章节分块 → 调用向量模型 → 保存索引和状态。**

知识库文档提取为 Markdown 是为了预览和检索，与“把表单变成 SKILL.md”是两件事。Skill 挂载知识库时，本批仍将有权限的原文件快照放入包内；不会把整份知识库正文塞进 YAML 头部。

## 3. 相比旧版后端改了什么

| 项目 | 定稿实现 |
| --- | --- |
| 团队/小队 | 新表单不再接收团队；身份来自统一登录 token |
| 归属 | 开发者仅操作自己的 Skill；私有知识库仅创建者可见；公开知识库可读，仍仅创建者可改 |
| 技能大类 | 必选，限定平台六类 ID |
| 应用 | Skill 可不选；知识库必选，`*` 表示所有应用适用；选择值必须来自服务器目录 |
| 技能版本 | 初始 `1.0.0`，成功保存/重新生成后递增补丁位；客户端 `version` 仅为旧调用兼容字段，不控制实际版本 |
| 知识库版本 | 初始 `V1.0.0`，每次保存修改递增；编辑必须填写变更摘要 |
| Skill 直接上传 | 单文件、全部直接上传文件合计均为 `50 × 1024 × 1024` 字节，与当前前端统一；旧 20MB/5 个规则失效 |
| 知识库上传 | 不套用 Skill 的 50MiB 限制；分块写盘；至少一个实际文件 |
| 资源分类 | 每个直接上传文件必须选择参考资料、模板、静态资源或脚本 |
| Markdown 编辑 | 独立保存接口；保留附件、重新生成 ZIP、递增版本，检测过期编辑 |
| Docker/ZIP | 不处理 Docker；ZIP 是资源原文件，不自动解压或安装 |

仍保留原先认可的技术校验：最多 100 个 Skill 资源、空文件拒绝、名称大小写/全半角归一化、相对路径校验。它们不是新增的产品必填项。描述 1024 字符、运行环境 500 字符沿用选定的 Skill 规范。

50M 的字节口径在本轮与现有前端统一为 MiB；如产品以后明确为十进制 50,000,000 字节，需要双方同时改，不能只改页面文字。

## 4. Skill 表单接口

沿用统一登录，将 token 放在请求头 `token`；不增加开发者中心独立登录页面。作者、维护人、服务器目录由后端确定。

### 4.1 创建基础技能记录

`POST /skills/`，JSON：

```json
{"name":"核心系统转账用例生成","is_enabled":false}
```

返回的 `data.id` 是后续 `skill_id`。此时只是基础记录，不代表已经生成 Skill 或上线。

### 4.2 从完整表单生成/保存

`POST /skills/form/builds`，`multipart/form-data`：

- `source`：下面 JSON 的字符串。
- `files`：实际二进制文件，可重复同名表单字段；没有附件就不传。

```json
{
  "skill_id":"创建接口返回的ID",
  "skill_name":"核心系统转账用例生成",
  "skill_class_id":"SKILL-CASE-001",
  "description":"根据转账需求和业务规则生成测试用例。",
  "application":"核心系统",
  "instructions":"读取需求和流程图，生成正向、异常、边界及幂等用例。",
  "knowledge_base_ids":[],
  "resource_categories":["template","asset","script"],
  "resource_usage":"按模板组织输出；图片提供流程；脚本供运行端使用。",
  "compatibility":"Python 3.12"
}
```

上例必须同时上传三个文件，顺序与 `resource_categories` 一致，例如 `template.md`、`flow.png`、`check.py`。无附件时分类数组传 `[]`。有知识库或附件时 `resource_usage` 必填。

分类取值：`reference`→`references/`；`template`→`assets/`；`asset`→`assets/`；`script`→`scripts/`。模板和静态资源共用标准 assets 目录，但清单保留各自分类。按用户分类组织目录，不再仅靠扩展名猜用途；文件类型和路径仍会检查。

六类 ID：

| 名称 | ID |
| --- | --- |
| 测试要点生成 | SKILL-POINT-005 |
| 智能用例生成 | SKILL-CASE-001 |
| 历史缺陷案例推荐 | SKILL-BUG-004 |
| 测试报告生成 | SKILL-REPORT-006 |
| 测试数据构造 | SKILL-DATA-002 |
| UI 自动化脚本生成 | SKILL-UI-007 |

编辑时建议另传 `expected_version`，取当前服务器版本。不要用前端自己计算的新版本替代服务器版本。返回后以 `data.version`、`data.build_id` 为准。

### 4.3 查询、定义编辑和下载

| 操作 | 接口 |
| --- | --- |
| 本人列表（含未启用记录） | GET /skills/?manage=true |
| 名称预校验 | GET /skills/name-availability?name=...&exclude_id=... |
| 当前 Markdown 和构建 | GET /skills/{skill_id}/definition |
| 保存 Markdown | PUT /skills/{skill_id}/definition |
| 指定构建 | GET /skills/{skill_id}/builds/{build_id} |
| 构建历史 | GET /skills/{skill_id}/builds |
| 完整 ZIP | GET /skills/{skill_id}/builds/{build_id}/download |

Markdown 保存 JSON：`{"markdown":"完整Markdown或正文","expected_version":"1.0.0"}`。正文同步到解析源，重新打包；重复保存不会重复叠加自动资源目录。名称、身份、描述、版本等生成头部以表单/服务器记录为准。修改这些字段应走完整表单接口。

完整表单通常无需传 `skill_markdown`。若传入，正文须与 `instructions` 同步；后端会拒绝两份指令互相矛盾的请求，避免悄悄使用过期 Markdown。

已经生成包的技能，不能再用基础 CRUD 单独改名称/描述，或通过 `config` 覆盖解析版本和构建指针。应使用上述完整表单/定义保存接口，让记录与 ZIP 一致。

## 5. 知识库接口

### 5.1 新建与修改

新建：`POST /knowledge-bases/`（也支持 `/knowledge-bases/form`）。修改：`PUT /knowledge-bases/{kb_id}`。同样使用 `source` JSON 字符串与重复的 `files` 字段。

```json
{
  "knowledge_name":"转账业务规则",
  "description":"覆盖转账约束、异常和幂等规则。",
  "tag":"custom",
  "application":"核心系统",
  "is_public":true
}
```

`tag`：`general`=通识类，`custom`=自定义。`is_public:false` 表示仅本人可见，不是团队可见。

新建必须带至少一个实际文件。支持 PDF、DOCX、DOC、XLSX、XLS、Markdown、TXT。普通 PDF、DOCX、XLSX、Markdown、TXT 已有真实文件解析测试。旧 DOC 的服务器需安装 LibreOffice；扫描 PDF 的 OCR 路径需安装 Docling 与离线模型并配置后再验收。

修改时补上：

```json
{
  "change_summary":"补充重复请求的幂等规则",
  "expected_version":"V1.0.0",
  "retained_document_ids":["保留的文件ID"]
}
```

这几项要与名称、描述、标签、应用、公开状态一起组成完整 `source`。不传 `retained_document_ids` 默认保留所有旧文件；传列表则仅保留列表内旧文件，再加入本次新文件。不能删到零个文件。

上传同名新文件表示替换该文档；内容哈希未变且上次处理完成时不重复向量化，但用实际上传字节修复原文件；上次失败时重新处理。按最终文件集合检查重复，支持批量内容交换及移除后同内容改名上传。只改名称/描述等元数据不会重新处理所有文档。

### 5.2 查询、查看、修改文档、重试、挂载

| 操作 | 接口 |
| --- | --- |
| 可见列表/名称模糊搜索 | GET /knowledge-bases/?search=...&offset=0&limit=50 |
| 名称预校验 | GET /knowledge-bases/name-availability?name=... |
| 应用目录 | GET /knowledge-bases/applications |
| 详情和处理状态 | GET /knowledge-bases/{id} |
| 编辑历史 | GET /knowledge-bases/{id}/history |
| 文件列表 | GET /knowledge-bases/{id}/documents |
| 解析 Markdown 预览 | GET /knowledge-bases/{id}/documents/{doc_id}/preview |
| 原文件下载 | GET /knowledge-bases/{id}/documents/{doc_id}/download |
| 修改 Markdown/TXT | PUT /knowledge-bases/{id}/documents/{doc_id}/content |
| 查看文本分块 | GET /knowledge-bases/{id}/chunks |
| 重试失败/恢复中断任务 | POST /knowledge-bases/{id}/retry |
| 单个文档重试 | POST /knowledge-bases/{id}/documents/{doc_id}/retry |
| 挂载到本人技能 | POST /knowledge-bases/{id}/mounts |

文本编辑 JSON：`{"content":"新正文","change_summary":"修正规则","expected_generation":1}`。二进制 Word/Excel/PDF 通过上传同名新文件修改，不会把 UTF-8 文本写进 DOCX/XLSX 文件。

挂载 JSON：`{"skill_ids":["本人已生成的技能ID"],"resource_usage":"生成前读取业务规则。"}`。挂载会重新打包并递增技能版本。批量结果逐项返回 `succeeded/failed`，不能把 HTTP 成功误认为每一项都挂载成功。尚未生成基础包的技能需先补齐表单。

详情返回 `user_id`、`can_edit`、`version`、`history`、`documents`、`document_count`、`reference_count`。状态为 `processing/completed/failed`；只要仍有任务处理中，总状态保持 processing；全部结束后再汇总完成或失败。创建响应返回处理中状态，前端应轮询详情。

## 6. 关键函数怎样工作

| 函数/文件 | 输入→处理→输出 |
| --- | --- |
| `source_from_developer_form()` | 校验必填、类/应用目录、逐资源分类及说明，将页面字段转换成统一生成源 |
| `SkillPackageService.build_form()` | 检查所有者；事务锁住技能记录；计算下一版本；占用唯一名称；构建后保存源和当前构建指针；失败回滚 |
| `SkillPackageService.resolve()` | 只接受知识库/文档 ID；校验本人或公开权限；从数据库解析原文件路径和哈希 |
| `SkillPackageBuilder.build()` | 临时目录复制文件、流式检查附件大小、计算哈希、渲染 Markdown、验证链接、制作 ZIP，完成后原子重命名 |
| `_render_skill()` | 用安全 YAML 序列化生成标准头部；写指令正文、公共使用说明和相对资源链接，不调用大模型 |
| `rebuild_saved()` | 读取并校验旧构建；复用旧附件字节；保存 Markdown 或挂载关系；重新生成新构建 |
| `KnowledgeService.stage()` | 文件类型/文件名检查；随机服务器文件名；分块落盘和 SHA256；不设置知识库业务大小上限 |
| `KnowledgeService.save()` | 校验权限/版本/变更摘要；事务写元数据和历史；按文件名与哈希识别新增/替换/未变/移除文档；只提交变化文档的任务 |
| `load_document_pages()` | 按类型实际提取文本；DOCX 保持段落和表格顺序，Excel 保留工作表，PDF 提取文本 |
| `chunk_document()` | 复用 RAG 工作区分块器；按 Markdown 章节切开，再递归切分，保留来源章节归属 |
| `DocumentPipeline.process()` | 数据库领取任务→解析→分块→真实 Embedding→先写新索引→事务切换分块→清理旧索引→完成 |
| `retry()` | 创建者才能重试；恢复失败、尚未领取或超过 30 分钟未完成的任务；递增 generation 使旧工作结果失效 |

`build_id` 标识一次不可变构建；`version` 是业务保存版本；`generation` 是某文档的处理代次，三者用途不同。

后端不会让客户端提供磁盘绝对路径。下载前校验完整包，图片和普通附件保存原字节。构建失败时清理临时目录；SQL 保存失败时清理本次新构建，旧构建可继续读取。

## 7. 知识库失败为什么不会毁掉旧结果

向量模型不可用时，原文件和已解析 Markdown 仍保留，状态标记失败；原有成功分块与向量不先删。新向量和 SQL 切换成功后才删除旧索引。

向量写入前，先把待写 ID 记入数据库清理清单，便于进程中断后重试回收。索引清理失败不会谎报完成。重复任务回调不会重复处理已完成文档。

本批使用 FastAPI 响应后的后台任务，任务状态持久化在 SQL；没有声称已经移植整套 Celery 调度。进程中断的任务通过重试接口显式恢复，尚未实现无人值守自动扫描恢复。

Windows 上旧文件若被下载进程占用，清理会记录日志，避免将已经提交的保存误报失败；这类遗留文件需要后续维护清理。

## 8. RAG 复用了哪些内容

来源：`D:/projects/agent-template-release-qoder`，`release/qoder-worker-db-20260930` 工作区。读取的是当时磁盘内容，包含未提交改动，而非只读 HEAD。

- `applications/jiayueyang/rag/chunker/` → 本仓库 `applications/knowledge_base/rag/`：递归分块及入口，调整了导入位置和配置名。
- 尚未提交的 `section_context.py` → 同目录：保留标题与章节归属，避免跨章节误挂上下文。
- 已修改的 `common/docling_native.py` 和 `docling_bundle.py` → 本仓库同名文件：可选 Docling OCR 解析路径。
- 复用本仓库已有的 Embedding 请求和 Chroma 存储，避免搬入旧项目的全局文档表、Milvus 与整个问答运行环境。
- 增量更新时保留旧结果、处理失败可重试的机制适配到新平台的个人知识库模型；没有声称整套旧 RAG 已原样迁入。

复用文件哈希与来源见 `applications/knowledge_base/rag/PROVENANCE.json`。修改前快照保存在忽略提交的 `output/skill-scope-check/final-20261019-baseline/`。本轮没有写入原 RAG 工作目录。

## 9. 运行配置与本机验证

现有环境已安装本批需要的解析及向量依赖。为消除 Chroma 的 PyPika 与旧 ORM 的包目录冲突，同步将 Tortoise ORM 更新为 `0.25.1`、`pypika-tortoise` 更新为 `0.6.5`；需团队数据库环境再验证。

本机服务使用独立 SQLite、上传目录、构建目录、Chroma，均位于 `output/platform-integration/`；不连接原 RAG 或团队数据库。

在后端仓库的 PowerShell 中启动：

```powershell
$env:KNOWLEDGE_RAG_ENV_FILE='D:/projects/agent-template-release-qoder/.env'
.venv/Scripts/python.exe -m examples.platform_backend_server
```

接口文档：`http://127.0.0.1:8520/docs`。只监听本机。联调账号 `skill-dev` / `SkillLocal2026!` 仅由这个隔离示例创建。

`KNOWLEDGE_RAG_ENV_FILE` 只读取 RAG 的 Embedding 地址、模型名、密钥，支持 `EMBEDDING_BINDING_HOST`、`EMBEDDING_MODEL`、`EMBEDDING_BINDING_API_KEY`；不继承其数据库、Redis、JWT 或上传目录。也可直接配置本项目的 `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL_NAME`、`EMBEDDING_API_KEY`，本项目显式配置优先。

检查命令：

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m examples.verify_platform_backend
```

第二条会向本机写入合成样例，调用真实向量模型，验证入库、元数据修改不重建、单文档更新、带图片/模板/脚本的 Skill、知识库挂载和 ZIP 下载。报告在 `output/platform-integration/verification.json`，不记录 token 或模型密钥。

## 10. 前端接入时需要改的适配层

本轮不修改前端文件。当前页面已实现与 API 接入是两个验收项，不能因为页面模拟流程通了就算真实联调完成。

| 页面数据 | 后端字段/规则 |
| --- | --- |
| `classId` | `skill_class_id`，必传 |
| `name` | `skill_name`；知识库是 `knowledge_name` |
| `applicationIds[0]` | `application`；空 Skill 传 null，知识库全应用传 `*` |
| 每个上传资源的 `category` | 按实际二进制上传顺序组成 `resource_categories`，不要按原数组排序后错位 |
| 当前版本 | 显示服务器返回值；编辑请求可作为 `expected_version` |
| `resourceIds` | `knowledge_base_ids`；只能使用真实接口返回的 ID |
| `resourceUsage` | `resource_usage` |
| 演示用户/本地创建人 | 真实接口使用统一登录身份；不能用演示用户切换控制服务器权限 |
| 知识库标签 | 页面中文映射 `general/custom` |
| 公开/私有 | `is_public`；不发送 team/squad |

建议按这个顺序联调：统一登录 token → 应用目录 → 知识库列表/新建/轮询 → 查看/修改/历史 → Skill 无附件生成 → 带分类附件生成 → 挂载真实知识库 → Markdown 保存 → 完整 ZIP 下载 → 失败/越权用例。

前端当前 `src/api/skillClient.ts` 旧请求尚未发送定稿的类、应用和分类；知识库页面仍有本地模拟存储。请在前端对话中按本文接入，不要通过放松后端必填项掩盖字段丢失。服务地址/代理也要明确指向本轮服务，避免误连旧的 8519 后端。

错误按统一 envelope 的 `status/message/data.errors` 显示，常见字段校验给出中文提示。知识库业务错误使用 HTTP 400/403/404/409，模型/请求校验使用 422；Skill 历史业务错误仍兼容原 envelope 规则，不能仅检查 HTTP 200。下载接口返回二进制 ZIP，不按 JSON 解析。

## 11. MySQL 升级与交接给赵

本轮没有执行服务器 DDL。已有数据库先备份并停止写入，在测试库预审名称，再参照 `docs/migrations/20261020-knowledge-platform.sql` 升级字段。SQL 是已有表的升级材料，不可重复对已升级表执行；新建隔离 SQLite 由示例生成完整模型。

```powershell
.venv/Scripts/python.exe -m examples.migrate_knowledge_names --configured-db
# 测试库名称无冲突、并完成表结构升级后再执行：
.venv/Scripts/python.exe -m examples.migrate_knowledge_names --configured-db --apply
```

`--configured-db` 明确选择当前配置数据库；默认审计，不加 `--apply` 不回填。也支持 `--sqlite <已有文件>`。Skill 名称迁移继续使用原 `examples.migrate_skill_names` 工具。不要把本机 SQLite 测试当成正式 MySQL 已验收。

交给赵的最小数据：`skill_id`、不可变 `build_id`、版本、构建清单、包下载接口或受控读取目录。赵的自测结果需绑定同一个 `build_id`；修改后生成的新包需重新自测。上线接口由其读取服务器真实自测结果，不接受页面模拟 passed 作为依据。

## 12. 测试证据的边界

补充用户操作场景并修复问题后，**207 项自动化回归全部通过**；最新代码重启后的真实向量模型、批量文件操作与完整 ZIP 验证也通过。最新证据、19 项新增用例和功能清单见 [用户流程测试报告](20261020-backend-user-tests.md)；初轮 188 项记录保留于 [原验证记录](20261020-backend-verification.md)。

自动化回归覆盖实际 ORM/HTTP/文件读写和真实格式解析；隔离用例对外部向量模型使用明确测试替身，验证失败、清理与权限。另有独立本机真实 HTTP + 实际 Embedding + 实际 Chroma 验证，不能混为同一种测试。

已验证的格式解析：普通文本 PDF、DOCX、XLSX、Markdown、TXT。旧 DOC 的 LibreOffice、旧 XLS 样本、Docling OCR/复杂表格模型还需相应服务器依赖及样本验收。生产 MySQL、多进程部署、前端页面真实会话接入、沙箱运行和上线均不在这次本机通过的证据内。

后续新增 UI 接口调用由前端对话继续；本后端分支尚未提交、推送或创建 PR。
