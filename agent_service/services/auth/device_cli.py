"""Revoke a remembered desktop device even while the HTTP backend is unavailable.

Invoked only as a local executable command. It uses the same config, database
factory and AuthService operation, creates no tables and starts no listener.
"""
from __future__ import annotations
import argparse
import logging
from pathlib import Path
from sqlalchemy import inspect
from agent_service.core.agent_config import AgentConfig
from agent_service.core.db.engine import create_database_engine
from agent_service.services.auth.service import AuthService

logger = logging.getLogger(__name__)

def main(arguments: list[str]) -> int:
    """Return zero after durable revocation or when no device database exists."""
    parser = argparse.ArgumentParser(description="Forget a local remembered device")
    parser.add_argument("device_id")
    args = parser.parse_args(arguments)
    config = AgentConfig.load_config(ensure_models=False, ensure_directories=False)
    if not Path(config.storage.sqlite_path).is_file():
        return 0
    engine = create_database_engine(config)
    service = None
    try:
        if not inspect(engine).has_table("auth_devices"):
            return 0
        service = AuthService(config=config, engine=engine)
        service.delete_remembered_blob(args.device_id)
        return 0
    except Exception:
        logger.error("Failed to forget local remembered device", exc_info=True)
        return 1
    finally:
        if service is not None:
            service.close()
        engine.dispose()
