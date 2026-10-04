"""Regenerate canonical protobuf bindings without oversized generated files.

Run from any directory with python scripts/generate_grpc.py. grpc_tools compiles
the checked-in standard proto; this script preserves generated behavior and
package import paths while splitting stub, servicer, client and typing outputs.
"""

from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory

import grpc_tools
from grpc_tools import protoc

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "agent_service" / "api" / "grpc"
NOTICE = '"""Generated from agent_service.proto; regenerate with scripts/generate_grpc.py."""\n'


def write(path: Path, body: str) -> None:
    """Save generated source as UTF-8 and enforce the project line ceiling."""
    source = NOTICE + body.rstrip() + "\n"
    if len(source.splitlines()) >= 1000:
        raise RuntimeError(f"Generated module exceeds line limit: {path.name}")
    path.write_text(source, encoding="utf-8", newline="\n")


def package_imports(tree: ast.Module) -> None:
    """Keep protoc's message alias while qualifying its public package import."""
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.Import) and any(alias.name == "agent_service_pb2" for alias in node.names):
            tree.body[index] = ast.ImportFrom(module="agent_service.api.grpc", names=node.names, level=0)


def split_grpc(source: Path) -> None:
    """Preserve all generated standard and experimental interfaces in small modules."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    package_imports(tree)
    header_nodes = [node for node in tree.body if not isinstance(node, (ast.ClassDef, ast.FunctionDef))]
    header = "\n".join(ast.unparse(node) for node in header_nodes)
    filenames = {"AgentServiceStub": "_agent_service_stub", "AgentServiceServicer": "_agent_service_servicer",
                 "AgentService": "_agent_service_client"}
    facade = [header]
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            module = filenames[node.name]
            write(DESTINATION / f"{module}.py", header + "\n\n" + ast.unparse(node))
            facade.append(f"from agent_service.api.grpc.{module} import {node.name} as {node.name}")
        elif isinstance(node, ast.FunctionDef):
            if node.name == "add_AgentServiceServicer_to_server":
                # Concrete application servicers may omit auth only in isolated
                # unit helpers; registering one must never expose unsigned RPCs.
                guard = ast.parse('if hasattr(servicer, "_auth_service") and servicer._auth_service is None:\n    raise ValueError("AuthService is required for gRPC registration")').body[0]
                node.body.insert(0, guard)
            facade.append(ast.unparse(node))
    write(DESTINATION / "agent_service_pb2_grpc.py", "\n\n".join(facade))


def split_typing(source: Path) -> None:
    """Re-export typed protobuf messages without changing public type names."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    header = "\n".join(ast.unparse(node) for node in tree.body if not isinstance(node, ast.ClassDef))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    chunks: list[list[ast.ClassDef]] = [[]]
    used = 0
    for node in classes:
        count = len(ast.unparse(node).splitlines()) + 2
        if used + count > 700 and chunks[-1]:
            chunks.append([])
            used = 0
        chunks[-1].append(node)
        used += count
    facade = [header]
    for index, chunk in enumerate(chunks):
        imports = []
        for other_index, other in enumerate(chunks):
            if other_index != index:
                imports.append(f"from ._agent_service_types_{other_index} import " + ", ".join(node.name for node in other))
        write(DESTINATION / f"_agent_service_types_{index}.pyi", "\n\n".join(
            [header, "\n".join(imports), *(ast.unparse(node) for node in chunk)]))
        facade.extend(f"from ._agent_service_types_{index} import {node.name} as {node.name}" for node in chunk)
    write(DESTINATION / "agent_service_pb2.pyi", "\n".join(facade))


def main() -> None:
    """Compile the stable source schema and publish all package bindings together."""
    include = Path(grpc_tools.__file__).resolve().parent / "_proto"
    with TemporaryDirectory(prefix="metaweave-grpc-") as temporary:
        target = Path(temporary)
        result = protoc.main(["grpc_tools.protoc", f"-I{DESTINATION}", f"-I{include}",
                              f"--python_out={target}", f"--pyi_out={target}", f"--grpc_python_out={target}",
                              str(DESTINATION / "agent_service.proto")])
        if result:
            raise RuntimeError(f"protobuf generation failed with exit code {result}")
        messages = ast.parse((target / "agent_service_pb2.py").read_text(encoding="utf-8"))
        for node in ast.walk(messages):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "BuildTopDescriptorsAndMessages":
                node.args[1] = ast.Constant("agent_service.api.grpc.agent_service_pb2")
        write(DESTINATION / "agent_service_pb2.py", ast.unparse(messages))
        split_grpc(target / "agent_service_pb2_grpc.py")
        split_typing(target / "agent_service_pb2.pyi")


if __name__ == "__main__":
    main()
