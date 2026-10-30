CREATE TABLE IF NOT EXISTS keenrobot_skill_classes (
  id VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  UNIQUE KEY uq_keenrobot_skill_classes_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS keenrobot_applications (
  id VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  UNIQUE KEY uq_keenrobot_applications_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO keenrobot_skill_classes (id, name, sort_order) VALUES
('SKILL-POINT-005', '测试要点生成', 10),
('SKILL-CASE-001', '智能用例生成', 20),
('SKILL-BUG-004', '历史缺陷案例推荐', 30),
('SKILL-REPORT-006', '测试报告生成', 40),
('SKILL-DATA-002', '测试数据构造', 50),
('SKILL-UI-007', 'UI自动化脚本生成', 60)
ON DUPLICATE KEY UPDATE name=VALUES(name), sort_order=VALUES(sort_order), is_enabled=1;

INSERT INTO keenrobot_applications (id, name, sort_order) VALUES
('*', '全应用适用', 0),
('信用卡系统', '信用卡系统', 10),
('核心系统', '核心系统', 20),
('ATPM', 'ATPM', 30),
('FNP', 'FNP', 40),
('BLIM', 'BLIM', 50),
('测试平台', '测试平台', 60),
('平台官方', '平台官方', 70)
ON DUPLICATE KEY UPDATE name=VALUES(name), sort_order=VALUES(sort_order), is_enabled=1;
