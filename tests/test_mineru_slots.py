"""MinerU slot recovery regressions using real bounded child processes."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_service.services.document_parsing.mineru import MinerUClient, MinerUNetworkError


def test_abandoned_lease_does_not_block_new_tasks(tmp_path: Path) -> None:
    """Legacy lease files cannot occupy a slot after their worker exits."""

    (tmp_path / "slot-0.lease").write_text("99999999:abandoned", encoding="ascii")
    client = MinerUClient({"slot_dir": str(tmp_path), "max_concurrency": 1, "timeout_seconds": 0.05})
    with client._process_slot():
        pass


def test_slot_released_after_worker_is_killed(tmp_path: Path) -> None:
    """OS process exit releases a slot even when Python finally cannot run."""

    code = """
import sys, time
from pathlib import Path
from agent_service.services.document_parsing.mineru import MinerUClient
root = Path(sys.argv[1])
with MinerUClient({'slot_dir': str(root), 'max_concurrency': 1})._process_slot():
    (root / 'acquired').write_text('ready', encoding='ascii')
    time.sleep(30)
"""
    worker = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)])
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "acquired").exists() and time.monotonic() < deadline:
            assert worker.poll() is None
            time.sleep(0.02)
        assert (tmp_path / "acquired").exists()
        client = MinerUClient({"slot_dir": str(tmp_path), "max_concurrency": 1, "timeout_seconds": 0.05})
        with pytest.raises(MinerUNetworkError):
            with client._process_slot():
                pytest.fail("a live worker must retain its slot")
        worker.kill()
        worker.wait(timeout=5)
        with client._process_slot():
            pass
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=5)


def test_waiting_slot_reports_real_stage(tmp_path: Path) -> None:
    """Capacity waiting is visible and cannot be mistaken for file preparation."""

    client = MinerUClient({"slot_dir": str(tmp_path), "max_concurrency": 1, "timeout_seconds": 0.05})
    updates: list[dict] = []
    with client._process_slot():
        with pytest.raises(MinerUNetworkError):
            with client._process_slot(updates.append):
                pass
    assert updates[-1]["stage"] == "vlm_wait_slot"


def test_slot_released_after_parser_exception(tmp_path: Path) -> None:
    """Normal parser failures also return their capacity to the next task."""

    client = MinerUClient({"slot_dir": str(tmp_path), "max_concurrency": 1})
    with pytest.raises(ValueError):
        with client._process_slot():
            raise ValueError("parse failed")
    with client._process_slot():
        pass
