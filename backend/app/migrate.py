"""幂等迁移：新增列/索引（不动既有数据，可重复执行）

说明：新表由 SQLAlchemy create_all 自动创建；此处只补齐既有表的列与索引。
后续 schema 变更频繁时可平滑切换到 Alembic。
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

STATEMENTS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'editor'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_by VARCHAR(32)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 1",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_call_limit INTEGER",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_char_limit INTEGER",
    "UPDATE users SET role = 'editor' WHERE role IS NULL",
    "UPDATE users SET is_active = TRUE WHERE is_active IS NULL",
    "UPDATE users SET token_version = 1 WHERE token_version IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_users_role ON users (role)",
    "CREATE INDEX IF NOT EXISTS ix_ai_usage_user_created ON ai_usage (user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_ai_usage_created ON ai_usage (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_created ON audit_logs (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_user ON audit_logs (user_id)",
    # ---- 运行台账与模板版本（P1/P2）----
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS template_key VARCHAR(40) DEFAULT ''",
    "ALTER TABLE node_templates ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1",
    "ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1",
    "UPDATE node_templates SET version = 1 WHERE version IS NULL",
    "UPDATE prompt_templates SET version = 1 WHERE version IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_run_logs_user_created ON run_logs (user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_run_logs_project_created ON run_logs (project_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_run_logs_status ON run_logs (status)",
    "CREATE INDEX IF NOT EXISTS ix_run_logs_created ON run_logs (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_template_versions_tpl ON template_versions (template_id, version)",
    "ALTER TABLE template_versions ADD COLUMN IF NOT EXISTS note VARCHAR(200) DEFAULT ''",
    # 语音识别用量：音频秒数
    "ALTER TABLE ai_usage ADD COLUMN IF NOT EXISTS audio_seconds INTEGER DEFAULT 0",
    # 图标体系从 emoji 换成 Lucide 图标名（如 message-square-text），原 16 位不够
    "ALTER TABLE node_templates ALTER COLUMN icon TYPE VARCHAR(40)",
    # 稿件来源：区分 AI 生成与人工修订（审定节点里直接改稿后保存）
    "ALTER TABLE revisions ADD COLUMN IF NOT EXISTS source VARCHAR(10) DEFAULT 'ai'",
]


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for stmt in STATEMENTS:
            await conn.execute(text(stmt))
