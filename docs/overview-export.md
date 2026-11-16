# 总览指标明细直接下载 Excel

八张指标卡片的“明细”按钮直接下载 `.xlsx`，不再打开明细预览弹窗。

接口：`GET /overview/metric-export?metric=...`，沿用平台请求头 token 鉴权和原明细接口的数据权限。期间指标还需传 `start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`；累计指标不受日期影响。

支持指标：`connected_users`、`online_skills`、`skill_calls`、`knowledge_mounts`、`active_users`、`test_artifacts`、`new_skills`、`new_knowledge_bases`。

复用现有总览事实源，导出全部匹配明细，超过20条仍全部导出。中文列名与原明细一致；技能调用明细仅含技能名称、操作人工号、调用时间。用户部门沿用现有目录提供器。缺失字段保持空白，数字0保持0；工号按文本保存，时间按北京时间保存，防止用户文本被Excel识别为公式。空结果仍导出表头。

不写业务数据库、不创建业务表。旧分页 JSON 明细接口继续保留。日期校验、权限或下载失败时页面显示错误，不下载错误JSON。超过Excel单表最大数据行数（1,048,575行）明确拒绝，不静默截断。
