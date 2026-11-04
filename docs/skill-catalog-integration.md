---
title: 技能中心接入与字段变更
status: 技能统计与知识库整数编号均已通过SSL迁移并复核
last_updated: 2026-11-04
---

# 技能中心

2026-11-04后续合并dev-wrq：新构建中的知识库改为运行时MCP检索，不再打包原文件，直接上传资源仍打包。目录已发布版本测试接入同一MCP授权及执行证据校验；上下文与原有任务/关联/计数同事务，保留重复提交保护。权限策略统一到knowledge_permissions，原隔离函数作为兼容入口。部署要求及63项后端/55项前端合并回归见 [MCP接入](../applications/wrq/KNOWLEDGE_MCP.md)。历史构建仍按原件校验读取，不重写旧ZIP。

技能中心与开发者中心共用 `keenrobot_skill_classes`、`keenrobot_skills`、`keenrobot_skill_versions`、`keenrobot_skill_forms`、`keenrobot_skill_resource_bindings`。不创建另一套技能实现、版本或资源关系表。大类的字段直接加在现有分类表，不新建大类详情表。

## 数据与可见性

- 已认证平台用户可以浏览当前状态 ONLINE/OFFLINE 且存在 published_version_id 的实现，目录跨创建人展示。开发者中心写权限仍限本人。
- 详情、名称搜索、大类和应用筛选均使用 published_version_id 对应的发布表单，禁止用 current_version_id 对应的新草稿替代。
- 草稿、调试中、调试成功、调试失败、软删除记录不进入目录。沿用现有保存生命周期：编辑会进入 DRAFT，重新上线前该实现不再进入目录。
- 下线实现保留发布版详情与 ZIP 下载，在线测试只允许 ONLINE 且大类已启用。仅有发布指针却缺失表单/构建原件时返回明确错误，不补演示内容。
- 维护人采用 update_user_login_name，空值回退 create_user_login_name。页面展示工号，不把当前浏览者的姓名填入他人技能。
- 数据库完成过滤、计数和分页；每页20条实现，分组计数明确为“本页”，与目录总数区分。

## 大类字段与迁移

按用户确认，仅扩展 `keenrobot_skill_classes`：

| 字段 | MySQL类型 | 用途 |
| --- | --- | --- |
| description | TEXT NULL | 能力描述；历史空值显示暂无描述 |
| input_schema | JSON NULL | 统一输入 JSON Schema |
| output_schema | JSON NULL | 统一输出 JSON Schema |
| template | LONGTEXT NULL | Skill模板原文及下载 |

没有配置的 Schema/模板显示“未配置”，模板下载禁用。未写入原型示例数据。本期不增加分类维护页面，已有分类编号、名称和启用状态继续复用。

2026-11-04按用户提供的目标连接，通过SSL完成大类四列和技能统计两列的新增并复核，Ssl_cipher为TLS_AES_256_GCM_SHA384。变更前DDL备份在忽略目录 `.tmp/skill-counter-backups/`；未存储连接密码。脚本 `applications/wrq/migrations/add_skill_counters_20261104.py` 从进程环境或本机.env读取连接，强制SSL，默认只规划，--apply才添加缺失列，不创建知识库表、不改既有主键。未提供私有CA时只验证加密会话，不声称已验证服务端证书身份。

## 实现统计与整数编号

`keenrobot_skills.call_count`、`download_count` 均为 BIGINT NOT NULL DEFAULT 0，按实现跨版本累计，历史值从本次上线起计数，不回填伪数据。

- call_count：技能中心实际接受的在线测试任务数，最终失败仍计一次；开发者中心的私人调试和未来正式执行入口尚未纳入这个计数。创建任务、固定版本关联、原子加一在同一事务；request_id作为run_id，重复提交同一编号返回原任务，不重新执行、不重复计数。
- download_count：成功生成并准备返回一次完整发布ZIP加一。预览、资源原件、类模板、结果文档及失败请求不计；不能证明客户端最终保存成功。
- 统计更新只修改计数字段，不改更新时间、维护人、版本、状态。业务save/offline/publish/build/debug登记均指定update_fields；Skill.save兼容旧整行调用时也排除统计字段，防止旧对象覆盖并发计数。
- 按实际数据库同步Skill.id为自增INT，版本/关联/发布/调试的skill_id及资源source_id为INT，保留已有legacy_id。旧构建按已保存路径和legacy_id校验后读取，不重新生成或改写旧包。前端统一将数字ID转换为字符串供选择与比较，接口按整数校验。
- 用户确认其他任务已创建知识库七张表，并进一步授权将代码和数据库均改为INT自增。已确认七表全部为空且没有知识库技能绑定；通过SSL执行 `applications/knowledge_base/migrations/align_empty_integer_ids_20261104.py --apply`，将七个主键和知识库/文档/分块关联列改为INT，恢复原文档外键及删除/更新规则。原User BIGINT、转换job_id和Celery任务编号不改。变更前DDL及逐步日志在忽略目录 `.tmp/knowledge-id-backups/`；空表方案遇到非空表或额外外键会拒绝，不对历史UUID做隐式转换。参考新建表SQL见 `docs/migrations/20261104-knowledge-integer-schema.sql`。

## GET/POST契约

平台 token 放请求头，以下查询全部 GET，业务参数均在查询字符串；响应统一检查 HTTP 状态与 status=success。

| 路径（前缀 /skills/catalog） | 查询参数 | 返回 |
| --- | --- | --- |
| /get-metadata | 无 | 全量分类、门户应用和目录维护人 |
| /get-class | class_id | 大类描述、Schema和模板 |
| /list-skills | name、class_id、application、maintainer、page、page_size | items、total、page、page_size、pages |
| /get-skill | skill_id | 发布表单、资源关系、Markdown、固定发布构建ID |
| /get-build | skill_id、build_id | 经校验的发布构建和资源清单，不返回服务器目录 |
| /download-skill | skill_id、build_id | 发布版完整ZIP |
| /download-resource | skill_id、build_id、path | 清单内原件字节；只用于已上线版本的在线测试 |

构建ID必须恰好匹配当前发布指针，不能指定任意历史或私人草稿构建。原件必须在构建清单中，路径不用于本机文件系统寻址。包读取复用既有构建服务和完整性检查，版本呈现复用既有发布包转换；并未放宽原开发者私人下载接口。

## 在线测试

新增 POST `/skills/catalog/create-test-run`，multipart包含source JSON（skill_id整数、build_id、request_id为32位小写十六进制、conversation_input）及可选documents。前端不提交Skill定义或挂载资源，后端从校验完整性的发布ZIP读取固定定义和原件，再复用同事的OnlineDebugRunService执行器。任务/版本关联/计数同事务落库，提交后调度任务，避免后台任务继承未提交事务。轮询、结果下载继续沿用现有沙箱合同；未修改同事沙箱执行代码或接口路径，只按用户要求同步其模型的既有整数列。

目录测试不调用开发者的 register-debug-run、save-skill 或 publish-skill，不改变技能状态、修订号或上线资格。任务结果由既有沙箱表维护；版本关联复用keenrobot_skill_debug_runs，创建关联不更改技能状态、修订号或last_debug_run_id。为避免误把 latest-run 当成当前发布版，本轮目录不自动恢复未知构建的历史任务。生产模型和 Docker 沙箱是否可用仍需目标环境联调。

## 验证

- `tests/test_skill_catalog_flow.py`：真实SQLite和HTTP，验证跨创建人发布目录、私有草稿不泄露、筛选分页、类字段、ZIP原件、构建越权/路径拒绝、下线/停用限制和鉴权。
- 统计事务、幂等、25次并发累加与旧对象save、生命周期、历史构建、目录、知识库和包引擎定向回归合计60项通过。
- 前端55项回归及正式构建通过；浏览器使用显式测试响应检查搜索、展开收起、详情、模板和ZIP下载、下线禁用、在线测试失败提示，页面异常为0。
- 已通过SSL完成用户授权的技能加列及既有七张空知识库表整数编号迁移；没有重复建表，未运行目标环境真实模型/Milvus/Docker任务。
