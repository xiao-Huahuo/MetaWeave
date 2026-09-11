"""Runtime debug endpoints."""

from __future__ import annotations

import inspect
import json
import tempfile
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from agent_service.api.grpc import agent_service_pb2
from agent_service.api.rest.deps import _require_agent, _require_knowledge_library_service
from agent_service.core.agent_config import AgentConfig, DEFAULT_BUSINESS_LIMITS
from agent_service.services.document_parsing import MINERU_SUPPORTED_SUFFIXES
from agent_service.services.memory.rag.chunk import chunk_text
from agent_service.services.memory.rag.frontmatter_bootstrap import FrontmatterBootstrapService
from agent_service.services.memory.rag.frontmatter_document import StructuredKnowledgeDocument
from agent_service.services.memory.rag.knowledge_ingestion import KnowledgeIngestionService

router = APIRouter()


@router.get("/debug/global-constants")
async def global_constants() -> JSONResponse:
    """返回当前 AgentConfig 的全部配置组、字段说明和值,仅供 debug 页面只读展示。"""

    payload = _collect_agent_config_constants(_require_agent().config)
    return JSONResponse(payload, headers={"Access-Control-Allow-Origin": "*"})


@router.get("/debug/runtime-apis")
async def runtime_apis(request: Request) -> JSONResponse:
    """Return the REST routes and gRPC methods exposed by the running backend."""

    config = _require_agent().config
    rest_base_url = _request_base_url(request)
    grpc_host = "0.0.0.0" if config.server.grpc_host == "[::]" else config.server.grpc_host
    grpc_address = f"{grpc_host}:{config.server.grpc_port}"
    apis = _collect_rest_apis(request=request, base_url=rest_base_url)
    grpc_runtime = getattr(request.app.state, "grpc_runtime", None)
    apis.extend(_collect_grpc_apis(address=grpc_address, running=bool(grpc_runtime and grpc_runtime.running)))
    return JSONResponse(
        {
            "apis": apis,
            "api_count": len(apis),
            "groups": [
                {"kind": "rest", "name": "REST API", "base_url": rest_base_url},
                {"kind": "grpc", "name": "gRPC API", "base_url": grpc_address},
            ],
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


def _collect_agent_config_constants(config: AgentConfig) -> dict[str, Any]:
    """动态枚举 AgentConfig 的 dataclass 配置组,不维护字段名或配置类白名单。"""

    configs: list[dict[str, Any]] = []
    constant_count = 0
    for config_field in fields(config):
        config_group = getattr(config, config_field.name)
        if not is_dataclass(config_group):
            continue
        group_fields = fields(config_group)
        group_description, field_descriptions = _parse_config_docstring(
            type(config_group),
            {field_info.name for field_info in group_fields},
        )
        constants = [
            {
                "name": field_info.name,
                "description": field_descriptions.get(field_info.name, ""),
                "type": _value_type_name(getattr(config_group, field_info.name)),
                "value": (
                    "***"
                    if any(secret in field_info.name.lower() for secret in ("api_key", "password", "token", "secret"))
                    and bool(getattr(config_group, field_info.name))
                    else _to_json_value(getattr(config_group, field_info.name))
                ),
            }
            for field_info in group_fields
        ]
        constant_count += len(constants)
        configs.append(
            {
                "key": config_field.name,
                "name": type(config_group).__name__,
                "description": group_description,
                "constants": constants,
            }
        )
    return {
        "config_count": len(configs),
        "constant_count": constant_count,
        "configs": configs,
    }


def _parse_config_docstring(
    config_type: type[Any],
    field_names: set[str],
) -> tuple[str, dict[str, str]]:
    """从配置类 docstring 提取类介绍与 ``field_name: 说明`` 字段文档。"""

    docstring = inspect.getdoc(config_type) or ""
    lines = docstring.splitlines()
    summary_lines: list[str] = []
    descriptions: dict[str, str] = {}
    active_field = ""
    reading_summary = True
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            reading_summary = False
            active_field = ""
            continue
        field_name, separator, description = line.partition(":")
        normalized_field_name = field_name.strip()
        if separator and normalized_field_name in field_names:
            active_field = normalized_field_name
            descriptions[active_field] = description.strip()
            reading_summary = False
            continue
        if active_field:
            descriptions[active_field] = f"{descriptions[active_field]} {line}".strip()
        elif reading_summary:
            summary_lines.append(line)
    return " ".join(summary_lines), descriptions


def _to_json_value(value: Any) -> Any:
    """递归转换 AgentConfig 字段值,确保 Path、Enum、集合和嵌套容器可 JSON 序列化。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _to_json_value(value.value)
    if is_dataclass(value):
        return {
            field_info.name: _to_json_value(getattr(value, field_info.name))
            for field_info in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_to_json_value(item) for item in sorted(value, key=str)]
    return str(value)


def _value_type_name(value: Any) -> str:
    """返回跨平台稳定的配置值类型名称,避免 WindowsPath/PosixPath 等实现差异。"""

    if isinstance(value, Path):
        return "Path"
    if isinstance(value, Enum):
        return type(value).__name__
    return type(value).__name__


@router.get("/debug/multimodal-ingestion")
async def multimodal_ingestion_observation(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="User ID"),
    path: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="Path relative to the active knowledge library"),
) -> JSONResponse:
    """Return the single-file multimodal ingestion observation without writing vector records."""

    try:
        payload = await run_in_threadpool(_build_multimodal_ingestion_observation, user_id=user_id, relative_path=path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"multimodal observation failed: {exc}") from exc
    return JSONResponse(payload, headers={"Access-Control-Allow-Origin": "*"})


def _build_multimodal_ingestion_observation(*, user_id: str, relative_path: str) -> dict[str, Any]:
    library_service = _require_knowledge_library_service()
    config = _require_agent().config
    source_root = library_service.get_active_root_path(user_id=user_id).resolve()
    source_path = (source_root / relative_path.replace("\\", "/").strip("/")).resolve()
    try:
        normalized_relative_path = source_path.relative_to(source_root).as_posix()
    except ValueError as exc:
        raise ValueError("path escapes knowledge_dir") from exc
    if not source_path.is_file():
        raise ValueError("source file not found")

    ocr_enabled = True
    vlm_config: dict[str, object] = {}
    if hasattr(library_service, "settings_service"):
        settings_service = library_service.settings_service
        if hasattr(settings_service, "is_ocr_enabled_for_user"):
            ocr_enabled = bool(settings_service.is_ocr_enabled_for_user(user_id=user_id))
        if hasattr(settings_service, "get_vlm_config"):
            vlm_config = settings_service.get_vlm_config(user_id=user_id)

    try:
        structured_payload = library_service.read_frontmatter_payload_for_file(
            user_id=user_id,
            path=normalized_relative_path,
        )
        current_hash = FrontmatterBootstrapService._hash_file(source_path)
        metadata = structured_payload.get("metadata") if isinstance(structured_payload.get("metadata"), dict) else {}
        expected_engine = "mineru" if bool(vlm_config.get("enabled")) and source_path.suffix.lower() in MINERU_SUPPORTED_SUFFIXES else "local"
        if (
            int(structured_payload.get("schema_version") or 1) < 2
            or structured_payload.get("source_hash") != current_hash
            or metadata.get("parser_engine") != expected_engine
        ):
            raise ValueError("stale projection")
    except ValueError:
        with tempfile.TemporaryDirectory(prefix="metaweave_multimodal_observe_") as temp_dir:
            frontmatter_root = Path(temp_dir) / "frontmatter"
            markdown_root = Path(temp_dir) / "md"
            _, output_path = FrontmatterBootstrapService(
                config=config,
                ocr_enabled=ocr_enabled,
                vlm_config=vlm_config,
                online_enabled=bool(vlm_config.get("enabled")),
            ).build_frontmatter_file(
                source_path=source_path,
                knowledge_dir=source_root,
                frontmatter_dir=frontmatter_root,
                markdown_dir=markdown_root,
                supported_suffixes=set(config.constants.knowledge_supported_suffixes),
            )
            structured_payload = json.loads(output_path.read_text(encoding="utf-8"))
    document = StructuredKnowledgeDocument.from_dict(structured_payload)

    semantic_chunks: list[dict[str, Any]] = []
    overlap_chunks: list[dict[str, Any]] = []
    global_chunk_index = 0
    for section_index, section in enumerate(structured_payload.get("sections", [])):
        if not isinstance(section, dict):
            continue
        content = str(section.get("content") or "")
        semantic_chunks.append(
            {
                "index": section_index,
                "section_id": str(section.get("section_id") or ""),
                "heading": str(section.get("heading") or ""),
                "title_path": section.get("title_path", []),
                "start_char": int(section.get("start_char") or 0),
                "end_char": int(section.get("end_char") or 0),
                "char_count": len(content),
                "content": content,
            }
        )
        previous_end = 0
        for chunk in chunk_text(
            text=content,
            chunk_size=config.memory.chunk_size,
            chunk_overlap=config.memory.chunk_overlap,
        ):
            overlap_chars = max(0, previous_end - chunk.start_char) if chunk.index > 0 else 0
            overlap_chunks.append(
                {
                    "index": global_chunk_index,
                    "section_index": section_index,
                    "section_id": str(section.get("section_id") or ""),
                    "section_heading": str(section.get("heading") or ""),
                    "local_chunk_index": chunk.index,
                    "chunk_start_char": chunk.start_char,
                    "chunk_end_char": chunk.end_char,
                    "char_count": len(chunk.content),
                    "overlap_chars": overlap_chars,
                    "overlap_preview": chunk.content[:overlap_chars],
                    "content": chunk.content,
                    "ingestion_content": KnowledgeIngestionService._build_chunk_content(
                        document=document,
                        section_heading=str(section.get("heading") or ""),
                        chunk_text=chunk.content,
                    ),
                    "source_range": {
                        "section_id": str(section.get("section_id") or ""),
                        "chunk_index": chunk.index,
                        "section_start_char": int(section.get("start_char") or 0),
                        "section_end_char": int(section.get("end_char") or 0),
                        "chunk_start_char": chunk.start_char,
                        "chunk_end_char": chunk.end_char,
                    },
                }
            )
            previous_end = chunk.end_char
            global_chunk_index += 1

    return {
        "path": normalized_relative_path,
        "name": source_path.name,
        "source_size": source_path.stat().st_size,
        "chunk_size": config.memory.chunk_size,
        "chunk_overlap": config.memory.chunk_overlap,
        "json_result": structured_payload,
        "markdown_result": document.markdown,
        "schema_version": document.schema_version,
        "projection_hash": document.projection_hash,
        "assets": document.assets,
        "source_map": document.source_map,
        "semantic_chunks": semantic_chunks,
        "overlap_chunks": overlap_chunks,
        "stats": {
            "section_count": len(semantic_chunks),
            "overlap_chunk_count": len(overlap_chunks),
            "ocr_enabled": ocr_enabled,
        },
    }


def _request_base_url(request: Request) -> str:
    host = request.url.hostname or "127.0.0.1"
    port = request.url.port
    netloc = f"{host}:{port}" if port is not None else host
    return f"{request.url.scheme}://{netloc}"


def _collect_rest_apis(*, request: Request, base_url: str) -> list[dict[str, Any]]:
    apis: list[dict[str, Any]] = []
    openapi = request.app.openapi()
    paths = openapi.get("paths", {})
    components = openapi.get("components", {}).get("schemas", {})
    for route in request.app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.include_in_schema:
            continue
        methods = sorted(method for method in route.methods if method not in {"HEAD", "OPTIONS"})
        summary = (route.summary or _first_doc_line(route.endpoint.__doc__) or "").strip()
        for method in methods:
            operation = paths.get(route.path, {}).get(method.lower(), {})
            parameters = operation.get("parameters", [])
            request_body = operation.get("requestBody")
            responses = operation.get("responses", {})
            apis.append(
                {
                    "kind": "rest",
                    "protocol": "HTTP",
                    "service": "FastAPI",
                    "name": route.name,
                    "method": method,
                    "path": route.path,
                    "operation_id": operation.get("operationId", ""),
                    "tags": operation.get("tags", []),
                    "request": _rest_request_summary(parameters=parameters, request_body=request_body),
                    "response": _rest_response_summary(responses=responses),
                    "base_url": base_url,
                    "summary": operation.get("summary") or summary,
                    "description": operation.get("description", ""),
                    "parameters": _rest_parameters(parameters=parameters, components=components),
                    "request_body": _rest_request_body(request_body=request_body, components=components),
                    "responses": _rest_responses(responses=responses, components=components),
                    "request_schema_tree": _schema_tree(
                        name="body",
                        schema=_first_content_schema(request_body),
                        components=components,
                    ),
                    "response_schema_tree": _response_schema_tree(responses=responses, components=components),
                    "call": {
                        "url": f"{base_url}{route.path}",
                        "method": method,
                    },
                    "status": "running",
                }
            )
    return sorted(apis, key=lambda item: (item["path"], item["method"]))


def _collect_grpc_apis(*, address: str, running: bool) -> list[dict[str, Any]]:
    apis: list[dict[str, Any]] = []
    for service in agent_service_pb2.DESCRIPTOR.services_by_name.values():
        for method in service.methods:
            apis.append(
                {
                    "kind": "grpc",
                    "protocol": "gRPC",
                    "service": service.full_name,
                    "name": method.name,
                    "method": "RPC",
                    "path": f"/{service.full_name}/{method.name}",
                    "request": method.input_type.full_name,
                    "response": method.output_type.full_name,
                    "base_url": address,
                    "call": {
                        "target": address,
                        "method": f"/{service.full_name}/{method.name}",
                    },
                    "client_streaming": method.client_streaming,
                    "server_streaming": method.server_streaming,
                    "input_type": method.input_type.full_name,
                    "output_type": method.output_type.full_name,
                    "input_fields": _message_fields(method.input_type),
                    "output_fields": _message_fields(method.output_type),
                    "input_schema_tree": _message_tree(method.input_type, name=method.input_type.name),
                    "output_schema_tree": _message_tree(method.output_type, name=method.output_type.name),
                    "summary": "",
                    "status": "running" if running else "stopped",
                }
            )
    return apis


def _rest_request_summary(*, parameters: list[dict[str, Any]], request_body: dict[str, Any] | None) -> str:
    parts: list[str] = []
    for location in ("path", "query", "header", "cookie"):
        count = sum(1 for parameter in parameters if parameter.get("in") == location)
        if count:
            parts.append(f"{count} {location}")
    if request_body:
        parts.append("body")
    return ", ".join(parts) if parts else "none"


def _rest_response_summary(*, responses: dict[str, Any]) -> str:
    if not responses:
        return "unknown"
    return ", ".join(str(status) for status in sorted(responses.keys()))


def _rest_parameters(*, parameters: list[dict[str, Any]], components: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for parameter in parameters:
        schema = parameter.get("schema")
        result.append(
            {
                **parameter,
                "schema_tree": _schema_tree(
                    name=str(parameter.get("name") or "parameter"),
                    schema=schema,
                    components=components,
                    required=bool(parameter.get("required")),
                ),
            }
        )
    return result


def _rest_request_body(*, request_body: dict[str, Any] | None, components: dict[str, Any]) -> dict[str, Any] | None:
    if not request_body:
        return None
    return {
        **request_body,
        "content": _content_with_schema_fields(
            content=request_body.get("content", {}),
            components=components,
            prefix="body",
        ),
    }


def _rest_responses(*, responses: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    return {
        status: {
            **response,
            "content": _content_with_schema_fields(
                content=response.get("content", {}),
                components=components,
                prefix=f"response.{status}",
            ),
        }
        for status, response in responses.items()
    }


def _content_with_schema_fields(
    *,
    content: dict[str, Any],
    components: dict[str, Any],
    prefix: str,
) -> dict[str, Any]:
    return {
        content_type: {
            **content_info,
            "schema_tree": _schema_tree(
                name=content_type,
                schema=content_info.get("schema"),
                components=components,
            ),
        }
        for content_type, content_info in content.items()
    }


def _first_content_schema(container: dict[str, Any] | None) -> dict[str, Any] | None:
    content = container.get("content", {}) if container else {}
    first = next(iter(content.values()), None)
    if not isinstance(first, dict):
        return None
    schema = first.get("schema")
    return schema if isinstance(schema, dict) else None


def _response_schema_tree(*, responses: dict[str, Any], components: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for status, response in responses.items():
        content = response.get("content", {}) if isinstance(response, dict) else {}
        children = [
            tree
            for content_type, content_info in content.items()
            if (
                tree := _schema_tree(
                    name=content_type,
                    schema=content_info.get("schema") if isinstance(content_info, dict) else None,
                    components=components,
                )
            )
            is not None
        ]
        nodes.append(
            {
                "name": str(status),
                "type": "response",
                "required": False,
                "description": response.get("description", "") if isinstance(response, dict) else "",
                "children": children,
            }
        )
    return nodes


def _schema_tree(
    *,
    name: str,
    schema: dict[str, Any] | None,
    components: dict[str, Any],
    required: bool = False,
    seen_refs: set[str] | None = None,
) -> dict[str, Any] | None:
    if not schema:
        return None
    seen_refs = set(seen_refs or set())
    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in seen_refs:
            return _schema_node(name=name, schema={"type": ref, "description": "recursive reference"}, required=required)
        target = _resolve_schema_ref(ref=ref, components=components)
        if target is None:
            return _schema_node(name=name, schema={"type": ref}, required=required)
        return _schema_tree(
            name=name,
            schema=target,
            components=components,
            required=required,
            seen_refs=seen_refs | {ref},
        )

    node = _schema_node(name=name, schema=schema, required=required)
    children: list[dict[str, Any]] = []
    for key in ("allOf", "anyOf", "oneOf"):
        for index, child in enumerate(schema.get(key, [])):
            child_node = _schema_tree(
                name=f"{key}[{index}]",
                schema=child,
                components=components,
                required=required,
                seen_refs=seen_refs,
            )
            if child_node is not None:
                children.append(child_node)

    if schema.get("type") == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            item_node = _schema_tree(
                name="items",
                schema=items,
                components=components,
                required=True,
                seen_refs=seen_refs,
            )
            if item_node is not None:
                children.append(item_node)

    properties = schema.get("properties")
    if isinstance(properties, dict):
        required_names = set(schema.get("required", []))
        for property_name, child in properties.items():
            if not isinstance(child, dict):
                continue
            child_node = _schema_tree(
                name=property_name,
                schema=child,
                components=components,
                required=property_name in required_names,
                seen_refs=seen_refs,
            )
            if child_node is not None:
                children.append(child_node)

    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        child_node = _schema_tree(
            name="<key>",
            schema=additional,
            components=components,
            required=False,
            seen_refs=seen_refs,
        )
        if child_node is not None:
            children.append(child_node)

    node["children"] = children
    return node


def _schema_node(*, name: str, schema: dict[str, Any], required: bool) -> dict[str, Any]:
    return {
        "name": name,
        "type": _schema_type(schema),
        "required": required,
        "description": schema.get("description", ""),
        "default": schema.get("default"),
        "enum": schema.get("enum", []),
        "children": [],
    }


def _schema_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return str(schema["$ref"])
    if schema.get("type") == "array":
        items = schema.get("items", {})
        if isinstance(items, dict):
            return f"array<{_schema_type(items)}>"
        return "array"
    if isinstance(schema.get("type"), str):
        return str(schema["type"])
    for key in ("allOf", "anyOf", "oneOf"):
        if key in schema:
            return key
    return "unknown"


def _resolve_schema_ref(*, ref: str, components: dict[str, Any]) -> dict[str, Any] | None:
    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        return None
    schema = components.get(ref[len(prefix):])
    return schema if isinstance(schema, dict) else None


def _message_fields(message: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": field.name,
            "number": field.number,
            "type": _field_type_name(field),
            "label": _field_label_name(field),
            "repeated": field.label == field.LABEL_REPEATED,
            "message_type": field.message_type.full_name if field.message_type is not None else "",
        }
        for field in message.fields
    ]


def _message_tree(message: Any, *, name: str, required: bool = True, seen: set[str] | None = None) -> dict[str, Any]:
    seen = set(seen or set())
    if message.full_name in seen:
        return {
            "name": name,
            "type": message.full_name,
            "required": required,
            "description": "recursive message",
            "number": "",
            "label": "recursive",
            "children": [],
        }

    children: list[dict[str, Any]] = []
    next_seen = seen | {message.full_name}
    for field in message.fields:
        field_type = _field_type_name(field)
        child = {
            "name": field.name,
            "type": f"repeated {field_type}" if field.label == field.LABEL_REPEATED else field_type,
            "required": field.label == field.LABEL_REQUIRED,
            "description": "",
            "number": field.number,
            "label": _field_label_name(field),
            "children": [],
        }
        if field.message_type is not None:
            child["children"] = _message_tree(
                field.message_type,
                name=field.message_type.name,
                required=field.label == field.LABEL_REQUIRED,
                seen=next_seen,
            )["children"]
        children.append(child)
    return {
        "name": name,
        "type": message.full_name,
        "required": required,
        "description": "",
        "number": "",
        "label": "message",
        "children": children,
    }


def _field_label_name(field: Any) -> str:
    if field.label == field.LABEL_REQUIRED:
        return "required"
    if field.label == field.LABEL_REPEATED:
        return "repeated"
    return "optional"


def _field_type_name(field: Any) -> str:
    if field.message_type is not None:
        return field.message_type.full_name
    if field.enum_type is not None:
        return field.enum_type.full_name
    type_names = {
        field.TYPE_DOUBLE: "double",
        field.TYPE_FLOAT: "float",
        field.TYPE_INT64: "int64",
        field.TYPE_UINT64: "uint64",
        field.TYPE_INT32: "int32",
        field.TYPE_FIXED64: "fixed64",
        field.TYPE_FIXED32: "fixed32",
        field.TYPE_BOOL: "bool",
        field.TYPE_STRING: "string",
        field.TYPE_BYTES: "bytes",
        field.TYPE_UINT32: "uint32",
        field.TYPE_SFIXED32: "sfixed32",
        field.TYPE_SFIXED64: "sfixed64",
        field.TYPE_SINT32: "sint32",
        field.TYPE_SINT64: "sint64",
    }
    return type_names.get(field.type, str(field.type))


def _first_doc_line(doc: str | None) -> str:
    if not doc:
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
