"""
统一长期记忆检索服务。

功能说明:
本文件实现项目当前生产形态的 Memory/Knowledge 统一召回链路。完整流程为:
1. 生成 query embedding。
2. 先做向量召回候选。
3. 并行补做关键词召回候选。
4. 对两路候选做去重合并。
5. 对混合候选执行 ReRank 精排。
6. 最后叠加 relevance、freshness、authority 产出最终排序。

使用说明:
service = MemoryRetrievalService(config=config)
memories = service.retrieve_long_term_memory(query="项目代号是什么", user_id="u1", session_id="s1")
knowledge = service.retrieve_knowledge(query="海洋酸化影响什么", user_id="u1")
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from agent_service.core.agent_config import AgentConfig
from agent_service.models.longterm_memory_spec import LongTermMemorySpec
from agent_service.models.user_settings import UserKnowledgeLibrary
from agent_service.schemas.longterm_memory_spec import LongTermMemorySpecOut
from agent_service.services.memory.longterm_memory_service import LongTermMemoryService
from agent_service.services.memory.rag.embedding import EmbeddingService
from agent_service.services.memory.rag.hybrid_retrieval import (
    HybridRetrievalCandidate,
    HybridRetrievalService,
)
from agent_service.services.memory.rag.rerank import RerankService
from agent_service.services.settings.service import SettingsService


@dataclass(slots=True)
class RetrievedMemory:
    """
    检索结果结构。

    memory: 统一长期记忆输出 DTO。
    relevance_score: 当前最终使用的相关性分数。启用 ReRank 时取 ReRank 分数,否则取混合召回分。
    freshness_score: 时效性分数。
    final_score: relevance + freshness + authority 联合排序分。
    current_session_match: 是否命中当前 session。
    keyword_score: 关键词召回分数,便于观测。
    rerank_score: ReRank 分数,未启用时为空。
    retrieval_channels: 命中的召回通道列表。
    """

    memory: LongTermMemorySpecOut
    relevance_score: float
    freshness_score: float
    final_score: float
    current_session_match: bool = False
    keyword_score: float = 0.0
    rerank_score: float | None = None
    retrieval_channels: tuple[str, ...] = ()


@dataclass(slots=True)
class RetrievalDebugSnapshot:
    """
    单路召回的观测快照。

    pre_rerank_candidates: 混合召回并去重后的候选列表,尚未经过 ReRank 精排。
    post_rerank_results: ReRank 与最终过滤后的结果列表。
    request_limit: 本通道请求的返回条数上限,即 final_top_k。
    """

    pre_rerank_candidates: list[HybridRetrievalCandidate] = field(default_factory=list)
    post_rerank_results: list[RetrievedMemory] = field(default_factory=list)
    request_limit: int = 0


class MemoryRetrievalService:
    """
    统一长期记忆检索服务。

    config: 全局配置对象。
    embedding_service: 可选 Embedding 服务。
    memory_service: 可选长期记忆服务。
    hybrid_retrieval_service: 可选混合检索服务,测试时可注入假实现。
    rerank_service: 可选 ReRank 服务,测试时可注入假实现。
    """

    def __init__(
        self,
        *,
        config: AgentConfig,
        embedding_service: EmbeddingService | None = None,
        memory_service: LongTermMemoryService | None = None,
        hybrid_retrieval_service: HybridRetrievalService | None = None,
        rerank_service: RerankService | None = None,
    ) -> None:
        """初始化统一检索服务。"""

        self.config = config
        self.embedding_service = embedding_service or EmbeddingService(config=config)
        self.memory_service = memory_service or LongTermMemoryService(config=config)
        self.engine: Engine = self.memory_service.engine
        self.hybrid_retrieval_service = hybrid_retrieval_service or HybridRetrievalService(
            config=config,
            engine=self.engine,
        )
        self.rerank_service = rerank_service or RerankService(config=config)
        self._memory_recall_cache: OrderedDict[str, tuple[float, RetrievalDebugSnapshot]] = OrderedDict()
        self._memory_recall_cache_lock = threading.Lock()
        # 同一 session 内相近查询在短 TTL 内复用召回结果,避免每轮重复
        # 跑完整 embedding + rerank 链路(本地模型推理秒级,是首 token 前的主要耗时)。
        self._memory_recall_cache_ttl_seconds = config.limits.retrieval_cache_ttl_seconds
        self._memory_recall_cache_max_entries = config.limits.retrieval_cache_max_entries

    def retrieve_long_term_memory(
        self,
        *,
        query: str,
        user_id: str,
        session_id: str | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedMemory]:
        """
        检索用户长期记忆摘要。
        三层记忆 (session_fact、important_fact_summary、session_summary) 合并去重后统一排序返回。

        query: 当前查询文本。
        user_id: 用户 ID。
        session_id: 可选 session ID,用于在跨 session 召回后给予当前会话更高排序优先级。
        top_k: 可选返回条数。
        """

        return self.retrieve_long_term_memory_with_debug(
            query=query,
            user_id=user_id,
            session_id=session_id,
            top_k=top_k,
        ).post_rerank_results

    def retrieve_knowledge(
        self,
        *,
        query: str,
        user_id: str = "system",
        top_k: int | None = None,
    ) -> list[RetrievedMemory]:
        """
        检索知识库切片。

        query: 当前查询文本。
        user_id: 知识库归属用户;默认 system 保持旧全局知识库兼容。
        top_k: 可选返回条数。
        """
        return self.retrieve_knowledge_with_debug(query=query, user_id=user_id, top_k=top_k).post_rerank_results

    def retrieve_unified_search(
        self,
        *,
        query: str,
        user_id: str,
        top_k: int | None = None,
    ) -> list[RetrievedMemory]:
        """检索当前知识库下图书馆、组件库和文献库的联合搜索索引。

        query: 用户搜索文本。
        user_id: 已包含 active library 的知识库 owner ID。
        top_k: 最多返回的精排结果数。
        """

        return self._retrieve_with_debug(
            query=query,
            user_id=user_id,
            session_id=None,
            tag=self.config.constants.knowledge_tag,
            memory_type="unified_search_chunk",
            top_k=top_k,
        ).post_rerank_results

    def retrieve_long_term_memory_with_debug(
        self,
        *,
        query: str,
        user_id: str,
        session_id: str | None = None,
        top_k: int | None = None,
    ) -> RetrievalDebugSnapshot:
        """
        检索用户长期记忆摘要,并返回 ReRank 前后的真实快照。

        query: 当前查询文本。
        user_id: 用户 ID。
        session_id: 可选 session ID。
        top_k: 可选返回条数。
        """

        final_top_k = top_k or self.config.memory.rerank_top_k
        if session_id:
            cache_key = self._memory_recall_cache_key(
                user_id=user_id,
                session_id=session_id,
                query=query,
                top_k=final_top_k,
            )
            cached = self._memory_recall_cache_get(cache_key)
            if cached is not None:
                return cached

        seen_pre_ids: set[str] = set()
        seen_post_ids: set[str] = set()
        merged_pre: list[HybridRetrievalCandidate] = []
        merged_post: list[RetrievedMemory] = []

        for memory_type in (
            "session_fact",
            self.config.constants.important_fact_summary_memory_type,
            "session_summary",
            "user_custom",
        ):
            snapshot = self._retrieve_with_debug(
                query=query,
                user_id=user_id,
                session_id=session_id,
                tag=self.config.constants.memory_tag,
                memory_type=memory_type,
                top_k=top_k,
            )
            for candidate in snapshot.pre_rerank_candidates:
                memory_id = candidate.memory.memory_id
                if memory_id in seen_pre_ids:
                    continue
                seen_pre_ids.add(memory_id)
                merged_pre.append(candidate)
            for item in snapshot.post_rerank_results:
                memory_id = item.memory.memory_id
                if memory_id in seen_post_ids:
                    continue
                seen_post_ids.add(memory_id)
                merged_post.append(item)

        merged_pre.sort(
            key=lambda item: (
                item.merged_score,
                int(item.current_session_match),
                len(item.source_channels),
                self._ensure_aware_datetime(item.memory.updated_at)
                or datetime.min.replace(tzinfo=timezone.utc),
                item.memory.importance,
            ),
            reverse=True,
        )
        merged_post.sort(key=self._rank_key, reverse=True)
        snapshot = RetrievalDebugSnapshot(
            pre_rerank_candidates=merged_pre[: max(final_top_k, self.config.memory.rerank_top_k)],
            post_rerank_results=merged_post[:final_top_k],
            request_limit=final_top_k,
        )
        if session_id:
            self._memory_recall_cache_put(cache_key, snapshot)
        return snapshot

    def retrieve_knowledge_with_debug(
        self,
        *,
        query: str,
        user_id: str = "system",
        top_k: int | None = None,
    ) -> RetrievalDebugSnapshot:
        """
        检索知识库切片,并返回 ReRank 前后的真实快照。

        query: 当前查询文本。
        user_id: 知识库归属用户;默认 system 保持旧全局知识库兼容。
        top_k: 可选返回条数。
        """

        resolved_user_id = self._resolve_knowledge_user_id(user_id)
        return self._retrieve_with_debug(
            query=query,
            user_id=resolved_user_id,
            session_id=None,
            tag=self.config.constants.knowledge_tag,
            memory_type="knowledge_chunk",
            top_k=top_k,
        )

    def _resolve_knowledge_user_id(self, user_id: str) -> str:
        """
        解析知识库检索使用的用户 ID。

        user_id: 请求中的知识库归属用户;如果该用户还没有自己的切片,回退到 system 默认知识库。
        """

        from agent_service.services.settings.mcp_settings import selected_library
        selection = selected_library.get()
        if selection is not None:
            owner, library_id = selection
            if owner != user_id:
                raise PermissionError("知识库身份不匹配")
            return SettingsService.build_knowledge_owner_id(user_id=owner, library_id=library_id)
        normalized_user_id = user_id.strip() or "system"
        if normalized_user_id == "system":
            return "system"
        active_library_id = self._get_active_library_id(user_id=normalized_user_id)
        if active_library_id:
            knowledge_owner_id = SettingsService.build_knowledge_owner_id(
                user_id=normalized_user_id,
                library_id=active_library_id,
            )
            if self.memory_service.has_memories(
                user_id=knowledge_owner_id,
                tag=self.config.constants.knowledge_tag,
                memory_type="knowledge_chunk",
            ):
                return knowledge_owner_id
        if self.memory_service.has_memories(
            user_id=normalized_user_id,
            tag=self.config.constants.knowledge_tag,
            memory_type="knowledge_chunk",
        ):
            return normalized_user_id
        return "system"

    def _get_active_library_id(self, *, user_id: str) -> str:
        """
        从数据库读取用户当前 active 知识库 ID。

        user_id: 用户 ID。
        """

        statement = (
            select(UserKnowledgeLibrary.library_id)
            .where(UserKnowledgeLibrary.user_id == user_id)
            .where(UserKnowledgeLibrary.is_active == True)  # noqa: E712
            .limit(1)
        )
        with Session(self.engine) as db_session:
            return db_session.exec(statement).first() or ""

    def get_latest_session_summary(self, *, user_id: str, session_id: str) -> RetrievedMemory | None:
        """
        获取当前会话最近一条摘要记忆,用于同 session 的保底注入。

        user_id: 用户 ID。
        session_id: 会话 ID。
        """

        return self._get_latest_memory_by_type(
            user_id=user_id,
            session_id=session_id,
            memory_type="session_summary",
            retrieval_channel="session_summary_fallback",
        )

    def get_latest_important_fact_summary(self, *, user_id: str, session_id: str) -> RetrievedMemory | None:
        """
        获取当前会话最近一条重要事实摘要记忆。

        user_id: 用户 ID。
        session_id: 会话 ID。
        """

        return self._get_latest_memory_by_type(
            user_id=user_id,
            session_id=session_id,
            memory_type=self.config.constants.important_fact_summary_memory_type,
            retrieval_channel="important_fact_summary",
        )

    def warmup(self) -> None:
        """预加载 Embedding 和 ReRank 模型,避免首次检索冷启动。"""

        self.embedding_service.warmup()
        self.rerank_service.warmup()

    # -----------------------------------------------------------------------------------------
    # 统一召回入口
    # -----------------------------------------------------------------------------------------
    def _retrieve_with_debug(
        self,
        *,
        query: str,
        user_id: str,
        session_id: str | None,
        tag: str,
        memory_type: str,
        top_k: int | None,
    ) -> RetrievalDebugSnapshot:
        """
        统一召回入口,调用各个检索业务执行统一检索。
        query: 当前查询文本。
        user_id: 用户 ID。
        session_id: 可选会话 ID。
        tag: Memory 或 Knowledge。
        memory_type: 记忆子类型。
        top_k: 返回条数。
        """

        normalized_query = query.strip()
        if not normalized_query:
            return RetrievalDebugSnapshot()
        final_top_k = top_k or self.config.memory.rerank_top_k
        # 将用户提出的query向量化入库
        query_vector = self.embedding_service.embed_text(normalized_query)
        if not query_vector:
            return RetrievalDebugSnapshot()
        # 双路召回
        # 向量召回
        vector_candidates = self._retrieve_vector_candidates(
            query_vector=query_vector,
            user_id=user_id,
            session_id=session_id,
            tag=tag,
            memory_type=memory_type,
            limit=max(final_top_k, self.config.memory.vector_top_k),
        )
        # 关键词召回
        keyword_candidates = self.hybrid_retrieval_service.retrieve_keyword_candidates(
            query=normalized_query,
            user_id=user_id,
            session_id=session_id,
            tag=tag,
            memory_type=memory_type,
            limit=max(final_top_k, self.config.memory.keyword_top_k),
        )
        # 双路召回合并去重
        merged_candidates = self.hybrid_retrieval_service.merge_candidates(
            vector_candidates=vector_candidates,
            keyword_candidates=keyword_candidates,
            session_id=session_id,
        )
        # rerank精排,取Top-K结果
        reranked_candidates = self.rerank_service.rerank(
            query=normalized_query,
            candidates=merged_candidates,
            top_k=max(final_top_k, self.config.memory.rerank_top_k),
        )
        now = datetime.now(timezone.utc)
        retrieved = [
            self._candidate_to_retrieved_memory(candidate=candidate, now=now, session_id=session_id)
            for candidate in reranked_candidates
        ]
        # 最终排序（0.5*relevance + 0.3*freshness + 0.2*authority）
        for item in retrieved:
            item.final_score = self._final_score(item)
        retrieved = [item for item in retrieved if item.final_score >= self.config.memory.score_threshold]
        retrieved.sort(key=self._rank_key, reverse=True)
        return RetrievalDebugSnapshot(
            pre_rerank_candidates=merged_candidates,
            post_rerank_results=retrieved[:final_top_k],
            request_limit=final_top_k,
        )

    @staticmethod
    def serialize_candidate(candidate: HybridRetrievalCandidate) -> dict[str, Any]:
        """
        将 ReRank 前候选序列化为前端可消费的观测对象。

        candidate: 混合召回候选。
        """

        return {
            "memory_id": candidate.memory.memory_id,
            "content": candidate.memory.content,
            "memory_type": candidate.memory.memory_type,
            "source_type": candidate.memory.source_type,
            "source_uri": candidate.memory.source_uri,
            "updated_at": _to_iso(candidate.memory.updated_at),
            "matched_terms": list(candidate.matched_terms),
            "retrieval_channels": list(candidate.source_channels),
            "current_session_match": candidate.current_session_match,
            "vector_score": round(candidate.vector_score, 4),
            "keyword_score": round(candidate.keyword_score, 4),
            "merged_score": round(candidate.merged_score, 4),
            "rerank_score": round(candidate.rerank_score, 4) if candidate.rerank_score is not None else None,
            "final_score": None,
        }

    @staticmethod
    def serialize_retrieved_memory(item: RetrievedMemory) -> dict[str, Any]:
        """
        将 ReRank 后结果序列化为前端可消费的观测对象。

        item: 最终检索结果。
        """

        return {
            "memory_id": item.memory.memory_id,
            "content": item.memory.content,
            "memory_type": item.memory.memory_type,
            "source_type": item.memory.source_type,
            "source_uri": item.memory.source_uri,
            "updated_at": _to_iso(item.memory.updated_at),
            "matched_terms": [],
            "retrieval_channels": list(item.retrieval_channels),
            "current_session_match": item.current_session_match,
            "vector_score": None,
            "keyword_score": round(item.keyword_score, 4),
            "merged_score": None,
            "rerank_score": round(item.rerank_score, 4) if item.rerank_score is not None else None,
            "relevance_score": round(item.relevance_score, 4),
            "freshness_score": round(item.freshness_score, 4),
            "final_score": round(item.final_score, 4),
        }

    @classmethod
    def serialize_debug_snapshot(cls, snapshot: RetrievalDebugSnapshot) -> dict[str, Any]:
        """
        将单路召回快照序列化为 API 输出结构。

        snapshot: 单路召回观测快照。
        """

        return {
            "pre_rerank": [cls.serialize_candidate(item) for item in snapshot.pre_rerank_candidates],
            "post_rerank": [cls.serialize_retrieved_memory(item) for item in snapshot.post_rerank_results],
            "request_limit": snapshot.request_limit,
        }

    def _get_latest_memory_by_type(
        self,
        *,
        user_id: str,
        session_id: str,
        memory_type: str,
        retrieval_channel: str,
    ) -> RetrievedMemory | None:
        """
        获取指定记忆类型在当前会话中的最近一条记录。

        user_id: 用户 ID。
        session_id: 会话 ID。
        memory_type: 目标记忆类型。
        retrieval_channel: 观测用检索通道名称。
        """

        statement = (
            select(LongTermMemorySpec)
            .where(LongTermMemorySpec.tag == self.config.constants.memory_tag)
            .where(LongTermMemorySpec.memory_type == memory_type)
            .where(LongTermMemorySpec.user_id == user_id)
            .where(LongTermMemorySpec.session_id == session_id)
            .order_by(LongTermMemorySpec.updated_at.desc())
            .limit(1)
        )
        with Session(self.engine) as db_session:
            record = db_session.exec(statement).first()
        if record is None:
            return None
        memory = LongTermMemorySpecOut.from_record(record)
        now = datetime.now(timezone.utc)
        retrieved = RetrievedMemory(
            memory=memory,
            relevance_score=1.0,
            freshness_score=self._freshness_score(memory, now=now),
            final_score=0.0,
            current_session_match=True,
            retrieval_channels=(retrieval_channel,),
        )
        retrieved.final_score = self._final_score(retrieved)
        return retrieved

    def _retrieve_vector_candidates(
        self,
        *,
        query_vector: list[float],
        user_id: str,
        session_id: str | None,
        tag: str,
        memory_type: str,
        limit: int,
    ) -> list[HybridRetrievalCandidate]:
        """
        统一执行向量候选召回。

        query_vector: 查询向量。
        user_id: 用户 ID。
        session_id: 当前会话 ID。
        tag: 记忆大类。
        memory_type: 记忆子类型。
        limit: 召回数量上限。
        """

        # 优先使用ChromaDB向量库召回,若查询无结果则回退到JSON向量余弦相似度计算.
        candidates = self._retrieve_by_chroma(
            query_vector=query_vector,
            user_id=user_id,
            session_id=session_id,
            tag=tag,
            memory_type=memory_type,
            limit=limit,
        )
        if candidates and any(candidate.vector_score > 0.0 for candidate in candidates):
            return candidates
        # 回退到cos相似度
        return self._retrieve_by_json_vectors(
            query_vector=query_vector,
            user_id=user_id,
            session_id=session_id,
            tag=tag,
            memory_type=memory_type,
            limit=limit,
        )

    def _retrieve_by_chroma(
        self,
        *,
        query_vector: list[float],
        user_id: str,
        session_id: str | None,
        tag: str,
        memory_type: str,
        limit: int,
    ) -> list[HybridRetrievalCandidate]:
        """
        使用 ChromaDB 向量集合检索候选记忆。

        query_vector: 查询向量。
        user_id: 用户 ID。
        session_id: 当前会话 ID。
        tag: 记忆大类。
        memory_type: 记忆子类型。
        limit: 候选数量上限。
        """

        memory_service = self.memory_service
        memory_service._ensure_chroma_collection(vector_dimension=len(query_vector))
        if not memory_service.chroma_available:
            return []

        collection = memory_service._chroma_collection
        where_filter = {
            "$and": [
                {"user_id": user_id},
                {"tag": tag},
                {"memory_type": memory_type},
            ]
        }
        try:
            results = collection.query(
                query_embeddings=[query_vector],
                n_results=limit,
                where=where_filter,
                include=["metadatas", "distances"],
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("ChromaDB query failed, falling back to JSON vectors: %s", exc)
            return []

        if not results or not results.get("ids") or not results["ids"][0]:
            return []

        memory_ids = results["ids"][0]
        distances = results.get("distances", [[]])[0] if results.get("distances") else []

        with Session(self.engine) as db_session:
            statement = select(LongTermMemorySpec).where(LongTermMemorySpec.memory_id.in_(memory_ids))
            records = db_session.exec(statement).all()
        record_map = {record.memory_id: LongTermMemorySpecOut.from_record(record) for record in records}

        now = datetime.now(timezone.utc)
        candidates: list[HybridRetrievalCandidate] = []
        for i, memory_id in enumerate(memory_ids):
            memory = record_map.get(memory_id)
            if memory is None or not self._is_memory_currently_active(memory):
                continue
            valid_until = self._ensure_aware_datetime(memory.valid_until)
            if valid_until is not None and valid_until < now:
                continue
            distance = distances[i] if i < len(distances) else 1.0
            vector_score = self._clamp_score(1.0 - float(distance))
            candidates.append(
                HybridRetrievalCandidate(
                    memory=memory,
                    vector_score=vector_score,
                    merged_score=vector_score,
                    source_channels=("vector",),
                    current_session_match=bool(session_id and memory.session_id == session_id),
                )
            )
        return candidates

    def _retrieve_by_json_vectors(
        self,
        *,
        query_vector: list[float],
        user_id: str,
        session_id: str | None,
        tag: str,
        memory_type: str,
        limit: int,
    ) -> list[HybridRetrievalCandidate]:
        """
        使用 JSON 向量字段回退检索候选记忆。

        query_vector: 查询向量。
        user_id: 用户 ID。
        session_id: 当前会话 ID。
        tag: 记忆大类。
        memory_type: 记忆子类型。
        limit: 候选数量上限。
        """

        now = datetime.now(timezone.utc)
        statement = (
            select(LongTermMemorySpec)
            .where(LongTermMemorySpec.tag == tag)
            .where(LongTermMemorySpec.memory_type == memory_type)
            .where(LongTermMemorySpec.user_id == user_id)
            .order_by(LongTermMemorySpec.updated_at.desc())
        )
        with Session(self.engine) as db_session:
            records = db_session.exec(statement).all()
        scored: list[HybridRetrievalCandidate] = []
        for record in records:
            valid_until = self._ensure_aware_datetime(record.valid_until)
            if valid_until is not None and valid_until < now:
                continue
            if not record.embedding_vector_json:
                continue
            memory = LongTermMemorySpecOut.from_record(record)
            if not self._is_memory_currently_active(memory):
                continue
            vector_score = self._cosine_similarity(query_vector, record.embedding_vector_json)
            scored.append(
                HybridRetrievalCandidate(
                    memory=memory,
                    vector_score=vector_score,
                    merged_score=vector_score,
                    source_channels=("vector",),
                    current_session_match=bool(session_id and memory.session_id == session_id),
                )
            )
        scored.sort(
            key=lambda item: (
                item.vector_score,
                int(item.current_session_match),
                self._ensure_aware_datetime(item.memory.updated_at),
            ),
            reverse=True,
        )
        return scored[:limit]

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        """
        计算两组向量的余弦相似度。

        left: 左向量。
        right: 右向量。
        """

        if len(left) != len(right) or not left or not right:
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        return MemoryRetrievalService._clamp_score((numerator / (left_norm * right_norm) + 1.0) / 2.0)

    def _candidate_to_retrieved_memory(
        self,
        *,
        candidate: HybridRetrievalCandidate,
        now: datetime,
        session_id: str | None,
    ) -> RetrievedMemory:
        """
        将混合召回候选转换为最终检索 DTO。

        candidate: 混合召回候选。
        now: 当前时间。
        session_id: 当前 session ID。
        """

        relevance_score = self._resolve_relevance_score(candidate)
        return RetrievedMemory(
            memory=candidate.memory,
            relevance_score=relevance_score,
            freshness_score=self._freshness_score(candidate.memory, now=now),
            final_score=0.0,
            current_session_match=bool(session_id and candidate.memory.session_id == session_id),
            keyword_score=candidate.keyword_score,
            rerank_score=candidate.rerank_score,
            retrieval_channels=candidate.source_channels,
        )

    @staticmethod
    def _resolve_relevance_score(candidate: HybridRetrievalCandidate) -> float:
        """
        解析候选最终用于排序的相关性分数。

        candidate: 混合召回候选。
        """

        if candidate.rerank_score is not None:
            return max(candidate.rerank_score, candidate.merged_score)
        return max(candidate.merged_score, candidate.vector_score, candidate.keyword_score)

    def _final_score(self, item: RetrievedMemory) -> float:
        """
        计算相关性、时效性和权威性的联合得分。

        item: 检索结果。
        """

        return self._clamp_score(
            self.config.memory.relevance_weight * item.relevance_score
            + self.config.memory.freshness_weight * item.freshness_score
            + self.config.memory.authority_weight * item.memory.authority
        )

    def _rank_key(self, item: RetrievedMemory) -> tuple[datetime, float, int, float, float]:
        """
        返回联合排序键。

        排序策略: 更新时间优先 → 最终得分 → 当前 session 命中 → 相关性 → 重要性。
        理由: score_threshold 已经滤掉无关记忆,在剩余的候选集中,越新的信息越可能是当前事实。
        对于"当前项目代号是什么"这类时效敏感查询,此排序远优于纯 relevance 排序。

        item: 检索结果。
        """

        updated_at = self._ensure_aware_datetime(item.memory.updated_at)
        if updated_at is None:
            updated_at = datetime.min.replace(tzinfo=timezone.utc)
        return (
            updated_at,
            item.final_score,
            int(item.current_session_match),
            item.relevance_score,
            item.memory.importance,
        )

    def _freshness_score(self, memory: LongTermMemorySpecOut, *, now: datetime) -> float:
        """
        计算记忆时效性得分。

        memory: 长期记忆记录。
        now: 当前时间。
        """

        updated_at = MemoryRetrievalService._ensure_aware_datetime(memory.updated_at)
        age_days = max((now - updated_at).total_seconds() / 86400.0, 0.0)
        return 1.0 / (1.0 + age_days / self.config.limits.retrieval_freshness_half_life_days)

    @staticmethod
    def _is_memory_currently_active(memory: LongTermMemorySpecOut) -> bool:
        """
        判断长期记忆当前是否仍应参与召回。

        memory: 长期记忆输出记录。
        """

        return HybridRetrievalService.is_memory_currently_active(memory)

    @staticmethod
    def _clamp_score(value: float) -> float:
        """
        将得分裁剪到 0 到 1。

        value: 原始得分。
        """

        return max(0.0, min(1.0, value))

    @staticmethod
    def _ensure_aware_datetime(value: datetime | None) -> datetime | None:
        """
        将数据库读回的时间统一规范为带 UTC 时区的 datetime。

        value: 可能来自 SQLite 的无时区 datetime。
        """

        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _memory_recall_cache_key(*, user_id: str, session_id: str, query: str, top_k: int) -> str:
        """
        生成长期记忆召回缓存 key:session 维度 + 查询归一化,避免跨会话串线,
        也让同一 session 内措辞接近的追问命中同一缓存。
        """

        normalized_query = " ".join(query.lower().split())
        return f"{user_id}\x00{session_id}\x00{normalized_query}\x00{top_k}"

    def _memory_recall_cache_get(self, cache_key: str) -> RetrievalDebugSnapshot | None:
        """读取未过期的召回缓存,命中时刷新到最新位置(近似 LRU)。"""

        now = time.monotonic()
        with self._memory_recall_cache_lock:
            entry = self._memory_recall_cache.get(cache_key)
            if entry is None:
                return None
            stored_at, snapshot = entry
            if now - stored_at > self._memory_recall_cache_ttl_seconds:
                del self._memory_recall_cache[cache_key]
                return None
            self._memory_recall_cache.move_to_end(cache_key)
            return snapshot

    def _memory_recall_cache_put(self, cache_key: str, snapshot: RetrievalDebugSnapshot) -> None:
        """写入召回缓存,超上限时淘汰最久未命中的条目。"""

        with self._memory_recall_cache_lock:
            while len(self._memory_recall_cache) >= self._memory_recall_cache_max_entries:
                self._memory_recall_cache.popitem(last=False)
            self._memory_recall_cache[cache_key] = (time.monotonic(), snapshot)
            self._memory_recall_cache.move_to_end(cache_key)


def _to_iso(value: datetime | None) -> str:
    """
    将 datetime 序列化为稳定的 ISO 8601 字符串。

    value: 待序列化时间。
    """

    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
