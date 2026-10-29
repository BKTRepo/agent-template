---
name: online-debug-runner
description: 开发者中心在线调试的固定容器入口。它不提供业务能力，只将页面传入的动态 Skill 定义、对话和只读资源交给模型执行。
---

# 在线调试容器入口

此目录由后端发布和只读挂载，不从用户输入复制 Skill 文件。实际业务定义始终来自 `/input/online-debug-request.json` 中的 `skill_definition` 字段。
