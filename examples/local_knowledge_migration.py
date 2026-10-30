"""只用于明确的本机 SQLite 演示库；正式 MySQL 使用审查后的 SQL。"""
import sqlite3


def migrate_local_jobs(path):
    with sqlite3.connect(path) as connection:
        columns = {r[1] for r in connection.execute('PRAGMA table_info("keenrobot_documents")')}
        additions = {"task_id": "VARCHAR(64)", "task_dispatched_at": "TIMESTAMP", "next_retry_at": "TIMESTAMP",
            "deletion_retry_count": "INT NOT NULL DEFAULT 0", "deletion_retryable": "INT NOT NULL DEFAULT 1",
            "deletion_error_type": "VARCHAR(64)", "cleanup_file_paths": "JSON NOT NULL DEFAULT '[]'",
            "artifact_paths": "JSON NOT NULL DEFAULT '[]'"}
        for name, definition in additions.items():
            if columns and name not in columns:
                connection.execute(f'ALTER TABLE "keenrobot_documents" ADD COLUMN "{name}" {definition}')
        if columns:
            connection.execute("UPDATE keenrobot_documents SET status='delete_failed', deletion_retryable=0 WHERE is_deleted=1 AND status='failed'")
            connection.execute("UPDATE keenrobot_documents SET status='deleting' WHERE is_deleted=1 AND status='processing'")
