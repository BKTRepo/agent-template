---
title: 资产管理接入与验收
status: implemented
last_updated: 2026-11-09
---

资产管理复用 `keenrobot_skill_classes`，概览按可见资产统计总数及各大类数量。列表按创建时间和编号稳定分页，每页 10 项，支持资产名称及创建人姓名或账号搜索。创建人才能移入回收站、恢复和彻底删除。

## 部署

- 显式应用 `docs/migrations/20261109-asset-management.sql`，先确认目标库已有 `keenrobot_skill_classes`。迁移新增 `keenrobot_assets` 和 `keenrobot_asset_files`。
- 归档文件放在 `OUTPUT_DIR/assets`。容器部署时把 `OUTPUT_DIR` 挂到持久化存储，多实例需要共享同一份文件。
- `.env` 配置 `ASSET_RECYCLE_RETENTION_DAYS=30`。恢复截止时间按回收时间加配置天数计算，修改后重启服务生效。到期后不可恢复，后台启动时和每 5 分钟清理过期记录及归档原件。
- Word 预览复用 `DOCUMENT_PREVIEW_CONVERTER_URL`。Excel 工作表、PDF 及脚本均读取归档文件。测试案例使用产出物已有的工作簿解析及导图分组服务。
- 联调使用 `ASSISTANT_ARTIFACT_MOCK_DIR` 和前端 `VITE_ASSISTANT_ARTIFACT_MOCK=true`。正式接入替换 `applications/conversation/services/asset_source.py` 的来源适配，复用同事产出物 ID、鉴权及内容读取契约。当前来源 ID 按不透明字符串处理。

## 接口

路径统一以 `/api/assets` 开头。平台 token 放请求头，GET 参数放查询字符串，POST 参数放 JSON 请求体。

| 方法 | 路径 | 参数与行为 |
| --- | --- | --- |
| GET | `/overview` | 资产总数、大类计数、本人回收站数量和当前回收期限 |
| GET | `/list` | `page`、`search`、`skill_classes_id`、`sort`，服务端每页最多 10 条 |
| GET | `/detail` | `asset_id`，返回资产与附件 |
| GET | `/source-status` | `artifact_id`，返回本人来源纳入或回收状态 |
| POST | `/create` | `artifact_id`、`base_hash`、`name`、`skill_classes_id`、`application_identify`、`visibility`，归档原文件快照，同来源幂等 |
| GET | `/preview`、`/preview-pdf`、`/download` | `asset_id`、`file_id`，每次检查资产权限及附件归属 |
| GET | `/preview-sheet` | `asset_id`、`file_id`、`sheet_index`、`offset`、`column_offset`，每次最多 100 行和 50 列 |
| POST | `/export` | `asset_ids`，下载所选资产 CSV 清单 |
| GET | `/recycle-bin` | `page`，返回本人可恢复资产及截止时间 |
| POST | `/move-to-recycle-bin`、`/restore`、`/delete-recycled` | `asset_ids`，限创建人操作，彻底删除限回收站资产 |

悬浮窗覆盖保存只更新原产出物。资产预览与下载读取纳入时的快照。

## 本地验收

通过隔离 SQLite 和真实文件测试 10+1 分页、权限隔离、重复纳入、快照保留、原文件下载、恢复、彻底删除和过期清理。浏览器使用配置为 2 天的验收环境，验证回收提示与后台一致。DOCX 使用本机 LibreOffice 实际转换为 PDF，XLSX、PDF、脚本和测试案例导图在浏览器中打开并验证。
