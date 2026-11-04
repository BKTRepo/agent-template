---
title: 知识库创建与抽象类批量挂载
status: implemented-local
last_updated: 2026-11-04
---

# 知识库创建与抽象类批量挂载

dev-zyl-前端 已合并 zdhgj-znfw-uat-fronted（6072d5e）。知识库管理改用真实后端，取消本地模拟保存和定时完成，没有新增独立文件管理页面。

## 创建与处理

1. 每个新文件通过 multipart file 调用 POST /api/convert，请求头携带平台 token，支持 PDF、DOCX、XLSX、MD、TXT。
2. 取得 data.job_id 后，POST /knowledge-bases/create 或 /save 保存元数据及 conversion_job_ids。编辑传 expected_version、retained_document_ids，同名替换等新文件走保存接口 files，后台仍进入同一处理流水线。
3. GET /api/convert/status?job_id=... 与 GET /knowledge-bases/detail?kb_id=... 查询实际阶段。任务 complete 且库真实 completed 才允许挂载；页面展示逐文档阶段和完成数量。
4. 失败 POST /api/convert/retry，JSON 为原 job_id。服务端关联知识库时不重复解析或入库。
5. 文件、历史、引用数来自后端；store 仅作缓存，切换身份清空，不混入示例 ID。

## 挂载

弹窗按抽象类多选，加载本人技能的全部分页并选择这些类下本人全部实现。搜索只定位抽象类，不截取类下实现子集。

逐个复用 updateDeveloperSkill，实际接口 POST /skills/developer/save-skill。保留完整表单、修订号及原资源，合并新知识库，绑定表由原保存逻辑维护。成功、已存在、失败分别提示；再次提交刷新记录，已成功的跳过。

当前保存接口生成新版本并转为草稿，需重新构建、调试和发布。前端不另写资源关系或伪造保存成功。

## 协议及验证

新增/修改调用只使用 GET、POST；GET 用 URLSearchParams，POST 业务编号在 JSON/form-data。/api 与技能/知识库使用同一后端代理和 token 策略。

```powershell
npm test
npm run build
```

接口回归及浏览器检查使用显式测试响应，不代表真实模型、Worker、Milvus 端到端验收。后端需同步部署新 GET/POST 路由，并按知识处理迁移文档准备环境。
