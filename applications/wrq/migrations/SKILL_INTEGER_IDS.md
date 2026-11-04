# 技能整数编号迁移

2026-11-04：`keenrobot_skills.id` 从字符串改为 signed `INT(11) AUTO_INCREMENT`，六张关系表的 `skill_id` 同步改为 signed `INT(11)`。开发者中心表及 MCP 记录中已有 INT/BIGINT 整数列统一为 signed INT，容量字节数字段保留 BIGINT；状态布尔值、外部任务编号和构建摘要保留各自语义。

执行前停止技能写入，默认只检查，显式 `--apply` 才执行：

```powershell
.\.venv\Scripts\python.exe -m applications.wrq.migrations.skill_integer_ids
.\.venv\Scripts\python.exe -m applications.wrq.migrations.skill_integer_ids --apply
```

执行时检查所有 skill_id 引用、无主技能引用及数值范围；在 `.tmp/skill-integer-migration/<时间>/backup.json` 保存原始行、列元数据和新旧编号映射，再在同一事务内改写技能与关系编号。DDL 最后执行，MySQL DDL 不具备跨语句事务回滚能力，中断后可重跑完成剩余列类型修改。不要用隐式字符串转整数直接 ALTER 原始编号。

`legacy_id` 是唯一、可空的历史编号，只为核验不可变历史构建包。现有包不重写，路径、摘要、正文保持原样；服务端先校验当前用户与版本归属，再用已登记版本的包路径和历史编号核验原包，接口返回新整数技能编号。新建技能不填写 `legacy_id`。

迁移校验应比较关系行数、无主引用和备份原值，修改时间也应保持。MySQL 8 的 information_schema 可能显示 `int`，这是省略显示宽度后的 `INT(11)`，范围为 -2147483648～2147483647。

前端收到数字编号后在页面状态中转为字符串以兼容组件键；发送 JSON 时转回数字。任务状态和关联编号比较使用规范化后的字符串。
