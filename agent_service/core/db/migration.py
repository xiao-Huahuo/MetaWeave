"""AgentService Alembic 数据库版本检查、备份和升级入口。

``upgrade_database`` 在业务 Service 构造前执行。空数据库直接升级；无版本表的旧
SQLite 数据库先验证核心表、创建一致性备份，再 stamp 基线并执行幂等兼容迁移。
未知结构会被拒绝，禁止猜测性修改用户数据。
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

import agent_service.models  # noqa: F401
from agent_service.core.agent_config import AgentConfig
from agent_service.core.db.engine import database_url

logger = logging.getLogger(__name__)

BASELINE_REVISION = "20260829_0001"
POST_BASELINE_TABLES = {
    "component_library_metadata",
    "knowledge_graph_section_cache",
    "knowledge_graph_dedup_decisions",
    "scanner_records",
    "user_vlm_config_presets",
}


def build_alembic_config(config: AgentConfig) -> Config:
    """创建指向项目唯一 Alembic 环境和当前数据库 URL 的配置。"""

    ini_path = config.storage.project_root / "alembic.ini"
    if not ini_path.is_file():
        ini_path = Path(__file__).resolve().parents[3] / "alembic.ini"
    alembic_config = Config(str(ini_path))
    alembic_config.set_main_option("script_location", str(Path(__file__).resolve().parent / "alembic"))
    alembic_config.set_main_option("sqlalchemy.url", database_url(config).replace("%", "%%"))
    return alembic_config


def _sha256(path: Path) -> str:
    """流式计算数据库备份的 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_sqlite_database(config: AgentConfig) -> Path:
    """复制非空 SQLite 数据库并验证副本大小和摘要。"""

    source = config.storage.sqlite_path
    backup_root = config.storage.base_data_dir / "backups" / "db-migrations"
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_root / f"{source.stem}-{timestamp}{source.suffix}.bak"
    shutil.copy2(source, destination)
    if destination.stat().st_size != source.stat().st_size:
        destination.unlink(missing_ok=True)
        raise RuntimeError("数据库迁移备份大小校验失败。")
    digest = _sha256(destination)
    logger.info("数据库迁移备份完成 | path=%s sha256=%s", destination, digest)
    return destination


def _validate_legacy_schema(engine: Engine) -> None:
    """确认无版本旧库至少包含当前模型的全部业务表。"""

    actual_tables = set(inspect(engine).get_table_names())
    expected_tables = set(SQLModel.metadata.tables) - POST_BASELINE_TABLES
    missing_tables = sorted(expected_tables - actual_tables)
    if missing_tables:
        raise RuntimeError(f"未知旧数据库结构，缺少业务表: {', '.join(missing_tables)}")


def upgrade_database(*, config: AgentConfig, engine: Engine) -> None:
    """安全地把空库、已版本库或受支持旧 SQLite 库升级到 Alembic head。"""

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    alembic_config = build_alembic_config(config)
    if not tables:
        command.upgrade(alembic_config, "head")
        return
    if "alembic_version" not in tables:
        _validate_legacy_schema(engine)
        _backup_sqlite_database(config)
        command.stamp(alembic_config, BASELINE_REVISION)
        engine.dispose()
        with engine.connect() as connection:
            stamped_revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if stamped_revision != BASELINE_REVISION:
            raise RuntimeError(
                f"旧数据库 Alembic 基线标记异常: expected={BASELINE_REVISION} actual={stamped_revision}"
            )
        alembic_config = build_alembic_config(config)
    command.upgrade(alembic_config, "head")
