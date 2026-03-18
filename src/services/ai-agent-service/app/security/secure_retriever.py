"""
Secure RAG Retriever

Wraps the existing Retriever with backend-enforced access control,
PII filtering, and audit logging for RAG access.
"""

import logging
from typing import Optional, List, Set

from app.rag.retriever import Retriever, RetrievalResult, StoredChunk
from app.security.backend_authorization_client import (
    AuthorizationContext,
    BackendAuthorizationClient,
)
from app.security.data_classifier import DataClassifier

logger = logging.getLogger(__name__)


class SecureRetriever:
    """Security wrapper around RAG Retriever."""

    def __init__(
        self,
        retriever: Retriever,
        data_classifier: Optional[DataClassifier] = None,
        audit_logger=None,
        authorization_client: BackendAuthorizationClient | None = None,
    ) -> None:
        self._retriever = retriever
        self._classifier = data_classifier or DataClassifier()
        self._audit_logger = audit_logger
        self._authorization_client = authorization_client or BackendAuthorizationClient()

    async def initialize(self) -> None:
        await self._retriever.initialize()

    async def retrieve(
        self,
        query: str,
        post_id: Optional[str] = None,
        user_id: str = "anonymous",
        k: int = 5,
        min_similarity: float = 0.3,
        filter_pii: bool = True,
    ) -> RetrievalResult:
        if post_id and not await self._check_post_access(user_id, post_id):
            self._log_unauthorized_access(user_id, post_id)
            raise PermissionError(f"Access denied to post {post_id}")

        result = await self._retriever.retrieve(
            query=query,
            post_id=post_id,
            k=k,
            min_similarity=min_similarity,
        )

        if filter_pii and result.has_results:
            result = self._apply_pii_filter(result)

        self._log_access(user_id, post_id, len(result.chunks))
        return result

    async def retrieve_with_context(
        self,
        query: str,
        post_id: str,
        user_id: str = "anonymous",
        k: int = 5,
        include_neighbors: bool = True,
        filter_pii: bool = True,
    ) -> RetrievalResult:
        if not await self._check_post_access(user_id, post_id):
            self._log_unauthorized_access(user_id, post_id)
            raise PermissionError(f"Access denied to post {post_id}")

        result = await self._retriever.retrieve_with_context(
            query=query,
            post_id=post_id,
            k=k,
            include_neighbors=include_neighbors,
        )

        if filter_pii and result.has_results:
            result = self._apply_pii_filter(result)

        self._log_access(user_id, post_id, len(result.chunks))
        return result

    async def _check_post_access(self, user_id: str, post_id: str) -> bool:
        auth_context = AuthorizationContext(
            subject_type="anonymous" if user_id == "anonymous" else "user",
            subject_id=None if user_id == "anonymous" else user_id,
            roles=[] if user_id == "anonymous" else ["Author"],
        )
        try:
            decision = await self._authorization_client.authorize_post_access(
                post_id=post_id,
                action="ViewPublished",
                auth_context=auth_context,
            )
        except Exception as exc:
            logger.error("SecureRetriever authorization failed closed for post_id=%s: %s", post_id, exc)
            return False
        return decision.allowed

    def _apply_pii_filter(self, result: RetrievalResult) -> RetrievalResult:
        filtered_chunks: List[StoredChunk] = []

        for chunk in result.chunks:
            classification = self._classifier.classify_and_redact(chunk.content)

            if classification.pii_entities:
                filtered_chunk = StoredChunk(
                    content=classification.anonymized_text,
                    post_id=chunk.post_id,
                    chunk_index=chunk.chunk_index,
                    similarity_score=chunk.similarity_score,
                    metadata=chunk.metadata,
                )
                filtered_chunks.append(filtered_chunk)
                logger.debug(
                    "PII redacted in chunk %s: %s entities, classification=%s",
                    chunk.chunk_index,
                    classification.entity_count,
                    classification.classification.value,
                )
            else:
                filtered_chunks.append(chunk)

        return RetrievalResult(
            chunks=filtered_chunks,
            query=result.query,
            post_id=result.post_id,
        )

    def _log_unauthorized_access(self, user_id: str, post_id: str) -> None:
        logger.warning("UNAUTHORIZED_RAG_ACCESS: user=%s, post=%s", user_id, post_id)
        if self._audit_logger:
            try:
                self._audit_logger.log_event(
                    event_type="unauthorized_access",
                    user_id=user_id,
                    resource_id=post_id,
                    action="rag_retrieve",
                    success=False,
                )
            except Exception as exc:
                logger.error("Audit log failed: %s", exc)

    def _log_access(self, user_id: str, post_id: Optional[str], chunk_count: int) -> None:
        if self._audit_logger:
            try:
                self._audit_logger.log_event(
                    event_type="rag_retrieve",
                    user_id=user_id,
                    resource_id=post_id or "all",
                    action="retrieve",
                    success=True,
                    details={"chunk_count": chunk_count},
                )
            except Exception as exc:
                logger.error("Audit log failed: %s", exc)
