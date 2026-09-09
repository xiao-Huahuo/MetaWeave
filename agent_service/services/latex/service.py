"""
LaTeX 运行时安装、检测与编译服务。

使用说明:
REST 与 gRPC 共同实例化 `LatexService`。服务优先使用 MetaWeave 托管的
MiKTeX，回退系统 PATH；编译产物固定写入活动知识库 `.mw/latex`，不会修改
或清理用户 `.tex` 源文件。安装操作仅在用户显式请求后启动后台线程。
"""

from __future__ import annotations

import hashlib
import locale
import logging
import os
import re
import shutil
import subprocess
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

try:
    import winreg
except ImportError:  # pragma: no cover - 项目仅发布 Windows，此处便于非 Windows 静态检查
    winreg = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

MIKTEX_SETUP_URL = (
    "https://miktex.org/download/ctan/systems/win32/miktex/setup/windows-x64/"
    "miktexsetup-5.5.0%2B1763023-x64.zip"
)
MIKTEX_SETUP_SHA256 = "0571e90f6d94353089b4f189fd82a532f9fe559a388c7e7f1102b14b3c1ae27d"
TEX_ROOT_PATTERN = re.compile(r"^\s*%\s*!?TEX\s+root\s*=\s*(.+?)\s*$", re.IGNORECASE)
TEX_PROGRAM_PATTERN = re.compile(r"^\s*%\s*!?TEX\s+(?:TS-)?program\s*=\s*(.+?)\s*$", re.IGNORECASE)
LATEX_ERROR_PATTERN = re.compile(r"^(.*?\.tex):(\d+):\s*(.+)$", re.IGNORECASE)
SUPPORTED_ENGINES = ("pdflatex", "xelatex", "lualatex")


class LatexService:
    """管理一个进程共享的 MiKTeX 安装任务，并为每个知识库编译 LaTeX。"""

    _state_lock = threading.RLock()
    _install_cancel = threading.Event()
    _install_process: subprocess.Popen[bytes] | None = None
    _install_state: dict[str, Any] = {
        "status": "idle",
        "stage": "idle",
        "progress": 0,
        "downloaded_bytes": 0,
        "total_bytes": None,
        "indeterminate": False,
        "message": "",
    }

    def __init__(self, *, config: Any, settings_service: Any, knowledge_library_service: Any) -> None:
        """保存共用服务依赖并派生固定的托管目录。"""

        self.config = config
        self.settings_service = settings_service
        self.knowledge_library_service = knowledge_library_service
        self.runtime_root = Path(config.storage.base_data_dir).expanduser().resolve() / "latex"
        self.managed_install_dir = self.runtime_root / "miktex"
        self.managed_config_dir = self.runtime_root / "config"
        self.managed_data_dir = self.runtime_root / "data"
        self.repository_dir = self.runtime_root / "repository"
        self.temp_dir = self.runtime_root / "temp"
        self.managed_marker = self.runtime_root / ".metaweave-managed"

    def get_status(self) -> dict[str, Any]:
        """返回安装任务状态和当前可用编译器信息。"""

        with self._state_lock:
            install_state = dict(self._install_state)
        toolchain = self._discover_toolchain()
        if install_state["status"] in {"downloading", "installing", "cancelling", "failed"}:
            return {
                **install_state,
                "source": toolchain.get("source", "none") if toolchain else "none",
                "managed": bool(toolchain and toolchain.get("source") == "managed"),
                "runtime_path": str(self.runtime_root),
            }
        if not toolchain:
            return {
                "status": "missing",
                "stage": "idle",
                "progress": 0,
                "downloaded_bytes": 0,
                "total_bytes": None,
                "indeterminate": False,
                "message": "未检测到 LaTeX 编译器",
                "source": "none",
                "managed": False,
                "distribution": "",
                "version": "",
                "compiler_path": "",
                "latexmk_path": "",
                "default_engine": "",
                "runtime_path": str(self.runtime_root),
            }
        default_engine = self._default_engine(toolchain)
        compiler_path = str(toolchain[default_engine])
        version = self._read_version(compiler_path)
        return {
            "status": "ready",
            "stage": "ready",
            "progress": 100,
            "message": "LaTeX 编译环境已就绪",
            "source": toolchain["source"],
            "managed": toolchain["source"] == "managed",
            "distribution": "MiKTeX" if "miktex" in version.lower() else "TeX",
            "version": version,
            "compiler_path": compiler_path,
            "latexmk_path": str(toolchain.get("latexmk") or ""),
            "default_engine": default_engine,
            "runtime_path": str(self.runtime_root),
        }

    def get_management_status(self) -> dict[str, Any]:
        """返回编译管理区所需的来源、发行版、引擎、路径和真实磁盘占用。"""

        status = self.get_status()
        toolchain = self._discover_toolchain()
        if toolchain:
            distribution_path = (
                self.managed_install_dir
                if toolchain["source"] == "managed"
                else self._system_distribution_root(Path(toolchain["bin_dir"]))
            )
        else:
            distribution_path = self.managed_install_dir
        size_bytes, file_count = self._directory_stats(distribution_path)
        engines = [
            {
                "name": engine,
                "available": bool(toolchain and toolchain.get(engine)),
                "path": str(toolchain.get(engine) or "") if toolchain else "",
                "default": status.get("default_engine") == engine,
            }
            for engine in SUPPORTED_ENGINES
        ]
        return {
            **status,
            "distribution_path": str(distribution_path),
            "size_bytes": size_bytes,
            "file_count": file_count,
            "engines": engines,
            "paths": {
                "runtime": str(self.runtime_root),
                "install": str(self.managed_install_dir),
                "repository": str(self.repository_dir),
                "config": str(self.managed_config_dir),
                "data": str(self.managed_data_dir),
                "temp": str(self.temp_dir),
            },
        }

    def compile_file(self, *, user_id: str, path: str) -> dict[str, Any]:
        """安全编译一个知识库内 `.tex` 文件并返回现有 PDF 预览 payload。"""

        knowledge_root = self._knowledge_root(user_id=user_id)
        source_path = self._resolve_library_path(knowledge_root=knowledge_root, relative_path=path)
        if source_path.suffix.lower() != ".tex" or not source_path.is_file():
            raise ValueError("只能编译知识库内存在的 .tex 文件")
        root_document = self.resolve_root_document(source_path=source_path, knowledge_root=knowledge_root)
        toolchain = self._discover_toolchain()
        if not toolchain:
            raise RuntimeError("未检测到 LaTeX 编译环境，请先安装 MiKTeX")
        engine = self.resolve_engine(root_document=root_document, toolchain=toolchain)

        root_relative = root_document.relative_to(knowledge_root).as_posix()
        build_key = hashlib.sha256(root_relative.encode("utf-8")).hexdigest()[:16]
        output_dir = (knowledge_root / ".mw" / "latex" / build_key).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        environment = self._compiler_environment(bin_dir=Path(str(toolchain["bin_dir"])))
        command = self._build_compile_command(
            toolchain=toolchain,
            engine=engine,
            root_document=root_document,
            output_dir=output_dir,
        )
        return_code, output = self._execute(
            command,
            cwd=root_document.parent,
            env=environment,
            timeout=120,
        )
        if not toolchain.get("latexmk") and return_code == 0:
            second_code, second_output = self._execute(
                command,
                cwd=root_document.parent,
                env=environment,
                timeout=120,
            )
            return_code = second_code
            output = f"{output}\n{second_output}".strip()

        pdf_path = output_dir / f"{root_document.stem}.pdf"
        if return_code != 0 or not pdf_path.is_file():
            log_path = output_dir / f"{root_document.stem}.log"
            if log_path.is_file():
                log_output = self._decode_output(log_path.read_bytes())
                if log_output and log_output not in output:
                    output = f"{output}\n\n--- {engine} log ---\n{log_output}".strip()
            errors = self._parse_errors(output)
            return {
                "success": False,
                "path": path,
                "root_path": root_relative,
                "engine": engine,
                "output": output,
                "errors": errors,
                "preview": None,
            }
        preview_path = pdf_path.relative_to(knowledge_root).as_posix()
        preview = self.knowledge_library_service.preview_file(user_id=user_id, path=preview_path)
        return {
            "success": True,
            "path": path,
            "root_path": root_relative,
            "engine": engine,
            "output": output,
            "errors": self._parse_errors(output),
            "preview": preview,
        }

    def resolve_root_document(self, *, source_path: Path, knowledge_root: Path) -> Path:
        """解析 `%!TeX root`，并拒绝知识库外部路径。"""

        lines = source_path.read_text(encoding="utf-8").splitlines()[:50]
        for line in lines:
            match = TEX_ROOT_PATTERN.match(line)
            if not match:
                continue
            raw_root = match.group(1).strip().strip('"\'')
            candidate = (source_path.parent / raw_root).resolve()
            self._assert_within(candidate, knowledge_root, "主文档必须位于当前知识库内")
            if candidate.suffix.lower() != ".tex" or not candidate.is_file():
                raise ValueError("%!TeX root 指向的主文档不存在")
            return candidate
        return source_path.resolve()

    def resolve_engine(self, *, root_document: Path, toolchain: dict[str, str]) -> str:
        """读取主文档编译器声明；未声明时优先选择 LaTeX Workshop 默认的 pdfLaTeX。"""

        aliases = {"pdftex": "pdflatex", "xetex": "xelatex", "luatex": "lualatex"}
        for line in root_document.read_text(encoding="utf-8").splitlines()[:50]:
            match = TEX_PROGRAM_PATTERN.match(line)
            if not match:
                continue
            requested = match.group(1).strip().lower().split()[0]
            engine = aliases.get(requested, requested)
            if engine not in SUPPORTED_ENGINES:
                raise ValueError(f"不支持的 LaTeX 编译器声明: {requested}")
            if not toolchain.get(engine):
                raise ValueError(f"当前环境没有安装文档要求的 {engine}")
            return engine
        return self._default_engine(toolchain)

    @staticmethod
    def _default_engine(toolchain: dict[str, str]) -> str:
        """按 pdfLaTeX、XeLaTeX、LuaLaTeX 顺序选择首个可用引擎。"""

        for engine in SUPPORTED_ENGINES:
            if toolchain.get(engine):
                return engine
        raise RuntimeError("未检测到可用的 LaTeX 编译器")

    def start_install(self) -> dict[str, Any]:
        """在用户显式请求后启动唯一的后台 MiKTeX 安装任务。"""

        if os.name != "nt":
            raise ValueError("MetaWeave 托管 MiKTeX 自动安装目前仅支持 Windows")
        with self._state_lock:
            if self._install_state["status"] in {"downloading", "installing", "cancelling"}:
                return dict(self._install_state)
            if self._discover_toolchain():
                return self.get_status()
            self._install_cancel.clear()
            self._set_install_state("downloading", "setup", 0, "正在下载 MiKTeX 安装工具")
            thread = threading.Thread(target=self._install_worker, name="latex-runtime-install", daemon=True)
            thread.start()
            return dict(self._install_state)

    def cancel_install(self) -> dict[str, Any]:
        """取消当前下载或终止 Setup Utility 子进程。"""

        with self._state_lock:
            if self._install_state["status"] not in {"downloading", "installing"}:
                return dict(self._install_state)
            self._install_cancel.set()
            self._set_install_state("cancelling", "cancel", self._install_state["progress"], "正在取消安装")
            process = self._install_process
        if process and process.poll() is None:
            process.terminate()
        return dict(self._install_state)

    def uninstall_managed(self) -> dict[str, Any]:
        """只移除带 MetaWeave 标记的托管运行时，永不操作系统 TeX。"""

        if not self.managed_marker.is_file():
            raise ValueError("当前没有可由 MetaWeave 卸载的托管 MiKTeX")
        with self._state_lock:
            if self._install_state["status"] in {"downloading", "installing", "cancelling"}:
                raise ValueError("LaTeX 环境正在安装，不能卸载")
        self._assert_within(self.runtime_root, Path(self.config.storage.base_data_dir).resolve(), "托管目录无效")
        shutil.rmtree(self.runtime_root)
        self._set_install_state("idle", "idle", 0, "托管 MiKTeX 已卸载")
        return self.get_status()

    def build_install_arguments(self, *, setup_path: Path) -> list[str]:
        """构造不提权、不写注册表、不修改全局 PATH 的安装参数。"""

        return [
            str(setup_path),
            "--quiet",
            f"--local-package-repository={self.repository_dir}",
            "--package-set=basic",
            "--shared=no",
            "--modify-path=no",
            "--use-registry=no",
            f"--user-config={self.managed_config_dir}",
            f"--user-data={self.managed_data_dir}",
            f"--user-install={self.managed_install_dir}",
            "install",
        ]

    def _install_worker(self) -> None:
        """下载、校验、解压并运行官方 Setup Utility。"""

        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            self.repository_dir.mkdir(parents=True, exist_ok=True)
            archive_path = self.temp_dir / "miktexsetup.zip"
            self._download_file(url=MIKTEX_SETUP_URL, target=archive_path)
            if self._sha256(archive_path) != MIKTEX_SETUP_SHA256:
                raise RuntimeError("MiKTeX 安装工具 SHA-256 校验失败")
            extract_dir = self.temp_dir / "setup"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True)
            self._safe_extract(archive_path=archive_path, target_dir=extract_dir)
            setup_path = next(extract_dir.rglob("miktexsetup_standalone.exe"), None)
            if setup_path is None:
                setup_path = next(extract_dir.rglob("miktexsetup.exe"), None)
            if setup_path is None:
                raise RuntimeError("MiKTeX Setup Utility 压缩包缺少可执行文件")

            self._set_install_state(
                "installing", "packages", None, "正在下载 MiKTeX basic 宏包", indeterminate=True,
            )
            download_arguments = [
                str(setup_path),
                "--quiet",
                f"--local-package-repository={self.repository_dir}",
                "--package-set=basic",
                "download",
            ]
            self._run_setup(
                download_arguments,
                progress_path=self.repository_dir,
                stage="packages",
                message="正在下载 MiKTeX basic 宏包",
            )
            self._set_install_state(
                "installing", "runtime", None, "正在安装 MiKTeX 运行环境", indeterminate=True,
            )
            self._run_setup(
                self.build_install_arguments(setup_path=setup_path),
                progress_path=self.managed_install_dir,
                stage="runtime",
                message="正在安装 MiKTeX 运行环境",
            )
            self._enable_package_installer()
            self.managed_marker.write_text("MetaWeave managed MiKTeX\n", encoding="utf-8")
            if not self._discover_toolchain():
                raise RuntimeError("MiKTeX 安装完成，但未找到 xelatex")
            installed_bytes, _ = self._directory_stats(self.managed_install_dir)
            self._set_install_state(
                "ready",
                "ready",
                100,
                "MiKTeX 安装完成",
                downloaded_bytes=installed_bytes,
                total_bytes=installed_bytes,
            )
        except Exception as exc:
            if self._install_cancel.is_set():
                self._set_install_state("idle", "cancelled", 0, "安装已取消")
            else:
                logger.exception("MiKTeX 自动安装失败")
                self._set_install_state("failed", "failed", 0, str(exc))
        finally:
            with self._state_lock:
                self._install_process = None

    def _download_file(self, *, url: str, target: Path) -> None:
        """流式下载 Setup Utility，并报告真实字节进度和取消状态。"""

        partial = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "MetaWeave LaTeX Runtime"})
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:  # noqa: S310
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                if self._install_cancel.is_set():
                    raise RuntimeError("安装已取消")
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                progress = min(100, int(downloaded * 100 / total)) if total else None
                self._set_install_state(
                    "downloading",
                    "setup",
                    progress,
                    "正在下载 MiKTeX 安装工具",
                    downloaded_bytes=downloaded,
                    total_bytes=total or None,
                    indeterminate=not bool(total),
                )
        partial.replace(target)

    def _run_setup(
        self,
        command: list[str],
        *,
        progress_path: Path | None = None,
        stage: str = "runtime",
        message: str = "正在安装 MiKTeX",
    ) -> None:
        """运行可取消 Setup Utility，并持续报告阶段目录的真实落盘字节。"""

        environment = self._compiler_environment(bin_dir=self.managed_install_dir / "miktex" / "bin" / "x64")
        with self._state_lock:
            self._install_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.temp_dir,
                env=environment,
                shell=False,
            )
            process = self._install_process
        stop_progress = threading.Event()

        def _track_setup_bytes() -> None:
            while progress_path is not None and not stop_progress.is_set():
                downloaded_bytes, _ = self._directory_stats(progress_path)
                self._set_install_state(
                    "installing",
                    stage,
                    None,
                    message,
                    downloaded_bytes=downloaded_bytes,
                    total_bytes=None,
                    indeterminate=True,
                )
                stop_progress.wait(0.75)

        tracker = threading.Thread(target=_track_setup_bytes, daemon=True)
        tracker.start()
        try:
            output, _ = process.communicate()
        finally:
            stop_progress.set()
            tracker.join(timeout=2)
        if self._install_cancel.is_set():
            raise RuntimeError("安装已取消")
        if process.returncode != 0:
            detail = self._decode_output(output)[-2000:]
            raise RuntimeError(f"MiKTeX Setup Utility 执行失败: {detail}")

    def _enable_package_installer(self) -> None:
        """启用 MiKTeX 缺失宏包自动安装，不弹出阻塞式控制台对话框。"""

        initexmf = self._find_managed_executable("initexmf.exe")
        if initexmf is None:
            return
        subprocess.run(
            [str(initexmf), "--set-config-value", "[MPM]AutoInstall=1"],
            cwd=self.runtime_root,
            env=self._compiler_environment(bin_dir=initexmf.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
            shell=False,
        )

    def _discover_toolchain(self) -> dict[str, str] | None:
        """依次发现托管 MiKTeX、系统 PATH 与 Windows 已注册的 MiKTeX。"""

        managed = {
            engine: str(self._find_managed_executable(f"{engine}.exe") or "")
            for engine in SUPPORTED_ENGINES
        }
        managed_default = next((Path(path) for path in managed.values() if path), None)
        if managed_default:
            return {
                "source": "managed",
                **managed,
                "latexmk": str(self._find_managed_executable("latexmk.exe") or ""),
                "bin_dir": str(managed_default.parent),
            }
        system = {engine: shutil.which(engine) or "" for engine in SUPPORTED_ENGINES}
        system_default = next((Path(path) for path in system.values() if path), None)
        if system_default:
            return {
                "source": "system",
                **system,
                "latexmk": shutil.which("latexmk") or "",
                "bin_dir": str(system_default.parent),
            }
        for install_root in self._system_install_roots():
            for bin_dir in (
                install_root / "miktex" / "bin" / "x64",
                install_root / "bin" / "x64",
                install_root / "bin",
            ):
                discovered = {
                    engine: str(bin_dir / f"{engine}.exe") if (bin_dir / f"{engine}.exe").is_file() else ""
                    for engine in SUPPORTED_ENGINES
                }
                if not any(discovered.values()):
                    continue
                latexmk = bin_dir / "latexmk.exe"
                return {
                    "source": "system",
                    **discovered,
                    "latexmk": str(latexmk) if latexmk.is_file() else "",
                    "bin_dir": str(bin_dir),
                }
        return None

    @staticmethod
    def _system_install_roots() -> list[Path]:
        """读取 MiKTeX 注册信息和固定安装位置，不依赖父进程 PATH。"""

        roots: list[Path] = []
        if winreg is not None:
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, r"Software\MiKTeX.org\MiKTeX") as base_key:
                        index = 0
                        while True:
                            try:
                                version = winreg.EnumKey(base_key, index)
                            except OSError:
                                break
                            index += 1
                            try:
                                with winreg.OpenKey(base_key, rf"{version}\Core") as core_key:
                                    value, _ = winreg.QueryValueEx(core_key, "UserInstall")
                            except OSError:
                                continue
                            roots.append(Path(str(value)).expanduser())
                except OSError:
                    continue
        for variable, suffix in (
            ("LOCALAPPDATA", Path("Programs") / "MiKTeX"),
            ("LOCALAPPDATA", Path("MiKTeX")),
            ("ProgramFiles", Path("MiKTeX")),
        ):
            base = os.environ.get(variable)
            if base:
                roots.append(Path(base) / suffix)
        return list(dict.fromkeys(root.resolve() for root in roots if root.is_dir()))

    def _find_managed_executable(self, filename: str) -> Path | None:
        """在固定托管目录内查找 MiKTeX 可执行文件。"""

        expected = self.managed_install_dir / "miktex" / "bin" / "x64" / filename
        if expected.is_file():
            return expected
        return next(self.managed_install_dir.rglob(filename), None) if self.managed_install_dir.exists() else None

    @staticmethod
    def _system_distribution_root(bin_dir: Path) -> Path:
        """从系统编译器 bin 目录推断 MiKTeX/TeX Live/TinyTeX 安装根目录。"""

        candidates = [
            parent
            for parent in (bin_dir, *bin_dir.parents)
            if parent.name.lower() in {"miktex", "texlive", "tinytex"}
        ]
        return candidates[-1] if candidates else bin_dir.parent

    @staticmethod
    def _directory_stats(path: Path) -> tuple[int, int]:
        """返回编译发行版真实字节数和文件数。"""

        if not path.exists():
            return 0, 0
        size_bytes = 0
        file_count = 0
        for item in path.rglob("*"):
            if not item.is_file():
                continue
            try:
                size_bytes += item.stat().st_size
                file_count += 1
            except OSError:
                continue
        return size_bytes, file_count

    def _build_compile_command(
        self,
        *,
        toolchain: dict[str, str],
        engine: str,
        root_document: Path,
        output_dir: Path,
    ) -> list[str]:
        """使用 latexmk 指定引擎并强制重建；缺少 latexmk 时直接运行目标引擎。"""

        if toolchain.get("latexmk"):
            latexmk_flag = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}[engine]
            return [
                toolchain["latexmk"],
                latexmk_flag,
                "-g",
                "-synctex=1",
                "-interaction=nonstopmode",
                "-file-line-error",
                "-halt-on-error",
                "-no-shell-escape",
                f"-outdir={output_dir}",
                root_document.name,
            ]
        return [
            toolchain[engine],
            "-synctex=1",
            "-interaction=nonstopmode",
            "-file-line-error",
            "-halt-on-error",
            "-no-shell-escape",
            f"-output-directory={output_dir}",
            root_document.name,
        ]

    def _compiler_environment(self, *, bin_dir: Path) -> dict[str, str]:
        """构造仅对子进程生效的 PATH、TEMP 与 Windows Perl locale 环境。"""

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ)
        environment["PATH"] = f"{bin_dir}{os.pathsep}{environment.get('PATH', '')}"
        environment["TEMP"] = str(self.temp_dir)
        environment["TMP"] = str(self.temp_dir)
        if os.name == "nt":
            for name in ("LC_ALL", "LC_CTYPE", "LANG"):
                environment.pop(name, None)
        return environment

    def _execute(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> tuple[int, str]:
        """执行无 shell 的编译命令并以兼容编码读取日志。"""

        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            return 124, f"LaTeX 编译超过 {timeout} 秒，已终止\n{self._decode_output(exc.stdout or b'')}"
        return completed.returncode, self._decode_output(completed.stdout)

    def _read_version(self, executable: str) -> str:
        """读取编译器首行版本，检测失败时仍保留可用状态。"""

        try:
            completed = subprocess.run(
                [executable, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=10,
                check=False,
                shell=False,
                env=self._compiler_environment(bin_dir=Path(executable).parent),
            )
            return self._decode_output(completed.stdout).splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError, IndexError):
            return "版本未知"

    @staticmethod
    def _decode_output(output: bytes | None) -> str:
        """按 UTF-8、系统首选编码顺序解码 Windows 工具输出。"""

        if not output:
            return ""
        for encoding in ("utf-8", locale.getpreferredencoding(False), "gb18030"):
            try:
                return output.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
        return output.decode("utf-8", errors="replace")

    @staticmethod
    def _parse_errors(output: str) -> list[dict[str, Any]]:
        """从 `-file-line-error` 日志提取可跳转的文件、行号和消息。"""

        errors: list[dict[str, Any]] = []
        for line in output.splitlines():
            match = LATEX_ERROR_PATTERN.match(line.strip())
            if match:
                errors.append({"file": match.group(1), "line": int(match.group(2)), "message": match.group(3)})
        return errors

    def _knowledge_root(self, *, user_id: str) -> Path:
        """返回用户活动知识库的绝对根路径。"""

        library = self.settings_service.get_active_knowledge_library(user_id=user_id)
        return Path(str(library["knowledge_dir"])).expanduser().resolve()

    def _resolve_library_path(self, *, knowledge_root: Path, relative_path: str) -> Path:
        """解析相对路径并阻止绝对路径和 `..` 逃逸。"""

        candidate = (knowledge_root / relative_path.replace("\\", "/")).resolve()
        self._assert_within(candidate, knowledge_root, "文件必须位于当前知识库内")
        return candidate

    @staticmethod
    def _assert_within(candidate: Path, root: Path, message: str) -> None:
        """验证候选路径属于指定根目录。"""

        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(message) from exc

    @staticmethod
    def _sha256(path: Path) -> str:
        """流式计算下载文件 SHA-256。"""

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _set_install_state(
        cls,
        status: str,
        stage: str,
        progress: int | None,
        message: str,
        *,
        downloaded_bytes: int = 0,
        total_bytes: int | None = None,
        indeterminate: bool = False,
    ) -> None:
        """原子更新安装状态；未知总量使用空百分比和真实落盘字节。"""

        with cls._state_lock:
            cls._install_state = {
                "status": status,
                "stage": stage,
                "progress": max(0, min(100, int(progress))) if progress is not None else None,
                "downloaded_bytes": max(0, int(downloaded_bytes)),
                "total_bytes": int(total_bytes) if total_bytes is not None else None,
                "indeterminate": bool(indeterminate),
                "message": message,
            }

    @classmethod
    def _safe_extract(cls, *, archive_path: Path, target_dir: Path) -> None:
        """拒绝 ZIP 路径穿越后解压官方 Setup Utility。"""

        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                destination = (target_dir / member.filename).resolve()
                cls._assert_within(destination, target_dir, "MiKTeX 安装包包含非法路径")
            archive.extractall(target_dir)
