# 开发者中心在线调试沙箱

在线调试不使用 Celery：接口先在 MySQL 创建任务记录并返回 `run_id`，同一后端进程中的后台任务再同步执行 Docker 沙箱和模型。前端关闭弹窗不会取消任务；再次打开时可按 `skill_id` 查询最近一条任务。

生成成功后的 Excel 保存在：

```text
applications/zhaoyunlong/sandbox_results/
└── runs/
    └── {run_id}/
        ├── 调试结果文档.xlsx
        └── 或多个按 Skill 结果命名的 .xlsx 文件
```

容器、上传内容和 Markdown 中间产物会清理，仅短期保留最终 Excel。默认保留 24 小时，可用 `ZHAOYUNLONG_DEBUG_RESULT_RETENTION_SECONDS` 配置为 1 小时至 7 天。后端启动后会使用 APScheduler 在每天北京时间凌晨 3 点删除过期结果目录及对应的 `keenrobot_online_debug_runs` 表记录；创建任务和下载文档时也会继续执行一次兜底的文件清理。

模型执行默认不设时长上限，容器会等待模型自然结束。若生产运维需要兜底保护，可设置 `ZHAOYUNLONG_SANDBOX_TIMEOUT_SECONDS` 为正数秒数；设置为 `0` 或不设置时表示无限等待。

## 接口

所有接口都需要在请求头传入登录令牌：`token: <access_token>`。

### 1. 创建在线调试任务

`POST /realtime-test-case-gen/runs`

请求类型为 `multipart/form-data`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `skill_id` | 文本 | 是 | 当前被调试技能的业务标识。 |
| `skill_definition` | 文本 | 是 | Markdown 格式的 Skill 定义。 |
| `conversation_input` | 文本 | 否 | 本次自然语言调试诉求。 |
| `documents` | 文件数组 | 否 | 需求文档，最多 10 个。 |
| `mounted_resources` | 文件数组 | 否 | 只读挂载资源，最多 20 个。 |

文件字段仅支持 PDF、DOCX、Markdown、TXT、XLSX、JSON。接口立即返回 `202` 和任务编号：

```json
{
  "run_id": "e2b8b90227cb4cd4a45112a8d5261c5f",
  "skill_id": "test-case-generator",
  "debugger": "当前登录用户的姓名",
  "status": "queued"
}
```

### 2. 查询一次调试任务

`GET /realtime-test-case-gen/runs/{run_id}`

前端在 `queued` 或 `running` 时每两秒调用一次。任务完成后只返回 `documents` 文件数组；单结果数组长度为 1。每个 `documents[].download_url` 都指向同一个下载接口，只是 `filename` 参数不同；失败时返回 `error_message`。

### 3. 查询技能最近一次调试任务

`GET /realtime-test-case-gen/skills/{skill_id}/latest-run`

调试弹窗重新打开时调用。后端按 `skill_id` 返回最新创建的任务，包括仍在运行中的任务。

### 4. 下载调试结果文档

`GET /realtime-test-case-gen/runs/{run_id}/document`

仅 `completed` 状态可下载，返回首个 Excel 文件。任务未完成、结果过期、文件不存在或无权访问时不会返回文件。

当 Skill 生成多个结果时，前端遍历 `documents` 数组，并使用每条记录的 `download_url` 下载对应文件。例如：

```text
GET /realtime-test-case-gen/runs/{run_id}/document?filename=登录功能.xlsx
```

## 本地联调

1. 启动 MySQL：

   ```bash
   cd /Users/superxiaozhao/PythonProject/agent-template
   docker compose up -d mysql
   ```

2. 构建一次沙箱镜像：

   ```bash
   docker build -f applications/zhaoyunlong/sandbox/Dockerfile -t test-case-sandbox:local .
   ```

3. 安装新增依赖并执行数据库迁移：

   ```bash
   /Users/superxiaozhao/miniconda3/envs/py3.12/bin/python -m pip install -e .
   PYTHONPATH=. /Users/superxiaozhao/miniconda3/envs/py3.12/bin/python -m aerich upgrade
   ```

4. 启动后端：

   ```bash
   /Users/superxiaozhao/miniconda3/envs/py3.12/bin/python backend_main.py
   ```

5. 使用示例脚本创建任务、等待完成并下载全部 Excel：

   ```bash
   /Users/superxiaozhao/miniconda3/envs/py3.12/bin/python \
     applications/zhaoyunlong/sandbox/call_online_debug.py \
     --token '登录接口返回的access_token' \
     --skill-id 'test-case-generator' \
     --output-dir ./downloads
   ```
