"""一键构建随 MetaWeave EXE发布的 DSH Windows Runtime SDK。

使用说明：在 Windows构建机执行本脚本；默认从 ``upstream.json`` 自动克隆锁定
提交并应用 MW补丁，也可使用本地仓库作为离线克隆源。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_SOURCE = PROJECT_ROOT / "native" / "dsh_job_launcher.c"
OVERLAY_SOURCE = PROJECT_ROOT / "resources" / "dsh" / "config" / "mw.patch.yml"
UPSTREAM_LOCK = PROJECT_ROOT / "resources" / "dsh" / "upstream.json"
MW_PATCH = PROJECT_ROOT / "resources" / "dsh" / "patches" / "mw-runtime.patch"
RUNTIME_SUFFIXES = {
    ".js", ".cjs", ".mjs", ".json", ".node", ".wasm", ".html", ".css",
    ".svg", ".png", ".ico", ".woff", ".woff2", ".ttf", ".webmanifest", ".yml", ".yaml", ".dll",
}


def parse_args() -> argparse.Namespace:
    """解析 SDK生产参数；默认从锁文件仓库获取源码。"""

    lock = json.loads(UPSTREAM_LOCK.read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsh-root", type=Path)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "resources" / "dsh" / "sdk")
    parser.add_argument("--version", default=str(lock["runtime_version"]))
    parser.add_argument("--node-executable", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    """流式计算一个发行文件的 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path) -> None:
    """执行一个构建步骤并保留原始失败退出码。"""

    subprocess.run(command, cwd=cwd, check=True)


def windows_io_path(path: Path) -> Path:
    """为 Windows 文件 IO 保留或生成扩展路径，支持 UNC 且不重复添加前缀。"""

    if os.name != "nt":
        return path
    resolved = str(path.resolve())
    if resolved.startswith("\\\\?\\"):
        return Path(resolved)
    if resolved.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + resolved[2:])
    return Path("\\\\?\\" + resolved)


def remove_build_tree(root: Path) -> None:
    """可靠删除含长路径和 Git只读文件的 Windows临时构建树。"""

    def make_writable(function, path, error) -> None:
        """只为删除本次临时树解除只读位，并忽略并发消失的文件。"""

        if isinstance(error, FileNotFoundError):
            return
        try:
            os.chmod(path, stat.S_IWRITE)
            function(path)
        except FileNotFoundError:
            return

    shutil.rmtree(windows_io_path(root), onexc=make_writable)


def verify_upstream(dsh_root: Path, requested_version: str) -> dict[str, object]:
    """校验构建输入严格对应 MW 锁定的 DSH 提交和 Runtime版本。"""

    lock = json.loads(UPSTREAM_LOCK.read_text(encoding="utf-8"))
    actual_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=dsh_root, capture_output=True, text=True, check=True,
    ).stdout.strip()
    if actual_commit != lock["commit"]:
        raise RuntimeError(f"DSH源码版本不匹配: 期望 {lock['commit']}，实际 {actual_commit}")
    if requested_version != lock["runtime_version"]:
        raise RuntimeError(
            f"Runtime版本不匹配: 期望 {lock['runtime_version']}，实际 {requested_version}"
        )
    return lock


@contextmanager
def prepared_dsh_source(source_root: Path | None):
    """克隆锁定提交到临时目录并应用 MW补丁，不修改调用方的 DSH仓库。"""

    lock = json.loads(UPSTREAM_LOCK.read_text(encoding="utf-8"))
    if not MW_PATCH.is_file():
        raise FileNotFoundError(f"缺少 MW DSH补丁: {MW_PATCH}")
    repository = str(source_root.resolve()) if source_root else str(lock["repository"])
    temporary = Path(tempfile.mkdtemp(prefix="mw-dsh-source-"))
    checkout = temporary / "deepseek-harness"
    try:
        run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", "--no-tags", repository, str(checkout)],
            cwd=PROJECT_ROOT,
        )
        run(["git", "checkout", "--detach", str(lock["commit"])], cwd=checkout)
        verify_upstream(checkout, str(lock["runtime_version"]))
        run(["git", "apply", "--check", str(MW_PATCH)], cwd=checkout)
        run(["git", "apply", str(MW_PATCH)], cwd=checkout)
        yield checkout
    finally:
        # pnpm闭包可能超过 Win32 MAX_PATH；扩展长度前缀避免构建后遗留临时仓库。
        remove_build_tree(temporary)


def verify_bundle_files(bundle_dir: Path) -> tuple[Path, Path]:
    """验证 EXE构建将要收集的固定 manifest与 ZIP完整且互相匹配。"""

    lock = json.loads(UPSTREAM_LOCK.read_text(encoding="utf-8"))
    version = str(lock["runtime_version"])
    manifest_path = bundle_dir / "sdk.manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"缺少 DSH SDK manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != version or manifest.get("source_commit") != lock["commit"]:
        raise ValueError("DSH SDK manifest与 upstream.json 锁定版本不一致")
    if manifest.get("patch_sha256") != sha256(MW_PATCH):
        raise ValueError("DSH SDK manifest与当前 MW补丁不一致，请重新生产 SDK")
    if manifest.get("archive_file") != "sdk.zip":
        raise ValueError("DSH SDK manifest必须引用固定的 sdk.zip")
    archive = (bundle_dir / str(manifest.get("archive_file") or "")).resolve()
    if bundle_dir.resolve() not in archive.parents or not archive.is_file():
        raise FileNotFoundError("缺少 DSH SDK ZIP或 archive_file越界")
    if archive.stat().st_size != int(manifest.get("archive_size_bytes") or 0):
        raise ValueError("DSH SDK ZIP大小与 manifest不一致")
    if sha256(archive) != str(manifest.get("archive_sha256") or "").lower():
        raise ValueError("DSH SDK ZIP哈希与 manifest不一致")
    return archive, manifest_path


def runtime_files(root: Path):
    """迭代 Node闭包运行所需文件，排除源码、测试、声明与 sourcemap。"""

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = {part.casefold() for part in relative.parts}
        if parts & {"test", "tests", "benchmark", "bench", "examples", ".history"}:
            continue
        if path.name == "package.json" or path.suffix.casefold() in RUNTIME_SUFFIXES:
            yield path


def hydrate_runtime_node_package(
    *,
    dsh_root: Path,
    runtime_closure: Path,
    package_name: str,
    required_file: str,
) -> None:
    """用 pnpm 完整包补齐 Runtime 闭包中被追踪器裁残的同版本 Node 包。"""

    pnpm_root = windows_io_path(dsh_root) / "node_modules" / ".pnpm"
    runtime_closure = windows_io_path(runtime_closure)
    source_packages: dict[str, Path] = {}
    for package_json in pnpm_root.glob(f"*/node_modules/{package_name}/package.json"):
        payload = json.loads(package_json.read_text(encoding="utf-8"))
        source_packages[str(payload.get("version") or "")] = package_json.parent
    targets = list(runtime_closure.glob(f"node_modules/**/node_modules/{package_name}/package.json"))
    targets.extend(runtime_closure.glob(f"node_modules/{package_name}/package.json"))
    for package_json in targets:
        target = windows_io_path(package_json.parent)
        if runtime_closure not in target.parents:
            raise ValueError("Node Runtime 包目录越过闭包根，不能删除或复制")
        if (target / required_file).is_file():
            continue
        version = str(json.loads(package_json.read_text(encoding="utf-8")).get("version") or "")
        source = source_packages.get(version)
        if source is None or not (source / required_file).is_file():
            raise FileNotFoundError(f"Node Runtime 闭包缺少 {package_name}@{version}/{required_file}")
        remove_build_tree(target)
        shutil.copytree(source, target)


def build_dsh(dsh_root: Path) -> Path:
    """调用 DSH 构建链生成固定、自包含的 Node Runtime闭包。"""

    pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm")
    node = shutil.which("node.exe") or shutil.which("node")
    if pnpm is None or node is None:
        raise RuntimeError("Node与pnpm必须在 PATH")
    run([pnpm, "install", "--frozen-lockfile"], cwd=dsh_root)
    run([pnpm, "run", "build"], cwd=dsh_root)
    run([
        node, "--import", "tsx/esm", "scripts/build-exe-for-python-sdk.ts",
        "--targets=node24-win-x64", "--skip-build", "--node-only",
    ], cwd=dsh_root)
    return dsh_root / "python" / "sdk-runtime" / "src" / "deepseek_harness_runtime" / "runtime" / "node"


def compile_launcher(destination: Path) -> None:
    """使用 MSVC 编译不依赖额外 DLL的 Job Object launcher。"""

    compiler = shutil.which("cl.exe")
    if compiler is not None:
        object_file = destination.with_suffix(".obj")
        run([
            compiler, "/nologo", "/O2", "/W4",
            str(LAUNCHER_SOURCE), f"/Fo:{object_file}", f"/Fe:{destination}", "/link", "/SUBSYSTEM:CONSOLE",
        ], cwd=destination.parent)
        object_file.unlink(missing_ok=True)
        return
    gcc = shutil.which("gcc.exe")
    if gcc is None:
        raise RuntimeError("cl.exe或gcc.exe不在 PATH，无法构建 Windows Job launcher")
    run([gcc, str(LAUNCHER_SOURCE), "-municode", "-O2", "-Wall", "-Wextra", "-o", str(destination)], cwd=destination.parent)


def build_bundle(args: argparse.Namespace) -> tuple[Path, Path]:
    """组装 EXE将要内置的 ZIP和兼容清单。"""

    dsh_root = args.dsh_root.resolve()
    upstream = verify_upstream(dsh_root, args.version)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    node_executable = str(args.node_executable.resolve()) if args.node_executable else shutil.which("node.exe")
    if node_executable is None or not Path(node_executable).is_file():
        raise RuntimeError("node.exe 不在 PATH；构建受管 Runtime需要固定 Node 24")
    node_version = subprocess.run(
        [node_executable, "--version"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    required_node_major = int(upstream["node_major"])
    if not node_version.startswith(f"v{required_node_major}."):
        raise RuntimeError(f"受管 DSH Runtime要求 Node {required_node_major}，当前为 {node_version}")
    # hydration、遍历、stat 和 ZIP 写入共用同一扩展根，relative_to 不混用路径形式。
    runtime_closure = windows_io_path(build_dsh(dsh_root))
    hydrate_runtime_node_package(
        dsh_root=dsh_root,
        runtime_closure=runtime_closure,
        package_name="@opentelemetry/core",
        required_file="build/src/baggage/propagation/W3CBaggagePropagator.js",
    )
    hydrate_runtime_node_package(
        dsh_root=dsh_root,
        runtime_closure=runtime_closure,
        package_name="@opentelemetry/resources",
        required_file="build/src/detectors/EnvDetector.js",
    )
    if not (runtime_closure / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js").is_file():
        raise FileNotFoundError(f"DSH Node Runtime闭包不存在: {runtime_closure}")

    with tempfile.TemporaryDirectory(prefix="mw-dsh-bundle-") as temporary:
        staging = Path(temporary) / "payload"
        config_dir = staging / "config"
        config_dir.mkdir(parents=True)
        runtime_name = "node/node.exe"
        launcher_name = "dsh-job-launcher.exe"
        (staging / "node").mkdir(parents=True)
        shutil.copy2(node_executable, staging / runtime_name)
        shutil.copy2(OVERLAY_SOURCE, config_dir / "mw.patch.yml")
        compile_launcher(staging / launcher_name)
        for legal_name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            source = dsh_root / legal_name
            if source.is_file():
                shutil.copy2(source, staging / legal_name)

        archive = output_dir / "sdk.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(staging).as_posix())
            for path in runtime_files(runtime_closure):
                relative = path.relative_to(runtime_closure).as_posix()
                bundle.write(path, f"runtime/node/{relative}")

        installed_size = (
            sum(path.stat().st_size for path in staging.rglob("*") if path.is_file())
            + sum(path.stat().st_size for path in runtime_files(runtime_closure))
        )
        launch = [
            "{runtime}", "{root}/runtime/node/node_modules/@deepseek-ai/dsh/lib/bin.js",
            "--profile", "mw", "--patch", "{root}/config/mw.patch.yml",
        ]
        manifest = {
            "version": args.version,
            "source_repository": upstream["repository"],
            "source_commit": upstream["commit"],
            "patch_file": MW_PATCH.relative_to(PROJECT_ROOT).as_posix(),
            "patch_sha256": sha256(MW_PATCH),
            "platform": "windows",
            "arch": "x64",
            "archive_file": archive.name,
            "archive_sha256": sha256(archive),
            "archive_size_bytes": archive.stat().st_size,
            "installed_size_bytes": installed_size,
            "executable": runtime_name,
            "launcher": launcher_name,
            "cordis_configs": {
                "readonly": "config/mw.patch.yml",
                "sandbox": "config/mw.patch.yml",
                "full_access": "config/mw.patch.yml",
            },
            "launch_args": {
                "readonly": launch,
                "sandbox": launch,
                "full_access": launch,
            },
        }
        manifest_path = output_dir / "sdk.manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        verify_bundle_files(output_dir)
        # 固定包完整校验后才移除旧命名制品，防止失败构建先删掉可用包。
        for retired in output_dir.glob("dsh-runtime-win-x64-*"):
            if retired.is_file() and (retired.suffix == ".zip" or retired.name.endswith(".manifest.json")):
                if retired.resolve().parent != output_dir:
                    raise ValueError("旧 SDK制品路径越过输出目录")
                retired.unlink()
        return archive, manifest_path


def main() -> None:
    """一键生成并验证下一次 AgentService.exe构建必须携带的 SDK。"""

    args = parse_args()
    with prepared_dsh_source(args.dsh_root) as checkout:
        args.dsh_root = checkout
        archive, manifest = build_bundle(args)
    print(f"archive={archive}")
    print(f"manifest={manifest}")
    print(f"manifest_sha256={sha256(manifest)}")


if __name__ == "__main__":
    main()
