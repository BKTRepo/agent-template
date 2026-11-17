# 智能测试平台 UAT 离线部署

交付包适用于 Linux amd64。一个 tar 内含八个独立镜像：前后端应用、CCR 3.1.3、MySQL 8.0、Redis 7.4、Milvus 2.6.4、etcd、MinIO 和 Gotenberg/LibreOffice。etcd 和 MinIO 分别提供 Milvus 的元数据和对象存储。

在安装了 Docker Engine 和 Compose v2 的主机上进入交付目录：

```sh
sha256sum -c SHA256SUMS
docker load -i keenrobot-platform-full-uat.tar
test -f .env || cp .env.example .env
chmod 600 .env
```

本机交付的 `.env` 已配置内网模型网关及平台、数据库、CCR 的凭据。按需设置 `VLM_API_BASE`、`VLM_API_KEY` 和 `VLM_MODEL` 以启用图片模型。重新用模板部署时，填写 `INTRANET_MODEL_API_KEY`，并用 `openssl rand -hex 32` 为平台和 CCR 的各个密钥或密码分别生成随机值。正式应用目录启用时，将 `APPLICATION_CATALOG_MODE` 改为 `remote` 并填写地址。

```sh
docker compose config --quiet
docker compose up -d
docker compose ps -a
```

`database-init` 首次启动会在自带的空 MySQL 中创建平台表、字典和初始管理员。它执行完显示退出码 0。默认用 `.env` 中的管理员账号登录，前端访问主机的 3000 端口。数据库和向量服务通过 Compose 内部网络连接。应用文件使用 `PLATFORM_DATA_DIR` 指定的 Docker 宿主机目录。

内网客户端通过部署机的 TCP 3308 连接 MySQL，容器内仍使用 `mysql:3306`。连接账号、密码和库名取自 `.env` 的 `DATABASE_USERNAME`、`DATABASE_PASSWORD` 和 `DATABASE_NAME`。

所有持久化数据默认位于 Docker 宿主机的 `/zdhgj/keenrobo`。应用文件使用 `PLATFORM_DATA_DIR=/zdhgj/keenrobo/app`，数据库和存储使用 `DATABASE_DATA_ROOT=/zdhgj/keenrobo` 下的 `mysql`、`redis`、`milvus`、`etcd`、`minio` 和 `chroma` 子目录。部署时确保 Docker 可以创建和读写这些目录。常规停机使用 `docker compose down`，数据保留在宿主机目录。

已用旧版 Compose 部署的实例，先停机并迁移数据。应用文件的旧默认目录为 `/srv/keenrobot/data`，早期版本的 Chroma 位于该目录下的 `chroma` 子目录。直接切换配置会使用新目录中的数据。

悬浮窗原始产出物和用例分组缓存保存在 `PLATFORM_DATA_DIR` 下的 `chat-results`。旧版后端如果尚未挂载该目录，先停止后端，并在重建前从原容器的 `/app/applications/chat/chat_results` 复制完整目录内容到宿主机的 `chat-results`。

已有数据库升级技能资源上传功能时，先执行 [上传人范围的唯一索引迁移](../docs/migrations/20261117-skill-upload-owner-dedup.sql)，再启动新版后端。迁移保留现有资源编号和技能绑定，可重复执行。

交付包包含新建数据库所需的表结构与基础字典。现有 UAT 业务数据、知识库文件和向量索引若需要迁移，请另行备份和恢复。

Word（DOCX）转 PDF 服务随 Compose 启动，默认地址为 `http://document-preview:3000`，仅后端可从 Compose 内部网络访问。产出物中的 DOCX 段落编辑、XLSX 预览和单元格编辑、文本与代码编辑，以及 PDF.js 预览脚本和资源已随应用镜像提供，浏览器无需访问外部 CDN。

悬浮对话和在线调试使用 Anthropic 协议访问 `http://ccr:3456`，CCR 转成 OpenAI 兼容请求发往内网网关。浏览器访问 `http://部署机内网IP:3458/?ccr_web_token=<CCR_WEB_AUTH_TOKEN>` 打开 CCR 管理页。3456 仅在容器网络内提供服务。CCR 的配置和界面修改保存在 `/zdhgj/keenrobo/ccr`。首次启动会从 `.env` 初始化模型源及凭据。已有部署变更上游时需同时更新 CCR 管理页面和 `.env`，使知识库和 CCR 使用同一配置。

知识库的文本模型和向量嵌入直接使用 `INTRANET_OPENAI_BASE_URL`，重排使用该地址下的 `/rerank`。默认网关是 `http://10.240.192.142:30003/v1`，默认模型分别为 `deepseek-v4-flash-local-thinkl`、`bge-m3` 和 `bge-rerank-v2-m3`。

仅升级代码时，在打包机使用 `docker save -o keenrobot-platform-code.tar keenrobot-platform:<新标签>` 导出前后端应用镜像。部署机加载该 tar 后，将 `.env` 的 `PLATFORM_IMAGE` 改为新标签，然后在交付目录运行：

```sh
docker compose up -d --no-deps backend web knowledge-parse knowledge-delete scheduler
```

新启动的 Skill 沙箱也使用该应用镜像标签。数据库、文档转换和 CCR 沿用原有镜像及数据目录。
