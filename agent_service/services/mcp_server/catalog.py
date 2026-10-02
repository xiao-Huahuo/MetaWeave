"""Explicit exported business tools; reuse Agent schemas, call domain services without chat/UI runtime."""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from jsonschema import Draft202012Validator
from agent_service.tools.definitions import BUILTIN_TOOL_DEFINITIONS

# Each entry explicitly states its domain and write permission. External MCP tools are never re-exported.
TOOL_ACCESS = {
    "search_knowledge": ("knowledge", False), "get_knowledge_context": ("knowledge", False),
    "list_knowledge_files": ("knowledge", False), "read_file": ("knowledge", False),
    "write_knowledge_file": ("knowledge", True), "patch_knowledge_file": ("knowledge", True),
    "delete_knowledge_file": ("knowledge", True), "rename_knowledge_file": ("knowledge", True),
    "create_knowledge_folder": ("knowledge", True),
    "list_library_items": ("library", False), "list_library_tags": ("library", False),
    "add_library_book": ("library", True), "add_library_collection": ("library", True),
    "update_library_item": ("library", True), "remove_library_item": ("library", True),
    "get_long_term_memory": ("memory", False), "write_long_term_memory": ("memory", True),
    "delete_long_term_memory": ("memory", True),
}


def tool_catalog() -> list[dict]:
    """Produce the same metadata for settings, discovery and invocation validation."""
    result = []
    for definition in BUILTIN_TOOL_DEFINITIONS:
        if definition.name not in TOOL_ACCESS:
            continue
        domain, write = TOOL_ACCESS[definition.name]
        schema = deepcopy(definition.args_schema)
        schema["additionalProperties"] = False
        description = definition.description
        if definition.name == "search_knowledge":
            # No global component data can be reached through a library-scoped credential.
            schema["properties"]["sources"]["items"]["enum"] = ["files", "library", "literature"]
            description = "搜索凭据授权知识库的文件、图书馆和文献，支持全文与语义检索。"
        if definition.name == "read_file":
            description = "读取凭据授权知识库内的文件正文，支持按行读取；不访问聊天附件。"
        title = "知识库联合搜索" if definition.name == "search_knowledge" else definition.display_name
        result.append(dict(name=definition.name, title=title, description=description,
                           input_schema=schema, domain=domain, write=write))
    return result


def execute_business(services, user_id: str, name: str, arguments: dict[str, Any]) -> Any:
    """Validate the complete schema and delegate to existing business services under request scope."""
    tool = next(t for t in tool_catalog() if t["name"] == name)
    Draft202012Validator(tool["input_schema"]).validate(arguments)
    a = dict(arguments)
    knowledge, library = services.knowledge_library_service, services.library_service
    if name == "search_knowledge":
        a.setdefault("sources", ["files", "library", "literature"])
        a.setdefault("fulltext", True)
        a.setdefault("semantic", False)
        return services.unified_search_service.search(user_id=user_id, **a)
    if name == "get_knowledge_context":
        return [dict(content=r.memory.content, source_uri=r.memory.source_uri, score=r.final_score)
                for r in services.retrieval_service.retrieve_knowledge(user_id=user_id, **a)]
    if name == "list_knowledge_files":
        return knowledge.list_files(user_id=user_id)
    if name == "read_file":
        if a["path"].startswith("attachment://"):
            raise PermissionError("此凭据不能访问聊天附件")
        try:
            result = knowledge.read_file(user_id=user_id, path=a["path"])
        except UnicodeDecodeError:
            result = knowledge.read_markdown_projection(user_id=user_id, path=a["path"])
        start = a.get("cursor", a.get("start_line", 0))
        end = a.get("end_line")
        if start < 0 or (end is not None and end < start):
            raise ValueError("读取行范围无效")
        result["content"] = "\n".join(result["content"].splitlines()[start:end])
        return result
    if name == "patch_knowledge_file":
        content = knowledge.read_file(user_id=user_id, path=a["path"])["content"]
        if not a["old_text"] or content.count(a["old_text"]) != 1:
            raise ValueError("原文必须唯一匹配")
        return knowledge.write_file(user_id=user_id, path=a["path"], content=content.replace(a["old_text"], a["new_text"], 1))
    knowledge_methods = {"write_knowledge_file": "write_file", "delete_knowledge_file": "delete_path",
                         "rename_knowledge_file": "rename_path", "create_knowledge_folder": "create_folder"}
    if name in knowledge_methods:
        return getattr(knowledge, knowledge_methods[name])(user_id=user_id, **a)
    library_methods = {"list_library_items": "list_items", "list_library_tags": "list_tags",
                       "add_library_book": "create_item", "add_library_collection": "create_collection",
                       "remove_library_item": "delete_item"}
    if name in library_methods:
        if a.get("content_type") == "external_file":
            raise PermissionError("MCP 凭据不能引用知识库外的本地文件")
        return getattr(library, library_methods[name])(user_id=user_id, **a)
    if name == "update_library_item":
        return library.update_item(user_id=user_id, item_id=a.pop("item_id"), payload=a)
    if name == "get_long_term_memory":
        return [dict(content=r.memory.content, memory_id=r.memory.memory_id)
                for r in services.retrieval_service.retrieve_long_term_memory(user_id=user_id, session_id="", **a)]
    if name == "write_long_term_memory":
        # Reuse the same manual memory business write as Agent tools, including embedding and formal persistence.
        from agent_service.services.memory.manual_write import write_manual_memory
        return write_manual_memory(config=services.config, memory_service=services.memory_service,
            embedding_service=services.retrieval_service.embedding_service, user_id=user_id, **a).model_dump(mode="json")
    if name == "delete_long_term_memory":
        memory = services.memory_service.find_user_memory_by_content(user_id=user_id, content=a["content"])
        if memory is None:
            return {"deleted": False}
        return {"deleted": services.memory_service.delete_memory(memory_id=memory.memory_id)}
    raise ValueError("工具尚未登记业务处理器")
