# 开发者中心 Skill 解析引擎联调说明

> 当前八项表单已适配，描述、版本由开发者必填。以 [Skill 解析引擎后端设计 v3](skill-parser-backend-design-v3.md) 与 [八项版执行记录](skill-form-v3-progress.md) 为准。本文下方旧标准合同仅供兼容接口参考。

## 当前页面入口：八项表单

先用现有 POST /skills/ 取得技能 ID，再向 POST /skills/form/builds 提交 multipart：source 是 JSON 字符串，files 是重复文件字段。使用已有 Token，不单独增加登录页面。

source 接收 skill_id、skill_name、description、version、instructions、knowledge_base_ids、resource_usage、compatibility。生成时名称/描述/版本/指令必填；任意知识库或文件存在时 resource_usage 必填。描述最多 1024、版本最多 64 字符。完整请求见 [八项 source 示例](../examples/skill-package/source-form-v3.json)，使用前替换真实 skill_id。

description 和 version 使用表单内容，不自动生成或从历史补齐；技术名继续稳定。PNG/JPG/JPEG/GIF/WebP/SVG 统一放入 assets，文件原样复制。查询和完整 ZIP 下载接口继续复用下文接口。此更新不需要新增数据库版本列；已有名称键迁移另按历史记录部署。

---

> 2026-10-13 更新：本文记录旧合同。六项表单入口 `POST /skills/form/builds`、名称唯一性、资源校验及图片 assets 归类已实施，见 [最新设计](skill-backend-design-v2.md) 和 [校验执行记录](skill-form-validation-progress.md)。新版需要名称键数据库迁移；下文“不需要迁移”仅指旧版文件生成器。旧字段和分入口方式保留兼容。

本模块在 `KKNOBUG/agent-template` 的 `master` 基础上实现，复用 FastAPI、Skill 模型、JWT 鉴权和 KnowledgeBase/Document 数据。输入是开发者表单加挂载文件，输出是 `SKILL.md`、资源目录、ZIP 和构建清单。构建记录保存在指定文件目录，未增加数据库表，因此本次修改不需要数据库迁移。

## 入口及最小链路

真实路由前缀是 `/skills`，与 `core/initializations/app_initialization.py` 一致；不要套用旧 README 中部分接口的 `/api/agent` 前缀。

所有请求携带 `token: <登录获得的 JWT>`，沿用现有响应格式。业务成功查看 `status == "success"`；业务失败查看 `status == "failure"` 和 `data`，不要仅以 HTTP 200 判断成功。现有全局异常处理器也可能用 HTTP 200 封装错误。

1. 先调用已有 `POST /skills/` 创建技能，得到 `data.id`。
2. 调用 `POST /skills/{skill_id}/validate` 检查表单和已有资源权限。
3. 调用 JSON 或 multipart 构建接口，保存返回的 `build_id`。
4. 查询构建清单或下载完整 ZIP。
5. 运行模块在验证目录后，使用返回的 `workspace_dir` 读取该 Skill。

创建技能示例（这只是记录创建，不意味着审批通过）：

```json
{
  "name": "核心系统用例生成",
  "description": "支付业务测试设计",
  "is_enabled": false
}
```

技术名与展示名分别保存：现有 Skill 的 `name` 可作为中文展示名；构建表单的 `name` 必须是标准技术名，构建源完整记录在 `manifest.json`。`display_name`、团队、系统等也保存在该构建源中。

## 新增接口

| 方法 | 路径 | 请求 |
| --- | --- | --- |
| POST | `/skills/{skill_id}/validate` | JSON 表单；返回缺失字段、错误、警告 |
| POST | `/skills/{skill_id}/builds` | JSON 表单；挂载现有 Document/KnowledgeBase |
| POST | `/skills/{skill_id}/builds/upload` | multipart：`source` 为 JSON 字符串，`files` 为重复文件字段 |
| POST | `/skills/{skill_id}/builds/upload/entries` | multipart：`source` 为 JSON 字符串，`reference_files` 与 `script_files` 为两个入口的重复文件字段 |
| GET | `/skills/{skill_id}/builds` | 构建历史，支持 `limit` 和 `offset`，返回 `data.items` 与 `data.total` |
| GET | `/skills/{skill_id}/builds/{build_id}` | 读取清单并验证文件哈希 |
| GET | `/skills/{skill_id}/builds/{build_id}/download` | 验证后下载完整 ZIP |

### 当前表单字段与生成进度

第二步补齐的数据结构已在第三步接入生成器；草稿省略新字段时仍然可以解析：

| 字段 | 类型与限制 | 来源 |
| --- | --- | --- |
| `compatibility` | 字符串，默认空，最多 500 字符，去除首尾空白 | 选填的运行环境要求 |
| `resources[].usage` | 字符串，默认空，最多 10000 字符，去除首尾空白 | 每个资源的使用说明，包含用途、使用条件或脚本调用方式 |

允许字段为空，是为了接收不完整草稿和返回业务补填报告。生成时每个直接上传资源（含 `upload_index`）必须有非空 `usage`，缺失时返回 `resources[序号].usage`，不会发布目录包。已有 Document 挂载暂不增加说明必填规则；填写了说明就会写入正文。

`compatibility` 非空时写入 YAML，空时完全省略。正文生成实现名称、功能说明、执行指令，以及有实际文件的参考资料、脚本或模板与静态资源章节；文件链接相对于 Skill 根目录，使用说明支持多行文本。无附件时只生成 `SKILL.md`，不生成空资源目录或章节。

YAML 顶层保持标准字段 `name`、`description`、可选 `compatibility` 和 `metadata`。平台信息写入字符串映射 `metadata`：`display_name`、`version`、`skill_id`、后端身份的 `creator_id`，以及非空的 `skill_class_id`、`system`、`team`、`model_tier`。本期省略 `license`、`allowed-tools` 和尚无真实来源的维护人信息。

`resources[].role` 保留为内部分类字段。第四步新增 `/builds/upload/entries` 上传适配器：参考文件入口和脚本入口分别由后端固定设置 `reference` 和 `script`，无需增加开发者手动分类的表单项。旧 `/builds/upload` 接口保留，仍使用内部 `role`、`upload_index`；本步没有修改前端 UI 或 mock。`asset` 保留旧合同兼容性，不代表本期新增静态资源页面。

请求不增加 `creator_id`、`maintainer_id` 或 `user_id` 字段；身份沿用接口认证上下文，客户端传入这些额外字段会被拒绝。维护人元信息需要用户体系实际提供后再写入，不能从表单任意指定。

校验表单示例：

```json
{
  "name": "core-case-generator",
  "display_name": "核心系统用例生成",
  "description": "根据支付需求生成测试用例；适用于支付业务测试设计。",
  "instructions": "读取需求，结合业务规则，生成正向、异常和边界用例。",
  "version": "0.1.0",
  "resources": [],
  "knowledge_base_ids": []
}
```

本平台的可构建要求是 `name`、`display_name`、`description`、`instructions` 和 `version` 非空；实现名称、执行指令和版本是平台约定，不是官方 YAML 必填字段。技术名为小写英文字母、数字、单连字符，长度 1–64；描述不超过 1024 字符。请求结构/字段类型错误由现有 FastAPI 校验机制处理；空值等业务缺失由本模块返回报告。

缺失信息响应中的 `data`：

```json
{
  "valid": false,
  "missing_fields": [{"field": "instructions", "reason": "请补充此字段"}],
  "errors": [],
  "warnings": []
}
```

`validate` 不会发布目录包。对新上传文件，它只校验绑定字段，并返回警告：文件名、内容、大小和最终路径将在实际构建时检查。它也不表示所有 Markdown 本地链接都已验证；本地链接存在性检查发生在包生成后。

## 文件与知识库挂载

每个 `resources` 项必须且只能提供 `document_id` 或 `upload_index`；文件用途 `role` 为 `script`、`reference` 或 `asset`，分别放入 `scripts/`、`references/`、`assets/`。

已有文件示例：

```json
{
  "document_id": "从已有知识库文档列表取得的 ID",
  "role": "reference",
  "target_path": "business-rules.md",
  "usage": "测试设计前读取业务规则。"
}
```

`target_path` 是用途目录下面的相对路径，可为空以沿用原文件名。脚本有相对导入时，应为相关文件填写保留其结构的路径。例如 `main.py` 和 `utils/helpers.py`。本周不解包任意 ZIP，也不分析和重新编排 Python 包。

可选的 `content_hash` 是固定的 SHA-256。指定值与数据库文件版本不一致时拒绝构建；复制时也对实际字节计算哈希，检查原文件是否已经变化。

知识库选择使用 `knowledge_base_ids`。服务先验证现有知识库访问权限，然后将其原文件作为 `reference` 快照到包中；与显式选择的同一 Document ID 去重。自动文件名使用文档 ID 的短哈希前缀避免重名和路径过长，完整 ID 与内容哈希保留在清单中。空知识库返回警告。

当前仓库没有资源版本表；本版以构建文件快照和内容哈希固定资源内容。没有建立向量检索服务，也不会调用 Embedding。文档即使尚未完成向量处理，只要原文件存在且权限/哈希有效，仍可被复制。

以上 Document/KnowledgeBase 能力是仓库草稿已有适配器，当前只做隔离数据库回归，不代表平台资源模块已部署。本期独立演示使用真实本地文件且 `knowledge_base_ids=[]`；前端 mock 资源 ID 不能传给真实接口充当数据库 ID。正式知识库使用检索还是文件快照，仍需在后续接入时确认。

## 第四步：参考资料和脚本分入口上传

新表单接入建议使用 `POST /skills/{skill_id}/builds/upload/entries`。认证、既有 Skill 记录创建及成功/失败响应规则与旧上传接口一致，不增加数据库迁移。

| JSON 字段 | 对应 multipart 文件字段 | 后端目录 |
| --- | --- | --- |
| `reference_uploads` | `reference_files` | `references/` |
| `script_uploads` | `script_files` | `scripts/` |

每个入口的文件和说明按各自顺序一一对应，数量必须一致；不同入口之间的发送顺序不影响对应关系。只有资料或只有脚本都可以，两个入口都不上传时可省略相应数组。用途根据入口确定，不按文件扩展名猜测。

每个说明项仅接收 `usage`、选填的内部 `target_path` 和 `content_hash`，不接收 `role`、`upload_index`、`document_id`。`usage` 非空必填，例如脚本何时使用、调用命令、输入及结果含义。调用说明由开发者提供，后端不推测命令、不执行脚本，也不自动安装 `compatibility` 中的依赖。

`resources` 在新接口仅用于已有 Document 挂载，本期没有真实资源服务时传空数组；原有 `knowledge_base_ids` 也传空。新接口拒绝通过 `files` 等未知文件字段上传，避免文件被忽略；旧请求请继续使用旧上传接口。

```javascript
const source = {
  name: item.technicalName,      // 前端技术标识 → 后端标准 name
  display_name: item.name,       // 前端实现名称 → 后端展示名
  skill_class_id: item.classId,
  model_tier: item.modelTier,
  system: item.system,
  team: item.team,
  description: item.description,
  instructions: item.instructions,
  version: item.version,
  compatibility: "调用检查脚本需要 Python 3.12+。",
  resources: [],
  knowledge_base_ids: [],
  reference_uploads: [{usage: "生成前读取演示业务规则。"}],
  script_uploads: [{usage: "检查输入时调用 python scripts/check_input.py <输入文件>。"}]
};
const form = new FormData();
form.append("source", JSON.stringify(source));
form.append("reference_files", rulesFile);
form.append("script_files", checkScriptFile);
const response = await fetch(`/skills/${skillId}/builds/upload/entries`, {
  method: "POST", headers: {token: jwtToken}, body: form
});
const result = await response.json();
// 必须按 status 判断成功，不能仅检查 HTTP 200。
```

前端已通过 `src/api/skillClient.ts` 接入真实认证、生成、查询和下载；`src/api/developer.ts` 的调试和审批仍为 mock。本地联调启动及验证结果见 [前后端联调记录](skill-frontend-integration.md)。

缺少说明会报告 `script_uploads[0].usage` 或 `reference_uploads[0].usage`；数量不匹配报告对应说明数组；大小超限报告对应 `script_files[0]` 等文件字段。路径、哈希和同名冲突也会从内部资源序号映射回相应上传入口。失败不会发布最终目录，已暂存的上传文件会被清理。

多文件脚本可通过受校验的内部相对路径保留布局，例如第二个文件的 `target_path: "utils/helpers.py"` 会保存为 `scripts/utils/helpers.py`。省略时沿用原文件名；不接受服务器绝对路径，不解包代码 ZIP，不重新分析和排列 Python 包。

新接口最终仍调用同一生成器，构建清单中的 `source.resources` 保存标准化后的绑定信息，查询、历史及 ZIP 下载使用原有接口。

独立验证新入口映射（不需要数据库）：

```powershell
.\.venv\Scripts\python.exe -m examples.skill_package_demo --scenario entries
```

源数据在 `examples/skill-package/source-entries.json`；真实 HTTP 上传链路另由隔离接口测试验证。

## 旧 multipart 接口示例

样例源与两份资源在 `examples/skill-package/`。`upload_index` 从零开始，按照 `files` 字段顺序对应；每个上传文件都必须至少有一项绑定，禁止默默丢弃未绑定文件。

```javascript
const source = {
  name: "core-case-generator",
  display_name: "核心系统用例生成",
  description: "根据支付需求生成测试用例；适用于支付测试设计。",
  instructions: "读取需求，参考业务规则，按输出模板生成测试用例。",
  compatibility: "", // 没有特定环境要求时可省略
  version: "0.1.0",
  resources: [
    {upload_index: 0, role: "reference", target_path: "business-rules.md", usage: "生成前读取业务规则。"},
    {upload_index: 1, role: "asset", target_path: "testcase-template.json", usage: "按此模板组织输出字段。"}
  ],
  knowledge_base_ids: []
};
const form = new FormData();
form.append("source", JSON.stringify(source));
form.append("files", rulesFile);
form.append("files", templateFile);
const response = await fetch(`/skills/${skillId}/builds/upload`, {
  method: "POST",
  headers: {token: jwtToken},
  body: form
});
const result = await response.json();
if (result.status === "failure") {
  // 将 data.missing_fields 和 data.errors 映射到表单；其他错误展示 message。
  showBuildErrors(result);
} else {
  saveBuildReference(result.data.build_id);
}
```

浏览器提交 FormData 时，让浏览器设置包含 boundary 的 Content-Type。最终构建接口也会检查缺失信息，不依赖前端先调用校验接口。

## 指定目录及加载接口

`.env` 可配置 `SKILL_BUILD_DIR`；默认是项目 `output/skill-builds`。Windows 部署建议配置较短的绝对路径，例如 `D:/skill-builds`，以减少长路径限制的影响。

```text
<SKILL_BUILD_DIR>/<user_id>/<skill_id>/<build_id>/
├── manifest.json
├── package.zip
└── .claude/
    └── skills/
        └── core-case-generator/
            ├── SKILL.md
            ├── references/business-rules.md
            └── assets/testcase-template.json
```

构建成功的 `data` 包括 `build_id`、`skill_id`、`name`、`version`、`files`、`package_sha256`、`workspace_dir`、`skill_directory` 和源表单。ZIP 内是标准的 `<name>/SKILL.md` 目录结构，不包含平台 manifest。

每次构建使用新 UUID，不覆盖已有包。输入校验失败不创建最终构建目录；文件复制、校验或 ZIP 生成失败时清理临时文件。重复请求会产生独立构建，不提供幂等重试键。本模块也未增加引用次数统计。

前端可以通过构建历史接口找回 `build_id`；列表返回简要元信息，实际加载和下载前再验证目录内容。

构建的所属用户和 Skill ID 与当前登录用户核验。后端不接受客户端提供服务器文件路径。既有文档只能从配置上传目录内读取，遵循原有“所有者、公开知识库及管理员”规则。

给调试模块的接入示例：

```python
from applications.agent.services.skill_package_service import SkillPackageService
from services.claude_agent_service import build_base_options

# user 是当前已鉴权用户；skill_id/build_id 来自受控请求。
build = await SkillPackageService().get(skill_id, build_id, user, verify=True)
options = build_base_options(
    skills=[build["name"]],
    output_dir=task_output_directory,
    workspace_dir=build["workspace_dir"],
)
# 运行模块随后使用已有 Agent 会话服务执行。
```

`build_base_options` 新增可选 `workspace_dir` 参数，旧调用方省略时保持原工作区。当前构建目录适合单技能调试；项目公共文件、多技能工作区和输出目录的挂载仍由运行模块负责。不要直接信任浏览器传回的绝对路径，应使用 `skill_id/build_id` 在后端重新解析和验证。

目录型 SDK 加载需有权限访问同一存储卷；如果调试进程在另一容器，要配置共享卷及一致的路径。本版验证了目录内容和接入参数，未执行真实模型或沙箱会话。

## 已实现的校验及范围

- YAML 通过安全序列化生成并重新解析，版本保存为字符串。
- 检查标准技术名、缺失字段、绑定完整性、目标路径和同名/文件目录冲突。
- 检查 `SKILL.md` 正文中的 Markdown 本地链接及图片链接，包括引用式链接；代码块里的示例不会当作真实文件引用。暂不检查任意自然语言、代码块或附属资源内部的路径。
- 2026-10-13老师最新要求及用户确认：单文件最多20MB（20,000,000字节），每次提交最多5个直接上传文件；不设合计20MB限制。知识库展开后的100份实际资源工程上限独立保留。接收与复制逐文件检查，等于上限允许，超限返回字段错误。旧入口也检查上传5个限额；本期不支持Docker镜像上传。
- 脚本仅复制，不执行；原文件保持字节内容。
- 清单和下载读取检查已记录文件的哈希、额外文件及 ZIP 哈希。

不包含已有 Skill ZIP 导入、Docker 镜像处理、自然语言自动补全、独立技能类模板继承、调试执行和审批状态机。`skill_class_id`、团队和系统当前仅记录元信息，不表示已验证归属。接入未来技能类服务时，在资源解析前增加类模板/公共资源适配器。

构建成功不会自动改变 `Skill.is_enabled`。正式运行台仍需接入审批校验；当前仓库的布尔开关不能代表完整审批流程。删除 Skill 后接口不再允许读取其构建，磁盘历史文件的定期清理策略待运维统一配置。

## 测试及本地验证

第三步提供不需要业务数据库、登录配置或前端的独立演示。在仓库根目录、已安装相关 Python 依赖的虚拟环境中执行：

```powershell
.\.venv\Scripts\python.exe -m examples.skill_package_demo --scenario basic
.\.venv\Scripts\python.exe -m examples.skill_package_demo --scenario reference
.\.venv\Scripts\python.exe -m examples.skill_package_demo --scenario script
```

三种场景分别使用 `examples/skill-package/source-basic.json`、`source-reference.json`、`source-script.json`。脚本打印构建 ID、Skill 目录、ZIP 路径和文件列表，并重新验证文件/ZIP 哈希与正文链接。每次运行生成新构建；默认输出在已被 Git 忽略的 `output/skill-builds/`，可用 `--output-dir` 指定其他输出根目录。

演示固定身份 `user_id=1`、`skill_id=skill-demo` 仅用于本地展示，不能作为真实接口身份。脚本场景仅复制 `check_input.py`，不执行它，也不代表调试运行已接通。输入检查规则在示例中明确标注为演示，不新增平台统一输入要求。

核心生成器导入时不再提前加载数据库模型和项目配置；原来的 `from applications.agent import Skill, McpServer` 仍可按需访问模型。接口层继续使用原有鉴权和数据库。

本地相关回归命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

在已安装项目依赖的开发环境中，额外安装测试工具后运行：

```powershell
uv pip install pytest pytest-asyncio
uv run --no-sync python -m pytest tests -q
```

测试使用 SQLite 内存数据库、实际 JWT 验证和 FastAPI 请求链路，不连接团队 MySQL、Redis 或模型服务。覆盖字段报告、Unicode/YAML、字节保留、资源权限、上传与下载、文件哈希变化、越界路径、大小限制、失败清理、并发构建和旧接口兼容。

实现验证时安装了项目对应的 FastAPI 0.136.3、Starlette 1.2.1、Pydantic 2.13.4、Tortoise ORM 0.23.0、Claude Agent SDK 0.2.96 等模块所需依赖，并验证 SDK 目录参数和旧调用兼容；没有为了这项功能安装全部向量与模型推理依赖。启动完整后端仍按项目原有环境配置执行。

正式联调还需要团队的 MySQL/Redis 配置、现有登录账号，以及运行模块的目录挂载配置。不要把隔离测试的临时配置用于生产。
