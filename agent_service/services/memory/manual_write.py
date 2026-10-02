"""Shared manual memory write used by Agent and MCP adapters, with explicit identity and dependencies."""
from sqlmodel import Session, select
from agent_service.models.longterm_memory_spec import LongTermMemorySpec
from agent_service.schemas.longterm_memory_spec import LongTermMemorySpecCreate


def write_manual_memory(*, config, memory_service, embedding_service, user_id: str,
                        content: str, memory_type: str = "important_fact_summary",
                        importance: float = 0.5, authority: float = 0.5, session_id: str = ""):
    """Embed and persist the same manual fact format while superseding prior active entries."""
    vector = embedding_service.embed_text(content) if embedding_service else []
    with Session(memory_service.engine) as db:
        rows = db.exec(select(LongTermMemorySpec).where(
            LongTermMemorySpec.user_id == user_id, LongTermMemorySpec.tag == config.constants.memory_tag,
            LongTermMemorySpec.memory_type == memory_type, LongTermMemorySpec.source_type == "manual_write",
        )).all()
        for row in rows:
            metadata = dict(row.metadata_json or {})
            if metadata.get("fact_status") == "active":
                metadata["fact_status"] = "superseded"
                row.metadata_json = metadata
                db.add(row)
        db.commit()
    return memory_service.create_memory(LongTermMemorySpecCreate(
        user_id=user_id, session_id=session_id, tag=config.constants.memory_tag,
        memory_type=memory_type, content=content, source_type="manual_write", source_uri="manual",
        confidence=1.0, importance=importance, authority=authority,
        embedding_model=config.model.embedding_model_name or None, embedding_vector_json=vector,
        metadata_json={"fact_status": "active", "fact": {"namespace": "general", "key": memory_type, "value": content}},
    ))
