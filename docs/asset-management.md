---
title: 资产管理接入与验收
status: implemented
last_updated: 2026-11-27
---

资产管理复用 `keenrobot_skill_classes`，概览展示“全部资产”和七个测试阶段，按可见且未回收的资产统计数量。同阶段下多个技能大类的资产合并计数，零资产阶段也展示；卡片点击后按阶段筛选，列表中的原“资产类型”列更名为“技能大类”，继续展示所选大类名称。列表按创建时间和编号稳定分页，每页 10 项，支持资产名称及创建人姓名或账号搜索。创建人才能移入回收站、恢复和彻底删除。移入回收站只支持逐条操作：仅显示每行操作按钮，确认时展示资产名称；多选工具栏保留批量导出，不提供批量移入。回收站现有恢复、彻底删除能力保持不变。

从悬浮窗纳入产出物时，用户选择已发布的技能大类，测试阶段自动由该大类的发布快照关联，只读展示，不由客户端填写或提交。资产继续只保存 `skill_classes_id`，无需新增阶段列或刷历史数据；归档后列表与阶段统计自动刷新。大类未重新发布时仍按原发布名称及阶段展示、筛选和计数，重新发布后一起切换。历史阶段为空或阶段字典已缺失的资产仍计入“全部资产”，不强行归入任一阶段，通过 `unassigned_count` 提示；已删除大类的历史资产也按保留的发布快照归类。

专项回归执行 `python scripts/test-asset-stages.py`，使用临时 SQLite 和模拟鉴权依赖，不连接业务数据库或 Redis。前端对应执行 `node scripts/test-assets.mjs`。

## 部署

- 显式应用 `docs/migrations/20261109-asset-management.sql`，先确认目标库已有 `keenrobot_skill_classes`。迁移新增 `keenrobot_assets` 和 `keenrobot_asset_files`。
- 归档文件放在 `OUTPUT_DIR/assets`。容器部署时把 `OUTPUT_DIR` 挂到持久化存储，多实例需要共享同一份文件。
- `.env` 配置 `ASSET_RECYCLE_RETENTION_DAYS=30`。恢复截止时间按回收时间加配置天数计算，修改后重启服务生效。到期后不可恢复，后台启动时和每 5 分钟清理过期记录及归档原件。
- Word 预览复用 `DOCUMENT_PREVIEW_CONVERTER_URL`。Excel 工作表、PDF 及脚本均读取归档文件。测试案例使用产出物已有的工作簿解析及导图分组服务。
- 正式来源已接通 `ChatArtifact`，通过本人当前会话及成功任务验证读取原件；不增加 `chat_artifacts` 字段。样例只在显式配置 mock 目录和前端开关后可用。详见 [集成契约](assistant-integration.md)。

## 接口

路径统一以 `/api/assets` 开头。平台 token 放请求头，GET 参数放查询字符串，POST 参数放 JSON 请求体。

| 方法 | 路径 | 参数与行为 |
| --- | --- | --- |
| GET | `/overview` | `total`、七阶段 `test_stages:[{id,code,name,count}]`、`unassigned_count`、本人回收站数量和当前回收期限；保留 `classes` 兼容旧调用方 |
| GET | `/list` | `page`、`search`、`test_stage_id`（正整数阶段 ID）、`skill_classes_id`、`sort`；阶段与大类条件取交集，服务端每页最多 10 条 |
| GET | `/detail` | `asset_id`，返回资产与附件 |
| GET | `/source-status` | `artifact_id`，返回本人来源纳入或回收状态 |
| POST | `/create` | `artifact_id`、`base_hash`、`name`、`skill_classes_id`、`application_identify`、`visibility`，归档原文件快照，同来源幂等 |
| GET | `/preview`、`/preview-pdf`、`/download` | `asset_id`、`file_id`，每次检查资产权限及附件归属 |
| GET | `/preview-sheet` | `asset_id`、`file_id`、`sheet_index`、`offset`、`column_offset`，每次最多 100 行和 50 列 |
| POST | `/export` | `asset_ids`，下载所选资产原文件 ZIP，文件直接平铺在压缩包根目录，不添加资产编号文件夹或文件名前缀；同名文件自动加 `(2)`、`(3)` 等后缀（保留扩展名，忽略大小写判断重名），校验全部权限，保留文件字节与格式 |
| GET | `/recycle-bin` | `page`，返回本人可恢复资产及截止时间 |
| POST | `/move-to-recycle-bin` | `asset_ids` 数组必须恰好1个正整数，限创建人操作；接口及业务层拒绝批量移入 |
| POST | `/restore`、`/delete-recycled` | `asset_ids`，限创建人操作，彻底删除限回收站资产 |

已纳入资产管理的测试案例提供思维导图、用例列表和 Excel 原表三种只读视图。`/preview` 返回 `viewer: "case"`、`case_artifact` 和 `sheets`，原表通过 `/preview-sheet` 读取。预览和下载使用归档副本，通过原产出物保存时选择「同步修改」可更新该副本。

## 本地验收

通过隔离 SQLite 和真实文件测试 10+1 分页、权限隔离、重复纳入、快照保留、原文件下载、恢复、彻底删除和过期清理。浏览器使用配置为 2 天的验收环境，验证回收提示与后台一致。DOCX 使用本机 LibreOffice 实际转换为 PDF，XLSX、PDF、脚本和测试案例导图在浏览器中打开并验证。
