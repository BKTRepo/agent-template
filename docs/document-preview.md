---
title: 知识库邮箱式附件预览
status: implemented
last_updated: 2026-11-06
---

复用知识库文件及登录鉴权，不新增数据库表，不依赖解析或向量入库完成。
支持PDF、DOCX、XLSX、Markdown、TXT，保留原文件下载；预览工具栏不提供“查看解析内容”，Excel不展示底部公式说明。
预览弹窗支持附件切换、全屏、缩放；PDF分页，Excel工作表和行列分页。

## 部署

`docker compose -f deploy/compose.document-preview.yaml up -d` 启动内部Gotenberg/LibreOffice。
仅绑定本机3001端口，后端配置 `DOCUMENT_PREVIEW_CONVERTER_URL=http://127.0.0.1:3001`。
后端也在Docker中时改为内部可达地址。转换服务不接收平台token、不对公网开放。
镜像默认关闭宏执行；配置拒绝Office文档发起内网和公网请求。
转换服务不可用时，Word显示重试提示，仍能下载原文件。

`DOCUMENT_PREVIEW_CACHE_DIR` 默认output/knowledge_previews，转换超时默认60秒。
PDF缓存按原件路径、代次、内容哈希、大小及修改时间隔离，跨进程文件锁避免重复转换。
旧缓存不是业务原件，可由运维在低峰期按修改时间清理目录中的过期PDF。
前端锁定pdfjs-dist并打包worker、字体、CMap和WASM，内网预览不依赖CDN。

## 接口

所有接口为GET，业务编号在查询字符串，平台token只放请求头。

| 路径 | 参数 | 返回 |
|---|---|---|
| /knowledge-bases/documents/preview | kb_id, doc_id | 保留markdown等原字段，追加format、viewer、sheets、generation |
| /knowledge-bases/documents/preview-pdf | kb_id, doc_id, generation | 原PDF或Word转换PDF字节 |
| /knowledge-bases/documents/preview-sheet | kb_id, doc_id, generation, sheet_index, offset, limit, column_offset, column_limit | 分页单元格、基础样式和合并范围 |
| /knowledge-bases/documents/download | kb_id, doc_id, 可选generation | 原文件，兼容旧调用 |

Excel每页最多200行、100列，前端默认100行50列。代次不一致返回409，重新加载预览即可。
每次请求包括缓存命中均检查权限，转换或读取后再次检查权限和代次。
缓存路径不返回前端，下载不依赖公开文件URL。

## 展示边界

DOCX按LibreOffice转换PDF的排版显示，字体缺失时可能替换字形，复杂域不保证与Microsoft Word完全一致。
XLSX小型工作簿展示基础样式和合并单元格，大型工作簿流式分页展示数据。
公式只显示表达式，不执行宏和外部链接；隐藏工作表不开放预览。
Office文件解压内容超过128MB时仅限制在线预览，不改变已有上传规则，仍可下载原文件。
TXT/Markdown预览前512KB并提示可下载完整内容；Markdown不执行HTML或加载外部图片。
旧版DOC、XLS及在线编辑不在本次范围。

## 验证

tests/test_document_preview.py 覆盖权限、代次、路径范围、Excel分页/样式/合并/公式、转换缓存和并发。
真实DOCX转PDF验收需启动内部转换服务，转换替身的测试不能代替真实转换测试。
