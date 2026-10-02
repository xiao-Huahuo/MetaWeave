"""Agent 与 MCP 共用的手动记忆写入服务。

使用 write_manual_memory 将一条独立记忆向量化并保存到正式长期记忆服务。
记忆类型用于分类，不代表单值槽位；新增记忆不会使同类型的已有记忆失效。
"""
from agent_service.schemas.longterm_memory_spec import LongTermMemorySpecCreate


def write_manual_memory(*, config, memory_service, embedding_service, user_id: str,
                        content: str, memory_type: str = "important_fact_summary",
                        importance: float = 0.5, authority: float = 0.5, session_id: str = ""):
    """追加独立记忆，保存失败时不修改已有记忆。

    config: 全局配置，提供记忆标签和 embedding 模型名称。
    memory_service: 正式长期记忆持久化服务。
    embedding_service: 可选向量化服务，为空时仅保存记忆正文。
    user_id: 记忆归属用户。
    content: 需要保存的记忆内容。
    memory_type: 记忆分类，不用于替换同类记录。
    importance: 记忆重要性评分。
    authority: 记忆权威性评分。
    session_id: 来源会话，为空时不绑定会话。
    """
    vector = embedding_service.embed_text(content) if embedding_service else []
    return memory_service.create_memory(LongTermMemorySpecCreate(
        user_id=user_id, session_id=session_id, tag=config.constants.memory_tag,
        memory_type=memory_type, content=content, source_type="manual_write", source_uri="manual",
        confidence=1.0, importance=importance, authority=authority,
        embedding_model=config.model.embedding_model_name or None, embedding_vector_json=vector,
        metadata_json={"fact_status": "active", "fact": {"namespace": "general", "key": memory_type, "value": content}},
    ))
