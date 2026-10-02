"""Verify the base reranker default, storage identity and filtered download paths."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_service.core.agent_config import AgentConfig
from agent_service.scripts import download_model
from agent_service.services.model_management.service import ModelManagementService


def test_default_model_storage_does_not_reuse_old_m3_cache(tmp_path: Path) -> None:
    """Storage reports only the configured base model, even when M3 is present."""

    config = AgentConfig()
    assert config.model.rerank_model_name == "BAAI/bge-reranker-base"
    config.storage.rerank_model_dir = tmp_path
    old = download_model.model_target_dir("BAAI/bge-reranker-v2-m3", tmp_path)
    old.mkdir()
    for name in ("config.json", "model.safetensors", "tokenizer.json", ".download_complete"):
        (old / name).write_text("old-model", encoding="utf-8")
    service = ModelManagementService(config=config, settings_service=None)
    item = service._hf_model(
        key="rerank", label="ReRank", role="rerank", name=config.model.rerank_model_name,
        base_path=tmp_path, state="not_downloaded",
    )
    assert item["path"] == str(tmp_path / "BAAI__bge-reranker-base")
    assert item["downloaded"] is False
    assert item["size_bytes"] == 0


def test_startup_and_settings_download_share_global_file_selection(tmp_path: Path, monkeypatch) -> None:
    """Both startup and model management pass the same global download whitelist."""

    config = AgentConfig()
    config.storage.rerank_model_dir = tmp_path
    calls: list[tuple[str, list[str] | None]] = []

    def ensure(name, directory, model_type=None, *, allow_patterns=None):
        calls.append((name, allow_patterns))

    monkeypatch.setattr(download_model, "ensure_model", ensure)
    config.ensure_local_models()
    service = ModelManagementService(config=config, settings_service=None)
    monkeypatch.setattr(service, "_model_is_available", lambda model: True)
    service._download_model("rerank")
    expected = (config.model.rerank_model_name, config.model.model_download_allow_patterns[config.model.rerank_model_name])
    assert calls[-1] == calls[-2] == expected
    assert "model.safetensors" in expected[1]
    assert "pytorch_model.bin" not in expected[1]


def test_download_size_counts_only_selected_runtime_files(tmp_path: Path, monkeypatch) -> None:
    """Download progress excludes alternate weights and matches the saved payload."""

    import huggingface_hub

    config = AgentConfig()
    selected = config.model.model_download_allow_patterns[config.model.rerank_model_name]
    files = {name: 10 for name in selected}
    files.update({"pytorch_model.bin": 1000, "onnx/model.onnx": 1000})
    monkeypatch.setattr(huggingface_hub.HfApi, "model_info", lambda *args, **kwargs: SimpleNamespace(
        siblings=[SimpleNamespace(rfilename=name, size=size) for name, size in files.items()],
    ))

    def snapshot(*, repo_id, local_dir, local_dir_use_symlinks, allow_patterns):
        assert allow_patterns == selected
        for name in allow_patterns:
            (Path(local_dir) / name).write_bytes(b"x" * files[name])

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot)
    target = download_model.ensure_model(config.model.rerank_model_name, tmp_path, model_type="rerank")
    progress = download_model.get_download_progress("rerank")
    assert progress["total_bytes"] == 60
    assert progress["percent"] == 100
    assert download_model.is_model_available(target)
    assert not (target / "pytorch_model.bin").exists()
    assert not (target / "onnx").exists()


@pytest.mark.parametrize("auto_download", [False, True])
def test_auto_download_preference_applies_to_new_default(tmp_path: Path, monkeypatch, auto_download: bool) -> None:
    """Startup follows the stored preference and prepares base rather than M3."""

    config = AgentConfig()
    config.storage.rerank_model_dir = tmp_path
    settings = SimpleNamespace(get_model_preferences=lambda **kwargs: {"auto_download_enabled": auto_download})
    service = ModelManagementService(config=config, settings_service=settings)
    loaded: list[str] = []
    monkeypatch.setattr(service, "_load_model", loaded.append)

    def start_worker(*, model, state, target):
        if model == "rerank":
            target()
        return True

    def download(name, directory, model_type=None, *, allow_patterns=None):
        assert name == "BAAI/bge-reranker-base"
        target = download_model.model_target_dir(name, directory)
        target.mkdir()
        for filename in ("config.json", "model.safetensors", "tokenizer.json", ".download_complete"):
            (target / filename).write_text("test", encoding="utf-8")

    monkeypatch.setattr(service, "_start_worker", start_worker)
    monkeypatch.setattr(download_model, "ensure_model", download)
    service.initialize_after_startup(user_id="u1")
    assert service._model_is_available("rerank") is auto_download
    assert loaded == (["rerank"] if auto_download else [])
