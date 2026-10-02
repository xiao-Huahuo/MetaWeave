"""DSH Runtime受管资源服务的磁盘状态与租约回归测试。"""

from __future__ import annotations

import json
import hashlib
import os
import threading
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from agent_service.core.agent_config import AgentConfig
from agent_service.services.dsh_runtime import DshRuntimePackageManager
from agent_service.services.dsh_runtime import service as runtime_service


def _manager(tmp_path, bundle_dir=None) -> DshRuntimePackageManager:
    """创建使用指定内置制品目录的临时 DSH资源管理器。"""

    config = AgentConfig.load_config(
        overrides={
            "storage": {"base_data_dir": str(tmp_path), "dsh_sdk_dir": "assets/sdks/dsh"},
            "dsh": {"runtime_version": "test-v1"},
        },
        load_env=False,
        load_dotenv=False,
        ensure_models=False,
    )
    return DshRuntimePackageManager(config=config, bundle_dir=bundle_dir)


def _embedded_bundle(tmp_path):
    """生成只含测试文件的内置 manifest与 ZIP。"""

    bundle_dir = tmp_path / "embedded"
    bundle_dir.mkdir()
    archive = bundle_dir / "sdk.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("runtime.exe", b"runtime")
        package.writestr("launcher.exe", b"launcher")
        package.writestr("config/mw.patch.yml", b"config")
    manifest = {
        "version": "test-v1",
        "platform": "windows",
        "arch": "x64",
        "archive_file": archive.name,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "archive_size_bytes": archive.stat().st_size,
        "installed_size_bytes": len(b"runtimelauncherconfig"),
        "executable": "runtime.exe",
        "launcher": "launcher.exe",
        "cordis_configs": {"sandbox": "config/mw.patch.yml"},
        "launch_args": {"sandbox": ["{runtime}"]},
    }
    (bundle_dir / "sdk.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    return bundle_dir


def test_runtime_manager_resolves_installed_bundle_and_blocks_in_use_uninstall(tmp_path) -> None:
    """ready版本应解析 argv，并在有租约时拒绝卸载。"""

    manager = _manager(tmp_path)
    version_dir = manager._installed_version_dir()
    (version_dir / "config").mkdir(parents=True)
    for relative in ("runtime.exe", "launcher.exe", "config/mw.patch.yml"):
        target = version_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture")
    manifest = {
        "executable": "runtime.exe",
        "launcher": "launcher.exe",
        "cordis_configs": {"sandbox": "config/mw.patch.yml"},
        "launch_args": {"sandbox": ["{runtime}", "--patch", "{root}/config/mw.patch.yml"]},
    }
    (version_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    manager.current_file.write_text(
        json.dumps({"directory": "sdk", "version": "test-v1", "executable": "runtime.exe"}),
        encoding="utf-8",
    )

    assert manager.get_management_status()["status"] == "ready"
    assert manager.resolve_launcher() == (version_dir / "launcher.exe").resolve()
    assert manager.resolve_runtime_launch_args("sandbox") == (
        str((version_dir / "runtime.exe").resolve()),
        "--patch",
        str((version_dir / "config" / "mw.patch.yml").resolve()),
    )
    manager.acquire_runtime("child-1")
    with pytest.raises(ValueError, match="正在被子 Agent 使用"):
        manager.uninstall()
    manager.release_runtime("child-1")
    assert manager.uninstall()["status"] == "missing"
    assert not version_dir.exists()


def test_runtime_manager_lazily_extracts_embedded_bundle_without_network(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首次租用应从 EXE内置 ZIP解压，且绝不访问网络。"""

    manager = _manager(tmp_path, _embedded_bundle(tmp_path))
    monkeypatch.setattr(manager, "_self_check", lambda launcher, executable: None)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: pytest.fail("内置 SDK安装不得访问网络"),
    )

    assert manager.get_management_status()["status"] == "missing"
    assert not manager._installed_version_dir().exists()
    executable = manager.acquire_runtime("child-1")

    assert executable.read_bytes() == b"runtime"
    assert manager.get_management_status()["status"] == "ready"
    manager.release_runtime("child-1")


def test_runtime_manager_refuses_install_without_embedded_bundle(tmp_path) -> None:
    """开发运行缺少内置 SDK制品时应明确拒绝安装。"""

    manager = _manager(tmp_path, tmp_path / "missing-bundle")
    with pytest.raises(ValueError, match="内置 SDK"):
        manager.start_install()


def test_runtime_manager_preserves_repair_failure_when_old_runtime_still_exists(tmp_path) -> None:
    """修复失败后不得因旧 executable 尚在就把 failed 状态伪装回 ready。"""

    manager = _manager(tmp_path)
    version_dir = manager._installed_version_dir()
    version_dir.mkdir(parents=True)
    (version_dir / "runtime.exe").write_bytes(b"old-runtime")
    manager.current_file.write_text(
        json.dumps({"directory": "sdk", "version": "test-v1", "executable": "runtime.exe"}),
        encoding="utf-8",
    )
    manager._set_progress("failed", "repair self-check failed")

    status = manager.get_management_status()

    assert status["status"] == "failed"
    assert status["message"] == "repair self-check failed"


@pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH regression")
def test_runtime_manager_extracts_required_node_file_beyond_max_path(tmp_path) -> None:
    """受管 ZIP 的深层 Node 依赖必须通过扩展路径完整解压。"""

    manager = _manager(tmp_path)
    archive = tmp_path / "long-path.zip"
    relative = Path(*(["nested-segment"] * 18), "runtime.js")
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(relative.as_posix(), b"module.exports = true;")
    destination = tmp_path / "extracted"

    manager._extract_archive(archive, destination, total_bytes=0)

    assert manager._windows_io_path(destination / relative).read_bytes() == b"module.exports = true;"


@pytest.mark.parametrize("cancelled", [False, True])
def test_runtime_acquire_can_leave_stalled_shared_install(
    tmp_path, monkeypatch: pytest.MonkeyPatch, cancelled: bool,
) -> None:
    """安装卡住时租用者可超时或取消，且不取消其他租用者共享的安装。"""

    manager = _manager(tmp_path)
    manager.config.dsh.startup_timeout_seconds = 0.05
    release_install = threading.Event()
    acquired = threading.Event()
    cancellation = threading.Event()
    errors: list[Exception] = []
    worker = threading.Thread(target=release_install.wait, daemon=True)
    manager._worker = worker
    monkeypatch.setattr(manager, "start_install", lambda: {})

    def acquire() -> None:
        """捕获租用结果，以便失败实现也能在 finally 内释放测试线程。"""

        try:
            manager.acquire_runtime("child-1", cancellation=cancellation)
        except Exception as exc:
            errors.append(exc)
        finally:
            acquired.set()

    worker.start()
    caller = threading.Thread(target=acquire, daemon=True)
    caller.start()
    if cancelled:
        cancellation.set()
    try:
        assert acquired.wait(1), "租用不能无限等待共享安装线程"
        assert len(errors) == 1
        assert isinstance(errors[0], InterruptedError if cancelled else TimeoutError)
        assert not manager._leases
        assert worker.is_alive() and not manager._cancel.is_set()
    finally:
        release_install.set()
        worker.join(timeout=1)
        caller.join(timeout=1)


def _blocked_finalize(manager, monkeypatch, *, winerror, recover=False, error_type=PermissionError):
    """只阻断目录发布，保留真实解压/磁盘切换，用虚拟时钟检查有界重试。"""

    original_replace = os.replace
    state = {"attempts": 0, "elapsed": 0.0}
    monkeypatch.setattr(manager, "_self_check", lambda _launcher, _executable: None)
    monkeypatch.setattr(runtime_service, "time", SimpleNamespace(monotonic=lambda: state["elapsed"]))

    def wait(seconds):
        """推进安装 owner 的时间，不产生真实阻塞或额外测试线程。"""

        state["elapsed"] += seconds
        return manager._cancel.is_set()

    def replace(source, destination):
        """模拟 Windows 扫描器占用发布目录；版本指针仍使用实际 os.replace。"""

        if Path(source).name.startswith(".sdk-"):
            state["attempts"] += 1
            if not recover or state["attempts"] < 3:
                error = error_type("finalize access denied")
                error.winerror = winerror
                raise error
        return original_replace(source, destination)

    monkeypatch.setattr(manager._cancel, "wait", wait)
    monkeypatch.setattr(runtime_service.os, "replace", replace)
    return state


@pytest.mark.parametrize("winerror", [5, 32])
def test_runtime_install_retries_transient_windows_directory_denial(tmp_path, monkeypatch, winerror):
    """短时目录占用解除后，必须真正发布验证过的 Runtime 才显示 ready。"""

    manager = _manager(tmp_path, _embedded_bundle(tmp_path))
    state = _blocked_finalize(manager, monkeypatch, winerror=winerror, recover=True)
    manager._install_worker()
    assert state["attempts"] == 3
    assert manager.get_management_status()["status"] == "ready"
    assert manager._runtime_executable().read_bytes() == b"runtime"
    assert not manager.versions_dir.exists()
    assert not list(manager.work_dir.glob(".sdk-*"))


@pytest.mark.parametrize("winerror", [5, 32])
def test_runtime_install_permanent_windows_denial_fails_and_cleans_staging(tmp_path, monkeypatch, winerror):
    """占用超过配置期限仍为 failed，不能写版本指针或留下 staging。"""

    manager = _manager(tmp_path, _embedded_bundle(tmp_path))
    state = _blocked_finalize(manager, monkeypatch, winerror=winerror)
    manager._install_worker()
    assert state["attempts"] > 1
    assert state["elapsed"] == pytest.approx(manager.config.dsh.install_finalize_timeout_seconds)
    assert manager.get_management_status()["status"] == "failed"
    assert not manager.current_file.exists()
    assert not manager.versions_dir.exists()
    assert not list(manager.work_dir.glob(".sdk-*"))
    assert manager._worker is None


@pytest.mark.parametrize("error_type,winerror", [(PermissionError, 123), (PermissionError, None), (OSError, 5)])
def test_runtime_install_does_not_retry_other_filesystem_errors(tmp_path, monkeypatch, error_type, winerror):
    """不支持的错误保持原失败，不把权限或路径故障吞成临时占用。"""

    manager = _manager(tmp_path, _embedded_bundle(tmp_path))
    state = _blocked_finalize(manager, monkeypatch, winerror=winerror, error_type=error_type)
    manager._install_worker()
    assert state["attempts"] == 1
    assert state["elapsed"] == 0
    assert manager.get_management_status()["status"] == "failed"
    assert not manager.current_file.exists()
    assert not manager.versions_dir.exists()
    assert not list(manager.work_dir.glob(".sdk-*"))


def test_runtime_install_cancellation_interrupts_directory_publish_retry(tmp_path, monkeypatch):
    """取消在受控 rename 边界到达时，安装线程退出并清理 staging。"""

    manager = _manager(tmp_path, _embedded_bundle(tmp_path))
    entered, release = threading.Event(), threading.Event()
    original_replace = os.replace
    monkeypatch.setattr(manager, "_self_check", lambda _launcher, _executable: None)

    def replace(source, destination):
        """把实际目录发布暂留在 Windows sharing violation 边界。"""

        if Path(source).name.startswith(".sdk-"):
            entered.set()
            assert release.wait(2)
            error = PermissionError("directory still in use")
            error.winerror = 32
            raise error
        return original_replace(source, destination)

    monkeypatch.setattr(runtime_service.os, "replace", replace)
    worker = threading.Thread(target=manager._install_worker, daemon=True)
    manager._worker = worker
    worker.start()
    try:
        assert entered.wait(1)
        manager.cancel_install()
        release.set()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert manager.get_management_status()["status"] == "missing"
        assert manager.get_management_status()["message"] == "安装已取消"
        assert not manager.current_file.exists()
        assert not manager.versions_dir.exists()
        assert not list(manager.work_dir.glob(".sdk-*"))
    finally:
        manager._cancel.set()
        release.set()
        worker.join(timeout=2)


@pytest.mark.parametrize("outside_argument", ["staging", "destination"])
def test_runtime_install_finalize_rejects_paths_outside_sdk_locations(tmp_path, outside_argument):
    """发布前验证两个规范化目录，不能删除受管根内的其他目录。"""

    manager = _manager(tmp_path)
    staging = manager.work_dir / ".sdk-staging"
    destination = manager._installed_version_dir()
    outside = manager.root / "outside-versions"
    outside.mkdir()
    marker = outside / "witness.txt"
    marker.write_text("unchanged", encoding="utf-8")
    if outside_argument == "staging":
        staging = outside
    else:
        destination = outside
    with pytest.raises(ValueError, match="work|sdk"):
        manager._finalize_install_directory(staging, destination)
    assert marker.read_text(encoding="utf-8") == "unchanged"


@pytest.mark.parametrize("field", ["install_finalize_timeout_seconds", "filesystem_retry_delay_seconds"])
@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf")])
def test_runtime_install_retry_config_requires_finite_positive_values(field, invalid):
    """重试期限和间隔必须有限且为正，避免忙等或永久安装。"""

    with pytest.raises(ValueError, match=field):
        AgentConfig.DshConfig(**{field: invalid})


def test_runtime_install_retry_config_reads_environment(tmp_path, monkeypatch):
    """进程环境覆盖经 AgentConfig 统一读取，不扩展用户业务设置。"""

    monkeypatch.setenv("AGENT_DSH_INSTALL_FINALIZE_TIMEOUT_SECONDS", "0.75")
    monkeypatch.setenv("AGENT_DSH_FILESYSTEM_RETRY_DELAY_SECONDS", "0.025")
    config = AgentConfig.load_config(
        overrides={"storage": {"base_data_dir": str(tmp_path)}},
        load_env=True, load_dotenv=False, ensure_models=False,
    )
    assert config.dsh.install_finalize_timeout_seconds == 0.75
    assert config.dsh.filesystem_retry_delay_seconds == 0.025


def test_runtime_install_uses_fixed_sdk_directory_and_cleans_legacy_versions(tmp_path, monkeypatch):
    """成功升级只留下固定 sdk，current 指向它而真实兼容版本保留在 metadata。"""

    manager = _manager(tmp_path, _embedded_bundle(tmp_path))
    old = manager.versions_dir / "old-v0"
    stale = manager.versions_dir / ".old-staging"
    for folder in (old, stale):
        folder.mkdir(parents=True)
        (folder / "obsolete.txt").write_text("old SDK", encoding="utf-8")
    conversations = Path(manager.config.storage.base_data_dir) / "dsh" / "conversations"
    conversations.mkdir(parents=True)
    marker = conversations / "history.txt"
    marker.write_text("keep history", encoding="utf-8")
    monkeypatch.setattr(manager, "_self_check", lambda _launcher, _executable: None)
    manager._install_worker()

    assert manager.get_management_status()["status"] == "ready"
    assert not manager.versions_dir.exists(), "成功安装仍保留旧 SDK 和 staging"
    sdk = manager.root / "sdk"
    assert manager._runtime_executable() == (sdk / "runtime.exe").resolve()
    current = json.loads(manager.current_file.read_text(encoding="utf-8"))
    assert current["directory"] == "sdk"
    assert current["version"] == "test-v1"
    assert manager.get_management_status()["path"] == str(sdk.resolve())
    assert marker.read_text(encoding="utf-8") == "keep history"


def test_runtime_install_failure_preserves_legacy_sdk_and_pointer(tmp_path, monkeypatch):
    """新包未通过自检前，不能删除旧缓存或会话资料。"""

    manager = _manager(tmp_path, _embedded_bundle(tmp_path))
    old = manager.versions_dir / "old-v0"
    old.mkdir(parents=True)
    marker = old / "runtime.exe"
    marker.write_bytes(b"old runtime")
    previous = {"version": "old-v0", "executable": "runtime.exe"}
    manager.current_file.write_text(json.dumps(previous), encoding="utf-8")

    def fail_check(_launcher, _executable):
        """复现正式安装自检失败。"""

        raise RuntimeError("self check rejected")

    monkeypatch.setattr(manager, "_self_check", fail_check)
    manager._install_worker()
    assert manager.get_management_status()["status"] == "failed"
    assert marker.read_bytes() == b"old runtime"
    assert json.loads(manager.current_file.read_text(encoding="utf-8")) == previous


def test_runtime_install_legacy_cleanup_failure_is_not_reported_ready(tmp_path, monkeypatch):
    """旧 SDK 清理失败时如实 failed，不能把并存的缓存报告为完整安装成功。"""

    manager = _manager(tmp_path, _embedded_bundle(tmp_path))
    legacy = manager.versions_dir / "old-v0"
    legacy.mkdir(parents=True)
    (legacy / "old.txt").write_bytes(b"old")
    remove_tree = manager._remove_tree
    monkeypatch.setattr(manager, "_self_check", lambda _launcher, _executable: None)

    def deny_legacy(path, **kwargs):
        """仅阻断旧版本清理，其他 staging 的回收使用真实实现。"""

        if path.resolve() == manager.versions_dir.resolve():
            raise PermissionError("legacy SDK still locked")
        return remove_tree(path, **kwargs)

    monkeypatch.setattr(manager, "_remove_tree", deny_legacy)
    manager._install_worker()
    status = manager.get_management_status()
    assert status["status"] == "failed"
    assert "legacy SDK still locked" in status["message"]
    assert legacy.exists()


def test_runtime_manager_does_not_cleanup_legacy_while_runtime_is_leased(tmp_path, monkeypatch):
    """即使是默认安装入口请求清旧版本，也不能覆盖正在使用的 Runtime。"""

    manager = _manager(tmp_path, _embedded_bundle(tmp_path))
    monkeypatch.setattr(manager, "_self_check", lambda _launcher, _executable: None)
    manager._install_worker()
    executable = manager.acquire_runtime("active-child")
    legacy = manager.versions_dir / "old-v0"
    legacy.mkdir(parents=True)
    marker = legacy / "old.txt"
    marker.write_bytes(b"old")
    try:
        with pytest.raises(ValueError, match="正在被子 Agent 使用"):
            manager.start_install()
        assert executable.read_bytes() == b"runtime"
        assert marker.read_bytes() == b"old"
    finally:
        manager.release_runtime("active-child")


def test_fixed_sdk_directory_still_rejects_mismatched_runtime_version(tmp_path):
    """sdk 是固定名称，不得用它替代真实版本的升级兼容性检查。"""

    manager = _manager(tmp_path)
    sdk = manager.root / "sdk"
    sdk.mkdir()
    (sdk / "runtime.exe").write_bytes(b"incompatible")
    manager.current_file.write_text(json.dumps({
        "directory": "sdk", "version": "old-v0", "executable": "runtime.exe",
    }), encoding="utf-8")
    assert manager._runtime_executable() is None
    assert manager.get_management_status()["status"] == "missing"


def test_sdk_cleanup_only_removes_known_staging_and_preserves_active_owner(tmp_path):
    """只清已知 .sdk-* 临时目录，保留当前 staging 和任意 work 文件。"""

    manager = _manager(tmp_path)
    active = manager.work_dir / ".sdk-active"
    stale = manager.work_dir / ".sdk-stale"
    unrelated = manager.work_dir / "user-notes"
    for folder in (active, stale, unrelated):
        folder.mkdir()
        (folder / "marker.txt").write_bytes(b"keep or cleanup")
    note = manager.work_dir / ".sdk-note.txt"
    note.write_bytes(b"not a staging directory")
    manager._cleanup_legacy_sdk(staging=active)
    assert not stale.exists()
    assert (active / "marker.txt").read_bytes() == b"keep or cleanup"
    assert (unrelated / "marker.txt").read_bytes() == b"keep or cleanup"
    assert note.read_bytes() == b"not a staging directory"


def test_runtime_acquire_waits_for_repair_before_leasing_sdk(tmp_path, monkeypatch):
    """修复期间新租用必须等待安装 owner，不能租用即将被替换的旧 sdk。"""

    manager = _manager(tmp_path, _embedded_bundle(tmp_path))
    monkeypatch.setattr(manager, "_self_check", lambda _launcher, _executable: None)
    manager._install_worker()
    entered, release, acquired = threading.Event(), threading.Event(), threading.Event()
    outputs = []

    def check(_launcher, _executable):
        """阻塞正式 repair 的自检，让另一线程尝试获取 Runtime 租约。"""

        entered.set()
        assert release.wait(2)

    def acquire():
        """保存调用结果和异常，并明确通知租用线程结束。"""

        try:
            outputs.append(manager.acquire_runtime("new-child"))
        except Exception as exc:
            outputs.append(exc)
        finally:
            acquired.set()

    monkeypatch.setattr(manager, "_self_check", check)
    manager.start_install(repair=True)
    assert entered.wait(1)
    caller = threading.Thread(target=acquire, daemon=True)
    caller.start()
    try:
        assert not acquired.wait(0.05)
        assert not manager._leases
        release.set()
        assert acquired.wait(1)
        assert outputs == [(manager.root / "sdk/runtime.exe").resolve()]
    finally:
        release.set()
        caller.join(timeout=2)
        manager.release_runtime("new-child")
        manager.shutdown()
