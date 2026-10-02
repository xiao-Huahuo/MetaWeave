"""管理 EXE内置 DSH Windows Runtime 的校验、懒解压、解析和卸载。

本服务只接受 ``AgentConfig.dsh`` 固定的兼容清单，不调用 pip、npm 或 npx。
安装任务属于应用生命周期；调用方必须在退出时调用 ``shutdown``。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_service.core.agent_config import AgentConfig

logger = logging.getLogger(__name__)
_CHUNK_BYTES = 1024 * 1024
_READY_STATES = {"ready"}


class DshRuntimePackageManager:
    """保存一个应用实例拥有的 DSH Runtime 安装任务和运行时租约。"""

    def __init__(self, *, config: AgentConfig, bundle_dir: Path | None = None) -> None:
        """绑定固定配置和 EXE资源目录；构造时不解压 SDK。"""

        self.config = config
        packaged_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
        self.bundle_dir = (bundle_dir or packaged_root / "resources" / "dsh" / "sdk").resolve()
        self.root = Path(config.storage.dsh_sdk_dir).resolve()
        self.versions_dir = self.root / "versions"
        self.work_dir = self.root / "work"
        self.current_file = self.root / "current.json"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._leases: set[str] = set()
        self._progress: dict[str, Any] = {
            "status": "missing",
            "message": "尚未安装",
            "processed_bytes": 0,
            "total_bytes": 0,
            "progress": None,
        }
        self._reconcile_status()

    def get_management_status(self) -> dict[str, Any]:
        """返回设置页所需的真实安装、任务、磁盘和配置状态。"""

        with self._lock:
            self._reconcile_status(update_working=False)
            version_dir = self._installed_version_dir()
            size_bytes, file_count = self._directory_stats(version_dir)
            package_size = self._bundled_archive_size()
            return {
                "key": "deepseek_harness",
                "label": "DeepSeek Harness SDK",
                "role": "代码子 Agent 与只读执行轨迹",
                "version": self.config.dsh.runtime_version,
                "platform": "Windows x64",
                "path": str(version_dir),
                "size_bytes": size_bytes,
                "package_size_bytes": package_size,
                "file_count": file_count,
                "installed": self._progress["status"] == "ready",
                "configured": self._bundle_is_available(),
                "in_use": bool(self._leases),
                **self._progress,
            }

    def start_install(self, *, repair: bool = False) -> dict[str, Any]:
        """异步安装固定 Runtime；相同任务运行中时返回当前状态。"""

        pending_cleanup = bool(self._legacy_sdk_paths())
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return self.get_management_status()
            if not self._bundle_is_available():
                raise ValueError("当前 MW 构建缺少内置 SDK 制品")
            if self._progress["status"] == "ready" and not repair and not pending_cleanup:
                return self.get_management_status()
            if self._leases:
                raise ValueError("DSH Runtime 正在被子 Agent 使用，不能修复")
            self._cancel.clear()
            self._set_progress("repairing" if repair else "verifying", "正在校验内置 SDK")
            self._worker = threading.Thread(
                target=self._install_worker,
                name="dsh-runtime-install",
                daemon=True,
            )
            self._worker.start()
            return self.get_management_status()

    def cancel_install(self) -> dict[str, Any]:
        """请求取消当前解压；工作线程在下一个数据块边界停止。"""

        self._cancel.set()
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                self._set_progress("cancelling", "正在取消安装")
            return self.get_management_status()

    def uninstall(self) -> dict[str, Any]:
        """删除当前固定 Runtime，保留独立的 DSH Conversation 会话目录。"""

        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise ValueError("DSH Runtime 正在安装，不能卸载")
            if self._leases:
                raise ValueError("DSH Runtime 正在被子 Agent 使用，不能卸载")
            version_dir = self._installed_version_dir()
            self._assert_managed_path(version_dir)
            if version_dir.exists():
                self._remove_tree(version_dir)
            self._cleanup_legacy_sdk()
            self.current_file.unlink(missing_ok=True)
            self._set_progress("missing", "尚未安装")
            return self.get_management_status()

    def acquire_runtime(self, owner: str, *, cancellation: threading.Event | None = None) -> Path:
        """有界等待共享安装；单个租用者取消不影响其他租用者的安装。"""

        deadline = time.monotonic() + self.config.dsh.startup_timeout_seconds
        if cancellation is not None and cancellation.is_set():
            raise InterruptedError("DSH Runtime 租用已取消")
        requested_install = False
        while True:
            if cancellation is not None and cancellation.is_set():
                raise InterruptedError("DSH Runtime 租用已取消")
            executable = self._runtime_executable()
            pending_cleanup = bool(self._legacy_sdk_paths())
            with self._lock:
                worker = self._worker
                installing = worker is not None and worker.is_alive()
                if executable is not None and not pending_cleanup and not installing:
                    self._leases.add(owner)
                    return executable
            if installing:
                requested_install = True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("等待 DSH Runtime 安装超时")
                worker.join(timeout=min(remaining, 0.1))
                continue
            if requested_install:
                raise FileNotFoundError(f"DSH Runtime 安装失败: {self._progress['message']}")
            self.start_install()
            requested_install = True

    def release_runtime(self, owner: str) -> None:
        """释放调用方持有的 Runtime 租约。"""

        with self._lock:
            self._leases.discard(owner)

    def resolve_cordis_config(self, access_mode: str) -> Path:
        """返回清单为指定 MW权限模式声明的 Cordis组合路径。"""

        with self._lock:
            version_dir = self._installed_version_dir()
            manifest_path = version_dir / "manifest.json"
            if self._runtime_executable() is None or not manifest_path.is_file():
                raise FileNotFoundError("DSH Runtime 尚未完整安装")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            configs = manifest.get("cordis_configs")
            if not isinstance(configs, dict) or not str(configs.get(access_mode) or "").strip():
                raise ValueError(f"DSH Runtime 未提供 {access_mode} 权限组合")
            config_path = (version_dir / str(configs[access_mode])).resolve()
            if version_dir.resolve() not in config_path.parents or not config_path.is_file():
                raise ValueError("DSH Runtime Cordis组合路径无效")
            return config_path

    def resolve_runtime_launch_args(self, access_mode: str) -> tuple[str, ...]:
        """按清单展开指定权限组合的 Runtime argv，不解释 DSH profile细节。"""

        with self._lock:
            version_dir = self._installed_version_dir()
            manifest_path = version_dir / "manifest.json"
            executable = self._runtime_executable()
            if executable is None or not manifest_path.is_file():
                raise FileNotFoundError("DSH Runtime 尚未完整安装")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            launch_map = manifest.get("launch_args")
            raw_args = launch_map.get(access_mode) if isinstance(launch_map, dict) else None
            if not isinstance(raw_args, list) or not raw_args:
                raise ValueError(f"DSH Runtime 未提供 {access_mode} 启动参数")
            resolved: list[str] = []
            for raw in raw_args:
                template = str(raw)
                value = template.replace("{runtime}", str(executable)).replace("{root}", str(version_dir))
                if "{runtime}" in template or "{root}" in template:
                    value = str(Path(value).resolve())
                resolved.append(value)
            return tuple(resolved)

    def resolve_launcher(self) -> Path:
        """返回负责原子 Job Object接管的窄 Windows launcher。"""

        with self._lock:
            version_dir = self._installed_version_dir()
            manifest_path = version_dir / "manifest.json"
            if self._runtime_executable() is None or not manifest_path.is_file():
                raise FileNotFoundError("DSH Runtime 尚未完整安装")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            launcher = (version_dir / str(manifest.get("launcher") or "")).resolve()
            if version_dir.resolve() not in launcher.parents or not launcher.is_file():
                raise ValueError("DSH Runtime 缺少 Windows Job launcher")
            return launcher

    def shutdown(self) -> None:
        """取消安装任务并有界等待工作线程退出。"""

        self._cancel.set()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=5)

    def _install_worker(self) -> None:
        """在后台完成内置清单、ZIP、签名、自检和原子切换。"""

        staging = self.work_dir / f".sdk-{uuid4().hex}"
        try:
            manifest, archive_path = self._load_bundled_manifest()
            self._validate_manifest(manifest)
            self._set_progress("verifying", "正在校验内置 SDK")
            self._verify_digest(archive_path, str(manifest["archive_sha256"]))
            self._set_progress("extracting", "正在解压 Windows Runtime")
            self._extract_archive(
                archive_path,
                staging,
                total_bytes=int(manifest.get("installed_size_bytes") or 0),
            )
            executable = (staging / str(manifest["executable"])).resolve()
            launcher = (staging / str(manifest["launcher"])).resolve()
            if not executable.is_file() or staging.resolve() not in executable.parents:
                raise ValueError("Runtime 压缩包缺少声明的 Windows 可执行文件")
            if not launcher.is_file() or staging.resolve() not in launcher.parents:
                raise ValueError("Runtime 压缩包缺少声明的 Windows Job launcher")
            self._verify_authenticode(executable)
            self._verify_authenticode(launcher)
            self._self_check(launcher, executable)
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            destination = self._installed_version_dir()
            self._set_progress("installing", "正在发布 Windows Runtime")
            self._finalize_install_directory(staging, destination)
            self._write_current(manifest)
            self._cleanup_legacy_sdk(staging=staging)
            self._set_progress("ready", "可用", processed_bytes=0, total_bytes=0, progress=None)
        except _InstallCancelled:
            self._set_progress("missing", "安装已取消")
        except Exception as exc:  # noqa: BLE001
            logger.exception("DSH Runtime 安装失败")
            self._set_progress("failed", str(exc))
        finally:
            if staging.exists():
                self._remove_tree(staging, ignore_errors=True)
            with self._lock:
                self._worker = None

    def _finalize_install_directory(self, staging: Path, destination: Path) -> None:
        """有界发布已验证的目录，只重试 Windows 短时占用并响应安装 owner 取消。"""

        staging, destination = staging.resolve(), destination.resolve()
        for target in (staging, destination):
            self._assert_managed_path(target)
        if staging.parent != self.work_dir.resolve() or not staging.name.startswith(".sdk-"):
            raise ValueError("DSH 安装临时目录必须位于受管 work 目录内")
        if destination != self._installed_version_dir():
            raise ValueError("DSH 安装目标必须是固定 sdk 目录")
        with self._lock:
            if self._leases:
                raise ValueError("DSH Runtime 正在被子 Agent 使用，不能修复")
        if self._cancel.is_set():
            raise _InstallCancelled
        if destination.exists():
            self._remove_tree(destination)
        deadline = time.monotonic() + self.config.dsh.install_finalize_timeout_seconds
        while True:
            if self._cancel.is_set():
                raise _InstallCancelled
            try:
                os.replace(staging, destination)
                return
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in {5, 32}:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                if self._cancel.wait(min(remaining, self.config.dsh.filesystem_retry_delay_seconds)):
                    raise _InstallCancelled from exc

    def _load_bundled_manifest(self) -> tuple[dict[str, Any], Path]:
        """读取 EXE内置 manifest，并安全解析同目录 ZIP路径。"""

        manifest_path = self.bundle_dir / "sdk.manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("当前 MW 构建缺少内置 SDK manifest")
        parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("内置 DSH Runtime manifest必须是 JSON对象")
        if parsed.get("archive_file") != "sdk.zip":
            raise ValueError("内置 DSH SDK压缩包必须命名为 sdk.zip")
        archive = (self.bundle_dir / str(parsed.get("archive_file") or "")).resolve()
        if self.bundle_dir not in archive.parents or not archive.is_file():
            raise FileNotFoundError("当前 MW 构建缺少内置 SDK ZIP")
        return parsed, archive

    def _validate_manifest(self, manifest: dict[str, Any]) -> None:
        """拒绝版本、平台、架构或字段不属于当前 MW兼容集合的清单。"""

        required = {
            "version", "platform", "arch", "archive_file", "archive_sha256",
            "executable", "launcher", "cordis_configs", "launch_args",
        }
        missing = sorted(required - manifest.keys())
        if missing:
            raise ValueError(f"DSH Runtime 清单缺少字段: {', '.join(missing)}")
        if str(manifest["version"]) != self.config.dsh.runtime_version:
            raise ValueError("DSH Runtime 清单版本与当前 MW 不兼容")
        if str(manifest["platform"]).lower() not in {"windows", "win32"}:
            raise ValueError("DSH Runtime 清单不是 Windows 平台")
        if str(manifest["arch"]).lower() not in {"x64", "amd64"}:
            raise ValueError("DSH Runtime 清单不是 x64 架构")
        digest = str(manifest["archive_sha256"]).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("DSH Runtime 压缩包 SHA-256 无效")

    def _extract_archive(self, archive: Path, destination: Path, *, total_bytes: int) -> None:
        """逐块解压 ZIP、响应取消、报告真实字节并拒绝目录穿越。"""

        destination.mkdir(parents=True, exist_ok=False)
        root = destination.resolve()
        processed = 0
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                target = (root / entry.filename).resolve()
                if target != root and root not in target.parents:
                    raise ValueError("DSH Runtime 压缩包包含越界路径")
                if entry.is_dir():
                    self._windows_io_path(target).mkdir(parents=True, exist_ok=True)
                    continue
                io_target = self._windows_io_path(target)
                io_target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, io_target.open("wb") as output:
                    while True:
                        if self._cancel.is_set():
                            raise _InstallCancelled
                        chunk = source.read(_CHUNK_BYTES)
                        if not chunk:
                            break
                        output.write(chunk)
                        processed += len(chunk)
                        progress = round(processed * 100 / total_bytes, 1) if total_bytes else None
                        self._set_progress(
                            "extracting",
                            "正在解压 Windows Runtime",
                            processed_bytes=processed,
                            total_bytes=total_bytes,
                            progress=progress,
                        )

    def _verify_authenticode(self, executable: Path) -> None:
        """配置证书指纹时，使用 Windows Authenticode 验证发布者。"""

        expected = self.config.dsh.signer_thumbprint.replace(" ", "").upper()
        if not expected:
            return
        command = (
            "$s=Get-AuthenticodeSignature -LiteralPath $args[0];"
            "if($s.Status -ne 'Valid'){exit 2};"
            "$s.SignerCertificate.Thumbprint"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command, str(executable)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip().upper() != expected:
            raise ValueError("DSH Runtime Authenticode 发布者校验失败")

    def _self_check(self, launcher: Path, executable: Path) -> None:
        """执行不接触模型的版本探针，拒绝无法启动的产物。"""

        home = self.work_dir / f"self-check-{uuid4().hex}"
        home.mkdir(parents=True)
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {
                "COMSPEC", "PATH", "PATHEXT", "SYSTEMDRIVE", "SYSTEMROOT",
                "TEMP", "TMP", "WINDIR",
            }
        }
        env.update({"DSH_HOME": str(home), "DSH_TELEMETRY_DISABLED": "1"})
        try:
            result = subprocess.run(
                [str(launcher), str(executable), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
                env=env,
            )
            if result.returncode != 0:
                raise ValueError("DSH Runtime 本地自检失败")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def _write_current(self, manifest: dict[str, Any]) -> None:
        """原子发布当前版本指针。"""

        temporary = self.current_file.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({
                "version": manifest["version"],
                "directory": "sdk",
                "executable": manifest["executable"],
                "launcher": manifest["launcher"],
            }),
            encoding="utf-8",
        )
        os.replace(temporary, self.current_file)

    def _runtime_executable(self) -> Path | None:
        """解析已安装且仍位于固定 SDK 目录中的 Runtime。"""

        if not self.current_file.is_file():
            return None
        try:
            current = json.loads(self.current_file.read_text(encoding="utf-8"))
            if current.get("version") != self.config.dsh.runtime_version:
                return None
            if current.get("directory") != "sdk":
                return None
            version_dir = self._installed_version_dir()
            executable = (version_dir / str(current["executable"])).resolve()
            if version_dir.resolve() not in executable.parents or not executable.is_file():
                return None
            return executable
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def _installed_version_dir(self) -> Path:
        """返回固定 sdk 目录；真实兼容版本保留在 manifest 与 current metadata。"""

        return (self.root / "sdk").resolve()

    def _legacy_sdk_paths(self, *, staging: Path | None = None) -> list[Path]:
        """只列出旧 versions 与已知 .sdk-* 临时目录，排除当前安装 owner。"""

        paths = [self.versions_dir] if self.versions_dir.exists() else []
        paths.extend(
            path for path in self.work_dir.glob(".sdk-*")
            if path.is_dir() and (staging is None or path.resolve() != staging.resolve())
        )
        return paths

    def _cleanup_legacy_sdk(self, *, staging: Path | None = None) -> None:
        """新 SDK 发布后清理明确受管的旧缓存；失败向安装 owner 传播。"""

        with self._lock:
            if self._leases:
                raise ValueError("DSH Runtime 正在被子 Agent 使用，不能清理")
        for path in self._legacy_sdk_paths(staging=staging):
            self._assert_managed_path(path)
            self._remove_tree(path)

    def _reconcile_status(self, *, update_working: bool = True) -> None:
        """以磁盘事实修正非运行中状态。"""

        if not update_working and self._progress["status"] in {
            "verifying", "extracting", "installing", "repairing", "cancelling", "failed",
        }:
            return
        if self._runtime_executable() is not None:
            if self._legacy_sdk_paths():
                self._set_progress("failed", "旧 SDK缓存或安装临时目录尚未清理，请修复安装")
            else:
                self._set_progress("ready", "可用")
        elif update_working or self._progress["status"] in _READY_STATES:
            self._set_progress("missing", "尚未安装")

    def _bundle_is_available(self) -> bool:
        """判断当前进程资源中是否同时存在固定 manifest与 ZIP。"""

        try:
            self._load_bundled_manifest()
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

    def _bundled_archive_size(self) -> int:
        """返回内置 SDK压缩包大小；开发环境缺失时返回零。"""

        try:
            _, archive = self._load_bundled_manifest()
            return archive.stat().st_size
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0

    def _set_progress(
        self,
        status: str,
        message: str,
        *,
        processed_bytes: int = 0,
        total_bytes: int = 0,
        progress: float | None = None,
    ) -> None:
        """在锁内发布一个完整、可轮询的状态快照。"""

        with self._lock:
            self._progress = {
                "status": status,
                "message": message,
                "processed_bytes": processed_bytes,
                "total_bytes": total_bytes,
                "progress": progress,
            }

    def _assert_managed_path(self, path: Path) -> None:
        """保证递归删除目标严格位于 DSH受管根目录下。"""

        resolved = path.resolve()
        root = self.root.resolve()
        if resolved == root or root not in resolved.parents:
            raise ValueError("拒绝操作 DSH受管根目录之外的路径")

    @staticmethod
    def _windows_io_path(path: Path) -> Path:
        """在 Windows 为受管绝对路径添加扩展前缀，解除 MAX_PATH 限制。"""

        resolved = path.resolve()
        if os.name == "nt" and not str(resolved).startswith("\\\\?\\"):
            return Path(f"\\\\?\\{resolved}")
        return resolved

    @classmethod
    def _remove_tree(cls, path: Path, *, ignore_errors: bool = False) -> None:
        """递归删除受管目录，并兼容其中超过 MAX_PATH 的 Node 依赖。"""

        shutil.rmtree(cls._windows_io_path(path), ignore_errors=ignore_errors)

    @staticmethod
    def _verify_digest(path: Path, expected: str) -> None:
        """流式计算文件 SHA-256。"""

        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(_CHUNK_BYTES), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected.lower():
            raise ValueError("DSH Runtime 压缩包 SHA-256 校验失败")

    @staticmethod
    def _directory_stats(path: Path) -> tuple[int, int]:
        """返回一个版本目录的真实字节数与文件数。"""

        if not path.is_dir():
            return 0, 0
        size = 0
        count = 0
        try:
            scan_root = DshRuntimePackageManager._windows_io_path(path)
            for item in scan_root.rglob("*"):
                if item.is_file():
                    size += item.stat().st_size
                    count += 1
        except OSError:
            return 0, 0
        return size, count


class _InstallCancelled(Exception):
    """内部取消信号，不作为安装错误展示。"""
