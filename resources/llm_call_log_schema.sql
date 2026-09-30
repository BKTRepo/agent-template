-- LLM 调用统计表建表 SQL（由本地库 SHOW CREATE TABLE 导出, 与模型定义一致）
-- 服务器执行: mysql -u<user> -p <db> < llm_call_log_schema.sql
CREATE TABLE IF NOT EXISTS `llm_call_log` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
  `model` varchar(128) NOT NULL COMMENT '模型名',
  `scene` varchar(64) DEFAULT NULL COMMENT '调用场景(预留列, 当前恒为空; 后续可在调用点补传以区分最终回答/术语抽取/查询改写)',
  `stream` tinyint(1) NOT NULL COMMENT '是否流式调用',
  `success` tinyint(1) NOT NULL COMMENT '调用是否成功',
  `error_message` longtext COMMENT '失败时的错误摘要',
  `start_at` datetime(6) NOT NULL COMMENT '调用开始时间',
  `end_at` datetime(6) DEFAULT NULL COMMENT '调用结束时间',
  `total_ms` int DEFAULT NULL COMMENT '总耗时(毫秒)',
  `first_token_ms` int DEFAULT NULL COMMENT '首 Token 耗时(毫秒), 仅流式有值',
  `prompt_tokens` int DEFAULT NULL COMMENT '输入 Token 数',
  `completion_tokens` int DEFAULT NULL COMMENT '输出 Token 数',
  `total_tokens` int DEFAULT NULL COMMENT '总 Token 数',
  `prompt_text` longtext NOT NULL COMMENT '模型实际收到的完整输入(messages 的 JSON)',
  `completion_text` longtext COMMENT '模型实际生成的完整输出(流式为逐块拼接)',
  `prompt_chars` int NOT NULL DEFAULT '0' COMMENT '输入字符数(便于按体积排序, 免解析 JSON)',
  `completion_chars` int NOT NULL DEFAULT '0' COMMENT '输出字符数',
  `created_time` datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '落库时间',
  PRIMARY KEY (`id`),
  KEY `idx_llm_call_lo_start_a_ca4dd2` (`start_at`),
  KEY `idx_llm_call_lo_model_b79a47` (`model`,`start_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM 调用统计表(耗时/Token/完整输入输出)';
