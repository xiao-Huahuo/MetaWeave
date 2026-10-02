"""验证 DSH Runtime构建只接受 MW 锁定的上游源码与版本。

本测试不执行实际 Node构建，覆盖锁定制品校验、真实 Windows 长路径补包和 ZIP归档。
"""

import argparse
import json
import os
from pathlib import Path
from subprocess import CompletedProcess
import subprocess

import pytest

from scripts import build_dsh_windows_bundle as bundle


@pytest.mark.skipif(os.name != "nt", reason="真实 Windows MAX_PATH 验证")
def test_hydrate_and_archive_real_long_runtime_package(tmp_path: Path) -> None:
    """真实长路径残包必须能删除补齐，ZIP 保留完整同版本运行时文件。"""

    required = Path("build/src/baggage/propagation/W3CBaggagePropagator.js")
    source = tmp_path / "source/node_modules/.pnpm/@opentelemetry+core@2.10.0/node_modules/@opentelemetry/core"
    closure = tmp_path / "runtime"
    padding = "p" * max(1, 230 - len(str(closure / "node_modules" / "plugin" / "node_modules/@opentelemetry/core")))
    target = closure / "node_modules" / ("plugin" + padding) / "node_modules/@opentelemetry/core"

    def io_path(path: Path) -> Path:
        """仅用于创建确实超过 MAX_PATH 的 fixture，不借用被测修复。"""

        return Path("\\\\?\\" + str(path.resolve()))

    for package in (source, target):
        io_path(package).mkdir(parents=True)
        io_path(package / "package.json").write_text(
            json.dumps({"name": "@opentelemetry/core", "version": "2.10.0"}), encoding="utf-8",
        )
    io_path(source / required).parent.mkdir(parents=True)
    io_path(source / required).write_text("module.exports = {};", encoding="utf-8")
    stale = target / required.with_suffix(".d.ts")
    assert len(str(stale)) > 260
    io_path(stale).parent.mkdir(parents=True)
    io_path(stale).write_text("export {};", encoding="utf-8")

    try:
        bundle.hydrate_runtime_node_package(
            dsh_root=tmp_path / "source", runtime_closure=closure,
            package_name="@opentelemetry/core", required_file=required.as_posix(),
        )
        assert io_path(target / required).read_text(encoding="utf-8") == "module.exports = {};"
        assert not io_path(stale).exists()
        io_closure = bundle.windows_io_path(closure)
        archive = tmp_path / "long-runtime.zip"
        with bundle.zipfile.ZipFile(archive, "w") as package:
            for path in bundle.runtime_files(io_closure):
                package.write(path, path.relative_to(io_closure).as_posix())
        with bundle.zipfile.ZipFile(archive) as package:
            assert package.read((target / required).relative_to(closure).as_posix()) == b"module.exports = {};"
    finally:
        bundle.remove_build_tree(tmp_path / "source")
        bundle.remove_build_tree(closure)


@pytest.mark.skipif(os.name != "nt", reason="真实 Windows extended path 验证")
def test_remove_build_tree_accepts_already_extended_path(tmp_path: Path) -> None:
    """上层已转换的 Windows 路径不能再被清理器添加第二个前缀。"""

    tree = tmp_path / "extended-cleanup"
    tree.mkdir()
    (tree / "file.txt").write_text("temporary", encoding="utf-8")
    extended = Path("\\\\?\\" + str(tree.resolve()))
    bundle.remove_build_tree(extended)
    assert not tree.exists()


@pytest.mark.skipif(os.name != "nt", reason="真实 Windows junction 边界验证")
def test_hydrate_rejects_package_junction_outside_runtime_closure(tmp_path: Path) -> None:
    """目录 junction 指向闭包外时拒绝补包，不能删除目标目录中的原文件。"""

    closure = tmp_path / "runtime"
    target = closure / "node_modules/@opentelemetry/core"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "package.json").write_text(
        json.dumps({"name": "@opentelemetry/core", "version": "2.10.0"}), encoding="utf-8",
    )
    witness = outside / "witness.txt"
    witness.write_text("must remain", encoding="utf-8")
    target.parent.mkdir(parents=True)
    subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(target), str(outside)],
        check=True, capture_output=True,
    )
    try:
        with pytest.raises(ValueError, match="闭包根"):
            bundle.hydrate_runtime_node_package(
                dsh_root=tmp_path / "source", runtime_closure=closure,
                package_name="@opentelemetry/core", required_file="build/required.js",
            )
        assert witness.read_text(encoding="utf-8") == "must remain"
    finally:
        # 仅删除 junction 本身；避免清理时跟随链接删除闭包外 fixture。
        os.rmdir(target)


def test_verify_upstream_accepts_only_locked_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """锁定提交和 Runtime版本同时匹配时返回构建元数据。"""

    lock = bundle.json.loads(bundle.UPSTREAM_LOCK.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        bundle.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, f"{lock['commit']}\n", ""),
    )

    assert bundle.verify_upstream(Path("dsh"), str(lock["runtime_version"])) == lock


@pytest.mark.parametrize("wrong_input", ["commit", "version"])
def test_verify_upstream_rejects_unlocked_input(
    monkeypatch: pytest.MonkeyPatch,
    wrong_input: str,
) -> None:
    """源码提交或 Runtime版本任一漂移时构建立即失败。"""

    lock = bundle.json.loads(bundle.UPSTREAM_LOCK.read_text(encoding="utf-8"))
    actual_commit = "0" * 40 if wrong_input == "commit" else str(lock["commit"])
    requested_version = "unlocked" if wrong_input == "version" else str(lock["runtime_version"])
    monkeypatch.setattr(
        bundle.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, f"{actual_commit}\n", ""),
    )

    with pytest.raises(RuntimeError):
        bundle.verify_upstream(Path("dsh"), requested_version)


def test_verify_bundle_files_requires_exact_locked_artifacts(tmp_path: Path) -> None:
    """EXE门禁只接受与锁定版本、大小和哈希完全一致的 manifest与 ZIP。"""

    lock = json.loads(bundle.UPSTREAM_LOCK.read_text(encoding="utf-8"))
    version = str(lock["runtime_version"])
    archive = tmp_path / "sdk.zip"
    archive.write_bytes(b"sdk")
    manifest = {
        "version": version,
        "source_commit": lock["commit"],
        "patch_sha256": bundle.sha256(bundle.MW_PATCH),
        "archive_file": archive.name,
        "archive_size_bytes": archive.stat().st_size,
        "archive_sha256": bundle.sha256(archive),
    }
    (tmp_path / "sdk.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )

    assert bundle.verify_bundle_files(tmp_path) == (
        archive.resolve(),
        tmp_path / "sdk.manifest.json",
    )
    archive.unlink()
    with pytest.raises(FileNotFoundError, match="缺少 DSH SDK ZIP"):
        bundle.verify_bundle_files(tmp_path)


def test_prepared_dsh_source_checks_out_lock_and_applies_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全新构建应克隆锁定提交、应用 MW补丁且不修改来源仓库。"""

    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
    (source / "demo.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "demo.txt"], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.name=MetaWeave", "-c", "user.email=build@metaweave.local", "commit", "-m", "base"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True,
    ).stdout.strip()
    lock_path = tmp_path / "upstream.json"
    lock_path.write_text(json.dumps({
        "repository": str(source), "commit": commit, "runtime_version": "test-v1",
    }), encoding="utf-8")
    patch_path = tmp_path / "mw.patch"
    patch_path.write_text(
        "diff --git a/demo.txt b/demo.txt\n"
        "index df967b9..b66ba06 100644\n"
        "--- a/demo.txt\n"
        "+++ b/demo.txt\n"
        "@@ -1 +1 @@\n"
        "-base\n"
        "+patched\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bundle, "UPSTREAM_LOCK", lock_path)
    monkeypatch.setattr(bundle, "MW_PATCH", patch_path)

    with bundle.prepared_dsh_source(source) as checkout:
        temporary_clone = checkout.parent
        assert (checkout / "demo.txt").read_text(encoding="utf-8") == "patched\n"
    assert not temporary_clone.exists()
    assert (source / "demo.txt").read_text(encoding="utf-8") == "base\n"


def test_hydrate_runtime_node_package_repairs_truncated_same_version_package(tmp_path: Path) -> None:
    """构建闭包缺文件时应从 pnpm store 复制同版本完整包，禁止发布半包。"""

    required = Path("build/src/baggage/propagation/W3CBaggagePropagator.js")
    source = tmp_path / "source" / "node_modules" / ".pnpm" / "@opentelemetry+core@2.10.0" / "node_modules" / "@opentelemetry" / "core"
    target = tmp_path / "runtime" / "node_modules" / "plugin" / "node_modules" / "@opentelemetry" / "core"
    for package in (source, target):
        package.mkdir(parents=True)
        (package / "package.json").write_text(
            json.dumps({"name": "@opentelemetry/core", "version": "2.10.0"}),
            encoding="utf-8",
        )
    (source / required).parent.mkdir(parents=True)
    (source / required).write_text("module.exports = {};", encoding="utf-8")

    bundle.hydrate_runtime_node_package(
        dsh_root=tmp_path / "source",
        runtime_closure=tmp_path / "runtime",
        package_name="@opentelemetry/core",
        required_file=required.as_posix(),
    )

    assert (target / required).is_file()


def test_checked_in_dsh_bundle_contains_complete_telemetry_runtime() -> None:
    """仓库内置 ZIP 必须通过 manifest 校验并包含两个曾缺失的运行时模块。"""

    archive, _manifest = bundle.verify_bundle_files(bundle.PROJECT_ROOT / "resources" / "dsh" / "sdk")
    required = {
        "runtime/node/node_modules/@deepseek-ai/dsh-session-telemetry-otel/node_modules/"
        "@opentelemetry/core/build/src/baggage/propagation/W3CBaggagePropagator.js",
        "runtime/node/node_modules/@deepseek-ai/dsh-session-telemetry-otel/node_modules/"
        "@opentelemetry/resources/build/src/detectors/EnvDetector.js",
    }
    with bundle.zipfile.ZipFile(archive) as package:
        names = set(package.namelist())

    assert required <= names


@pytest.mark.parametrize("validation_fails", [False, True])
def test_build_replaces_versioned_archives_only_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, validation_fails: bool,
) -> None:
    """构建固定 sdk 文件；校验成功才清旧命名包，失败保留旧包供排查。"""

    lock = json.loads(bundle.UPSTREAM_LOCK.read_text(encoding="utf-8"))
    source, closure, output = tmp_path / "source", tmp_path / "closure", tmp_path / "output"
    source.mkdir()
    binary = closure / "node_modules/@deepseek-ai/dsh/lib/bin.js"
    binary.parent.mkdir(parents=True)
    binary.write_text("module.exports = {};", encoding="utf-8")
    node = tmp_path / "node.exe"
    node.write_bytes(b"node fixture")
    output.mkdir()
    old_files = [output / "dsh-runtime-win-x64-old.zip", output / "dsh-runtime-win-x64-old.manifest.json"]
    for path in old_files:
        path.write_bytes(b"old SDK")
    unrelated = output / "README.md"
    unrelated.write_text("retain", encoding="utf-8")
    monkeypatch.setattr(bundle, "verify_upstream", lambda *_args: lock)
    monkeypatch.setattr(bundle, "build_dsh", lambda _root: closure)
    monkeypatch.setattr(bundle, "compile_launcher", lambda path: path.write_bytes(b"launcher fixture"))
    monkeypatch.setattr(bundle.subprocess, "run", lambda *args, **kwargs: CompletedProcess(args[0], 0, "v24.19.0\n", ""))
    args = argparse.Namespace(dsh_root=source, output_dir=output, version=lock["runtime_version"], node_executable=node)

    if validation_fails:
        def reject(_output: Path) -> None:
            """复现发布校验失败，旧包仍需保留。"""

            raise ValueError("invalid SDK")

        monkeypatch.setattr(bundle, "verify_bundle_files", reject)
        with pytest.raises(ValueError, match="invalid SDK"):
            bundle.build_bundle(args)
        assert all(path.is_file() for path in old_files)
    else:
        archive, manifest = bundle.build_bundle(args)
        assert (archive.name, manifest.name) == ("sdk.zip", "sdk.manifest.json")
        assert not any(path.exists() for path in old_files)
        assert bundle.verify_bundle_files(output) == (archive.resolve(), manifest)
    assert unrelated.read_text(encoding="utf-8") == "retain"
