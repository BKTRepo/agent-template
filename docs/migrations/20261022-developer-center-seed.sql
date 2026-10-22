-- 开发者中心联调演示数据：仅用于验证前端从后端读取，不属于前端 mock。
INSERT INTO keenrobot_skills (
  id, name, name_key, description, user_id, is_enabled, display_status,
  current_version_id, current_revision, config, state
) VALUES (
  'seed-skill-login', '登录功能测试用例生成', SHA2('登录功能测试用例生成', 256),
  '基于登录需求和业务约束生成测试用例。', 1, 0, 'DRAFT',
  'seed-skill-login-v1', 1,
  JSON_OBJECT(
    'class_id', 'SKILL-CASE-001',
    'application_ids', JSON_ARRAY('*'),
    'instructions', '读取登录需求，生成正向、异常和边界测试用例。',
    'resource_ids', JSON_ARRAY(),
    'resource_usage', '',
    'compatibility', 'Python 3.12',
    'technical_name', 'login-test-case-generator',
    'uploaded_resources', JSON_ARRAY(),
    'knowledge_bases', JSON_ARRAY()
  ), 0
) ON DUPLICATE KEY UPDATE
  description = VALUES(description),
  display_status = VALUES(display_status),
  current_version_id = VALUES(current_version_id),
  config = VALUES(config),
  updated_time = CURRENT_TIMESTAMP(6);

INSERT INTO keenrobot_skill_versions (
  id, skill_id, version, revision, skill_class_id, application_id, description,
  instructions, resource_usage, compatibility, created_by
) VALUES (
  'seed-skill-login-v1', 'seed-skill-login', '1.0.0', 1,
  'SKILL-CASE-001', '*', '基于登录需求和业务约束生成测试用例。',
  '读取登录需求，生成正向、异常和边界测试用例。',
  NULL, 'Python 3.12', 1
) ON DUPLICATE KEY UPDATE
  description = VALUES(description),
  instructions = VALUES(instructions),
  updated_time = CURRENT_TIMESTAMP(6);
