"""
LaTeX 运行时与编译服务回归测试。

使用说明:
验证系统/托管编译器发现、主文档解析、安全编译参数、PDF 预览复用和
MiKTeX 当前用户安装参数。测试使用假编译器，不下载或修改真实 MiKTeX。
"""

from __future__ import annotations

from pathlib import Path
import shutil
import zipfile
from types import SimpleNamespace

import pytest

import agent_service.services.latex.service as latex_module
from agent_service.services.latex.service import LatexService


class _SettingsStub:
    """向 LaTeX 服务提供固定的活动知识库。"""

    def __init__(self, knowledge_dir: Path) -> None:
        self.knowledge_dir = knowledge_dir

    def get_active_knowledge_library(self, *, user_id: str) -> dict[str, str]:  # noqa: ARG002
        """返回测试知识库根目录。"""

        return {"knowledge_dir": str(self.knowledge_dir)}


class _KnowledgeStub:
    """记录编译成功后请求的现有 PDF 预览路径。"""

    def __init__(self) -> None:
        self.preview_path = ""

    def preview_file(self, *, user_id: str, path: str) -> dict[str, object]:  # noqa: ARG002
        """返回与现有 KnowledgeLibraryService 相同形状的 PDF payload。"""

        self.preview_path = path
        return {
            "path": path,
            "kind": "pdf",
            "raw_url": f"/knowledge/files/raw?user_id=u1&path={path}",
            "pdf_pages": [],
            "mtime": "2026-08-25T00:00:00",
            "size": 4,
            "extension": ".pdf",
            "readonly": True,
        }


def _service(tmp_path: Path) -> tuple[LatexService, _KnowledgeStub, Path]:
    """创建使用临时运行目录和知识库的 LaTeX 服务。"""

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    knowledge = _KnowledgeStub()
    config = SimpleNamespace(storage=SimpleNamespace(base_data_dir=tmp_path / "runtime"))
    return (
        LatexService(
            config=config,
            settings_service=_SettingsStub(knowledge_dir),
            knowledge_library_service=knowledge,
        ),
        knowledge,
        knowledge_dir,
    )


def test_status_prefers_managed_toolchain_then_system(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """托管运行时存在时必须优先使用；不存在时才回退系统 PATH。"""

    service, _, _ = _service(tmp_path)
    managed_bin = service.managed_install_dir / "miktex" / "bin" / "x64"
    managed_bin.mkdir(parents=True)
    (managed_bin / "pdflatex.exe").write_bytes(b"exe")
    (managed_bin / "xelatex.exe").write_bytes(b"exe")
    (managed_bin / "lualatex.exe").write_bytes(b"exe")
    (managed_bin / "latexmk.exe").write_bytes(b"exe")
    monkeypatch.setattr(service, "_read_version", lambda path: "MiKTeX 25.12")
    monkeypatch.setattr(latex_module.shutil, "which", lambda name: f"C:/system/{name}.exe")

    managed = service.get_status()
    (managed_bin / "pdflatex.exe").unlink()
    (managed_bin / "xelatex.exe").unlink()
    (managed_bin / "lualatex.exe").unlink()
    (managed_bin / "latexmk.exe").unlink()
    system = service.get_status()

    assert managed["status"] == "ready"
    assert managed["source"] == "managed"
    assert managed["compiler_path"].startswith(str(service.managed_install_dir))
    assert system["source"] == "system"
    assert system["compiler_path"] == "C:/system/pdflatex.exe"
    assert system["default_engine"] == "pdflatex"


def test_system_miktex_is_discovered_outside_process_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正式 EXE 的 PATH 缺少 MiKTeX 时，仍应从 Windows 安装根目录发现编译器。"""

    service, _, _ = _service(tmp_path)
    install_root = tmp_path / "MiKTeX"
    bin_dir = install_root / "miktex" / "bin" / "x64"
    bin_dir.mkdir(parents=True)
    for filename in ("pdflatex.exe", "xelatex.exe", "latexmk.exe"):
        (bin_dir / filename).write_bytes(b"exe")
    monkeypatch.setattr(latex_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(service, "_system_install_roots", lambda: [install_root])

    toolchain = service._discover_toolchain()

    assert toolchain is not None
    assert toolchain["source"] == "system"
    assert toolchain["pdflatex"] == str(bin_dir / "pdflatex.exe")
    assert toolchain["xelatex"] == str(bin_dir / "xelatex.exe")
    assert toolchain["latexmk"] == str(bin_dir / "latexmk.exe")
    assert toolchain["bin_dir"] == str(bin_dir)


def test_compile_defaults_to_safe_pdflatex_recipe_and_forces_real_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """编译必须禁用 shell escape、输出到 `.mw/latex` 并复用现有 PDF payload。"""

    service, knowledge, knowledge_dir = _service(tmp_path)
    source = knowledge_dir / "paper.tex"
    source.write_text("\\documentclass{article}\n\\begin{document}OK\\end{document}\n", encoding="utf-8")
    monkeypatch.setattr(service, "_discover_toolchain", lambda: {
        "source": "system",
        "latexmk": "C:/tex/latexmk.exe",
        "pdflatex": "C:/tex/pdflatex.exe",
        "xelatex": "C:/tex/xelatex.exe",
        "lualatex": "C:/tex/lualatex.exe",
        "bin_dir": "C:/tex",
    })
    captured: dict[str, object] = {}

    def fake_execute(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, str]:
        """记录命令并生成最小 PDF 文件，模拟外部编译器。"""

        captured.update(command=command, cwd=cwd, env=env, timeout=timeout)
        out_arg = next(item for item in command if item.startswith("-outdir="))
        output_dir = Path(out_arg.split("=", 1)[1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "paper.pdf").write_bytes(b"%PDF")
        return 0, "paper.tex:1: compiled"

    monkeypatch.setattr(service, "_execute", fake_execute)

    result = service.compile_file(user_id="u1", path="paper.tex")

    command = captured["command"]
    assert isinstance(command, list)
    assert "-pdf" in command
    assert "-xelatex" not in command
    assert "-g" in command
    assert "-no-shell-escape" in command
    assert not any("shell-escape" in item and not item.startswith("-no-") for item in command)
    assert knowledge.preview_path.startswith(".mw/latex/")
    assert result["success"] is True
    assert result["preview"]["kind"] == "pdf"


@pytest.mark.parametrize(("directive", "expected_engine", "expected_flag"), [
    ("%!TeX program = xelatex", "xelatex", "-xelatex"),
    ("% !TeX TS-program = lualatex", "lualatex", "-lualatex"),
    ("%!TeX program = pdflatex", "pdflatex", "-pdf"),
])
def test_magic_program_selects_requested_available_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directive: str,
    expected_engine: str,
    expected_flag: str,
) -> None:
    """主文档 magic comment 应覆盖默认 pdfLaTeX，并保持安全/强制重建参数。"""

    service, _, knowledge_dir = _service(tmp_path)
    (knowledge_dir / "paper.tex").write_text(
        f"{directive}\n\\documentclass{{article}}\n\\begin{{document}}OK\\end{{document}}\n",
        encoding="utf-8",
    )
    toolchain = {
        "source": "system",
        "latexmk": "C:/tex/latexmk.exe",
        "pdflatex": "C:/tex/pdflatex.exe",
        "xelatex": "C:/tex/xelatex.exe",
        "lualatex": "C:/tex/lualatex.exe",
        "bin_dir": "C:/tex",
    }
    monkeypatch.setattr(service, "_discover_toolchain", lambda: toolchain)
    monkeypatch.setattr(service, "_execute", lambda *args, **kwargs: (1, "expected test stop"))

    result = service.compile_file(user_id="u1", path="paper.tex")

    assert result["engine"] == expected_engine
    command = service._build_compile_command(
        toolchain=toolchain,
        engine=result["engine"],
        root_document=knowledge_dir / "paper.tex",
        output_dir=knowledge_dir / ".mw" / "latex" / "test",
    )
    assert expected_flag in command
    assert "-g" in command


def test_failed_latexmk_summary_includes_real_log_diagnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """latexmk 失败缓存摘要必须补充 `.log`，并提取可跳转的源码错误。"""

    service, _, knowledge_dir = _service(tmp_path)
    (knowledge_dir / "paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    monkeypatch.setattr(service, "_discover_toolchain", lambda: {
        "source": "system", "latexmk": "latexmk", "pdflatex": "pdflatex",
        "xelatex": "xelatex", "lualatex": "lualatex", "bin_dir": "C:/tex",
    })

    def fake_failure(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, str]:  # noqa: ARG001
        output_dir = Path(next(item for item in command if item.startswith("-outdir=")).split("=", 1)[1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "paper.log").write_text(
            "paper.tex:12: Undefined control sequence.\nNo pages of output.\n",
            encoding="utf-8",
        )
        return 12, "Latexmk: Nothing to do. previous invocation failed."

    monkeypatch.setattr(service, "_execute", fake_failure)

    result = service.compile_file(user_id="u1", path="paper.tex")

    assert result["success"] is False
    assert "Undefined control sequence" in result["output"]
    assert result["errors"] == [{"file": "paper.tex", "line": 12, "message": "Undefined control sequence."}]


def test_magic_root_must_stay_inside_knowledge_library(tmp_path: Path) -> None:
    """`%!TeX root` 可以引用项目主文件，但不能逃逸知识库。"""

    service, _, knowledge_dir = _service(tmp_path)
    chapter_dir = knowledge_dir / "chapters"
    chapter_dir.mkdir()
    chapter = chapter_dir / "one.tex"
    chapter.write_text("%!TeX root = ../main.tex\nchapter", encoding="utf-8")
    (knowledge_dir / "main.tex").write_text("main", encoding="utf-8")

    assert service.resolve_root_document(source_path=chapter, knowledge_root=knowledge_dir) == knowledge_dir / "main.tex"

    chapter.write_text("%!TeX root = ../../outside.tex\nchapter", encoding="utf-8")
    with pytest.raises(ValueError, match="知识库"):
        service.resolve_root_document(source_path=chapter, knowledge_root=knowledge_dir)


def test_miktex_install_arguments_are_private_and_do_not_modify_global_path(tmp_path: Path) -> None:
    """托管安装必须使用当前用户目录、配置文件模式且不污染系统 PATH。"""

    service, _, _ = _service(tmp_path)

    arguments = service.build_install_arguments(setup_path=tmp_path / "miktexsetup.exe")
    flattened = " ".join(arguments)

    assert "--shared=no" in arguments
    assert "--modify-path=no" in arguments
    assert "--use-registry=no" in arguments
    assert f"--user-install={service.managed_install_dir}" in arguments
    assert "--package-set=basic" in arguments
    assert "--quiet" in arguments
    assert "install" == arguments[-1]


def test_miktex_unknown_total_reports_real_bytes_without_fake_percent(tmp_path: Path) -> None:
    """Setup Utility 总量未知阶段只报告实际目录字节和不确定进度。"""

    service, _, _ = _service(tmp_path)
    service._set_install_state(
        "installing",
        "packages",
        None,
        "正在下载 MiKTeX basic 宏包",
        downloaded_bytes=4096,
        total_bytes=None,
        indeterminate=True,
    )

    status = service.get_status()

    assert status["progress"] is None
    assert status["downloaded_bytes"] == 4096
    assert status["total_bytes"] is None
    assert status["indeterminate"] is True
    service._set_install_state("idle", "idle", 0, "")


def test_install_worker_downloads_verifies_and_installs_managed_miktex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """假官方包完整经过下载、哈希、仓库下载、私有安装和健康检测，不触碰真实网络。"""

    service, _, _ = _service(tmp_path)
    commands: list[list[str]] = []

    def fake_download(*, url: str, target: Path) -> None:
        """创建只含 Setup Utility 占位文件的测试 ZIP。"""

        assert url == latex_module.MIKTEX_SETUP_URL
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("miktexsetup_standalone.exe", b"setup")

    def fake_setup(command: list[str], **kwargs: object) -> None:  # noqa: ARG001
        """记录两个 setup 阶段，并在安装阶段创建健康检测文件。"""

        commands.append(command)
        if command[-1] == "install":
            bin_dir = service.managed_install_dir / "miktex" / "bin" / "x64"
            bin_dir.mkdir(parents=True)
            (bin_dir / "xelatex.exe").write_bytes(b"exe")
            (bin_dir / "pdflatex.exe").write_bytes(b"exe")
            (bin_dir / "latexmk.exe").write_bytes(b"exe")

    monkeypatch.setattr(service, "_download_file", fake_download)
    monkeypatch.setattr(service, "_sha256", lambda path: latex_module.MIKTEX_SETUP_SHA256)
    monkeypatch.setattr(service, "_run_setup", fake_setup)
    monkeypatch.setattr(service, "_enable_package_installer", lambda: None)
    service._install_cancel.clear()
    service._set_install_state("downloading", "setup", 1, "test")

    service._install_worker()

    assert [command[-1] for command in commands] == ["download", "install"]
    assert service.managed_marker.is_file()
    assert service.get_status()["status"] == "ready"


@pytest.mark.skipif(shutil.which("xelatex") is None, reason="本机没有可用于冒烟验证的 XeLaTeX")
def test_real_system_compiler_generates_managed_pdf_cache(tmp_path: Path) -> None:
    """有系统编译器的开发机实际执行一次最小 XeLaTeX，验证命令参数和 PDF 产物。"""

    service, knowledge, knowledge_dir = _service(tmp_path)
    (knowledge_dir / "smoke.tex").write_text(
        "\\documentclass{article}\n\\begin{document}MetaWeave LaTeX smoke\\end{document}\n",
        encoding="utf-8",
    )

    result = service.compile_file(user_id="u1", path="smoke.tex")

    assert result["success"] is True, result["output"]
    assert knowledge.preview_path.startswith(".mw/latex/")
    assert (knowledge_dir / knowledge.preview_path).read_bytes().startswith(b"%PDF")


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="本机没有可用于回归验证的 pdfLaTeX")
def test_real_mcm_template_uses_default_pdflatex_successfully(tmp_path: Path) -> None:
    """VS Code 可成功编译的 MCM 模板必须用默认 pdfLaTeX 在 MetaWeave 服务中通过。"""

    service, _, knowledge_dir = _service(tmp_path)
    shutil.copy2(Path("resources/knowledge/MCM-ICM.template.tex"), knowledge_dir / "MCM-ICM.template.tex")

    result = service.compile_file(user_id="u1", path="MCM-ICM.template.tex")

    assert result["success"] is True, result["output"]
    assert result["engine"] == "pdflatex"


def test_compiler_management_reports_distribution_source_location_size_and_engines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """编译管理详情必须解释编译器来源和实际磁盘信息。"""

    service, _, _ = _service(tmp_path)
    distribution_root = tmp_path / "MiKTeX"
    bin_dir = distribution_root / "miktex" / "bin" / "x64"
    bin_dir.mkdir(parents=True)
    for name in ("pdflatex.exe", "xelatex.exe", "latexmk.exe"):
        (bin_dir / name).write_bytes(name.encode("ascii"))
    monkeypatch.setattr(service, "_discover_toolchain", lambda: {
        "source": "system",
        "pdflatex": str(bin_dir / "pdflatex.exe"),
        "xelatex": str(bin_dir / "xelatex.exe"),
        "lualatex": "",
        "latexmk": str(bin_dir / "latexmk.exe"),
        "bin_dir": str(bin_dir),
    })
    monkeypatch.setattr(service, "_read_version", lambda path: "MiKTeX-pdfTeX 4.18 (MiKTeX 24.1)")

    result = service.get_management_status()

    assert result["source"] == "system"
    assert result["distribution"] == "MiKTeX"
    assert result["distribution_path"] == str(distribution_root)
    assert result["size_bytes"] == sum(len(name) for name in ("pdflatex.exe", "xelatex.exe", "latexmk.exe"))
    assert result["file_count"] == 3
    assert result["default_engine"] == "pdflatex"
    assert result["engines"][0]["name"] == "pdflatex"
    assert result["engines"][0]["available"] is True
    assert result["engines"][2]["available"] is False
