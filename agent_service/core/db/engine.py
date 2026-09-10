"""创建 AgentService 统一 SQLAlchemy engine 和 session factory。

应用启动时调用 ``create_database_engine(config)`` 一次，并把返回值注入所有业务
Service。测试可以继续显式传入独立 engine。
"""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock

from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from agent_service.core.agent_config import AgentConfig

SessionFactory = Callable[[], Session]
_ENGINE_REGISTRY: dict[str, Engine] = {}
_ENGINE_REGISTRY_LOCK = Lock()


def database_url(config: AgentConfig) -> str:
    """根据只读 AgentConfig 返回当前 SQLite SQLAlchemy URL。"""

    return f"sqlite:///{config.storage.sqlite_path}"


def create_database_engine(config: AgentConfig) -> Engine:
    """创建应用级唯一 engine，不执行建表或迁移。"""

    return create_engine(database_url(config), pool_pre_ping=True)


def create_database_engine_from_url(url: str) -> Engine:
    """Create an isolated worker-process engine through the central factory."""

    return create_engine(url, pool_pre_ping=True)


def get_database_engine(config: AgentConfig) -> Engine:
    """返回按数据库 URL 缓存的兼容 engine，供尚未显式注入的调用方复用。"""

    url = database_url(config)
    with _ENGINE_REGISTRY_LOCK:
        engine = _ENGINE_REGISTRY.get(url)
        if engine is None:
            engine = create_engine(url, pool_pre_ping=True)
            _ENGINE_REGISTRY[url] = engine
        return engine


def create_session_factory(engine: Engine) -> SessionFactory:
    """返回每次调用都创建独立 SQLModel Session 的轻量 factory。"""

    return lambda: Session(engine)
