"""统一数据库 factory 与 Alembic 迁移测试。

测试只操作 pytest 临时目录中的 SQLite 文件，覆盖空库、重复升级和受支持的无版本
旧库补列；不会读取或修改用户运行时数据库。
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import inspect, text
from sqlmodel import SQLModel

import agent_service.models  # noqa: F401
from agent_service.core.agent_config import AgentConfig
from agent_service.core.db.engine import create_database_engine
from agent_service.core.db.migration import build_alembic_config, upgrade_database


def _config(tmp_path: Path) -> AgentConfig:
    """创建把全部运行数据隔离到 pytest 临时目录的配置。"""

    return AgentConfig.load_config(
        {
            "storage": {
                "project_root": str(Path(__file__).resolve().parents[1]),
                "base_data_dir": str(tmp_path / "runtime"),
                "sqlite_path": str(tmp_path / "runtime" / "db" / "relation" / "agent_service.db"),
                "chroma_persist_dir": str(tmp_path / "runtime" / "db" / "vector" / "chroma"),
            }
        },
        load_env=False,
        ensure_directories=True,
        ensure_models=False,
    )


def test_empty_database_upgrades_to_complete_schema_and_is_idempotent(tmp_path: Path) -> None:
    """空库必须仅通过 Alembic 创建完整模型 schema，并可重复升级。"""

    config = _config(tmp_path)
    engine = create_database_engine(config)

    upgrade_database(config=config, engine=engine)
    first_tables = set(inspect(engine).get_table_names())
    upgrade_database(config=config, engine=engine)
    second_tables = set(inspect(engine).get_table_names())

    assert set(SQLModel.metadata.tables) <= first_tables
    assert "alembic_version" in first_tables
    assert second_tables == first_tables


def test_supported_unversioned_database_is_backed_up_stamped_and_upgraded(tmp_path: Path) -> None:
    """无版本旧库必须先备份，再补充历史缺失列并到达 head。"""

    config = _config(tmp_path)
    engine = create_database_engine(config)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE knowledge_graph_dedup_decisions"))
        connection.execute(text("DROP TABLE knowledge_graph_section_cache"))
        connection.execute(text("DROP TABLE component_library_metadata"))
        connection.execute(text("DROP TABLE user_llm_config"))
        connection.execute(text(
            "CREATE TABLE user_llm_config ("
            "user_id VARCHAR(128) NOT NULL PRIMARY KEY, "
            "api_key VARCHAR(1024) NOT NULL DEFAULT '', "
            "base_url VARCHAR(1024) NOT NULL DEFAULT '', "
            "model_name VARCHAR(256) NOT NULL DEFAULT '', "
            "updated_at DATETIME NOT NULL)"
        ))
        connection.execute(text("DROP TABLE user_settings"))
        connection.execute(text(
            "CREATE TABLE user_settings ("
            "user_id VARCHAR(128) NOT NULL PRIMARY KEY, "
            "knowledge_dir VARCHAR(1024) NOT NULL, "
            "font_size_percent INTEGER NOT NULL DEFAULT 100, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO user_settings (user_id, knowledge_dir, font_size_percent, created_at, updated_at) "
            "VALUES ('legacy-user', 'D:/Knowledge', 115, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        connection.execute(text("DROP TABLE smart_form_rows"))
        connection.execute(text(
            "CREATE TABLE smart_form_rows ("
            "row_record_id VARCHAR(160) NOT NULL PRIMARY KEY, "
            "form_id VARCHAR(64) NOT NULL, row_id VARCHAR(96) NOT NULL, order_index INTEGER NOT NULL)"
        ))
        connection.execute(text("DROP TABLE smart_form_columns"))
        connection.execute(text(
            "CREATE TABLE smart_form_columns ("
            "column_record_id VARCHAR(160) NOT NULL PRIMARY KEY, "
            "form_id VARCHAR(64) NOT NULL, column_id VARCHAR(96) NOT NULL, "
            "order_index INTEGER NOT NULL, title VARCHAR(256) NOT NULL, column_type VARCHAR(32) NOT NULL, "
            "removable BOOLEAN NOT NULL, editable BOOLEAN NOT NULL, width INTEGER NOT NULL, "
            "options_json TEXT NOT NULL, tone VARCHAR(32) NOT NULL)"
        ))

    upgrade_database(config=config, engine=engine)

    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "20260910_0015"
    assert "component_library_metadata" in inspect(engine).get_table_names()
    assert {"knowledge_graph_section_cache", "knowledge_graph_dedup_decisions"} <= set(inspect(engine).get_table_names())
    assert "small_model_name" in {
        column["name"] for column in inspect(engine).get_columns("user_llm_config")
    }
    assert {"ui_font_size_percent", "text_font_size_percent"} <= {
        column["name"] for column in inspect(engine).get_columns("user_settings")
    }
    assert "dsh_coding_agent_enabled" in {
        column["name"] for column in inspect(engine).get_columns("user_settings")
    }
    assert "model_auto_download_enabled" in {
        column["name"] for column in inspect(engine).get_columns("user_settings")
    }
    assert "vision_understanding_enabled" in {
        column["name"] for column in inspect(engine).get_columns("user_settings")
    }
    assert "tag_colors" in {
        column["name"] for column in inspect(engine).get_columns("user_settings")
    }
    assert "tag_colors_translucent" in {
        column["name"] for column in inspect(engine).get_columns("user_settings")
    }
    assert {"height", "created_at", "updated_at"} <= {
        column["name"] for column in inspect(engine).get_columns("smart_form_rows")
    }
    assert "description" in {
        column["name"] for column in inspect(engine).get_columns("smart_form_columns")
    }
    with engine.connect() as connection:
        sizes = connection.execute(text(
            "SELECT ui_font_size_percent, text_font_size_percent FROM user_settings "
            "WHERE user_id = 'legacy-user'"
        )).one()
    assert tuple(sizes) == (115, 115)
    backups = list((config.storage.base_data_dir / "backups" / "db-migrations").glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].stat().st_size > 0


def test_compatibility_revision_downgrade_and_upgrade_round_trip(tmp_path: Path) -> None:
    """从 head 退回基线再升级时，完整 schema 必须保持可用。"""

    config = _config(tmp_path)
    engine = create_database_engine(config)
    upgrade_database(config=config, engine=engine)
    alembic_config = build_alembic_config(config)

    command.downgrade(alembic_config, "20260829_0001")
    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260910_0015"
    assert set(SQLModel.metadata.tables) <= set(inspect(engine).get_table_names())
