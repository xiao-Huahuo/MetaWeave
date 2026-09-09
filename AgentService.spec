# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 构建配置 — 将后端、前端和 DSH SDK打包为单个 exe。

使用说明:
先构建 editor/dist,再执行 `pyinstaller AgentService.spec`。
构建产物输出到项目根目录的 dist/AgentService.exe。
默认 resources 由 Electron安装包外置携带；DSH SDK是例外，必须进入后端 exe。
"""

import atexit
from pathlib import Path
import shutil
import tempfile

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from scripts.build_dsh_windows_bundle import verify_bundle_files

# SPECPATH 由 PyInstaller 在 exec spec 前注入,指向 spec 文件所在目录
_project_root = Path(SPECPATH)  # noqa: F821
_paddlex_hiddenimports = (
    collect_submodules('paddlex.inference.pipelines')
    + collect_submodules('paddlex.inference.models')
)
_paddlex_config_data = collect_data_files('paddlex', includes=['configs/**/*.yaml'])


def _required_data_dir(relative_path: str) -> tuple[str, str]:
    """返回 PyInstaller datas 目录元组,并在目录缺失时给出明确错误。"""

    source = _project_root / relative_path
    if not source.is_dir():
        raise FileNotFoundError(
            f"Required build asset directory is missing: {source}. "
            f"Build it before running PyInstaller."
        )
    return (str(source), relative_path.replace("\\", "/"))


def _required_data_file(relative_path: str) -> tuple[str, str]:
    """返回根目录数据文件元组,并在文件缺失时中止构建。"""

    source = _project_root / relative_path
    if not source.is_file():
        raise FileNotFoundError(f"Required build asset file is missing: {source}")
    return (str(source), ".")


def _snapshot_required_data_dir(relative_path: str) -> tuple[str, str]:
    """复制易被并发构建改写的数据目录,供本次构建稳定读取。"""

    source, destination = _required_data_dir(relative_path)
    snapshot_root = Path(tempfile.mkdtemp(prefix="metaweave-pyinstaller-"))
    atexit.register(shutil.rmtree, snapshot_root, ignore_errors=True)
    snapshot = snapshot_root / relative_path
    shutil.copytree(source, snapshot)
    if not (snapshot / "index.html").is_file():
        raise FileNotFoundError(f"Frontend build snapshot is incomplete: {snapshot}")
    return (str(snapshot), destination)


def _required_dsh_sdk_bundle() -> tuple[str, str]:
    """验证固定 SDK制品后返回 PyInstaller目录映射，缺失或损坏立即失败。"""

    source = _project_root / 'resources' / 'dsh' / 'sdk'
    verify_bundle_files(source)
    return (str(source), 'resources/dsh/sdk')


a = Analysis(
    ['main.py'],
    pathex=[str(_project_root)],
    binaries=[],
    # 普通 resources/由 Electron外置携带；DSH SDK必须进入 EXE供首次使用时懒解压。
    # runtime/仍在首次运行时生成，不得写入安装目录。
    datas=[
        _snapshot_required_data_dir('editor/dist'),
        _required_data_dir('agent_service/core/db/alembic'),
        _required_data_file('alembic.ini'),
        _required_data_dir('agent_service/vendor/deepseek_harness'),
        _required_dsh_sdk_bundle(),
        *_paddlex_config_data,
    ],
    hiddenimports=['xlrd', 'torchvision', *_paddlex_hiddenimports],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest',
        'pip',
        'torchaudio',
        'nvidia',
        'caffe2',
        'grpcio_tools',
        'grpcio_tests',
        'mypy',
        'ruff',
        'IPython',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    a.zipfiles,
    name='AgentService',
    icon='editor/src/assets/icons/app.ico',
    console=True,
    debug=False,
)
