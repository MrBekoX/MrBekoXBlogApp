"""RAG retrieval tool for ReAct/autonomous agents."""

import logging
from typing import Any, TYPE_CHECKING

from app.security.backend_authorization_client import AuthorizationContext

if TYPE_CHECKING:
    from app.services.rag_service import RagService

logger = logging.getLogger(__name__)


class RagRetrieveTool:
    """Wraps RagService as a callable tool for the ReAct loop."""

    name: str = "rag_retrieve"
    description: str = "Retrieve relevant article chunks from the knowledge base."

    def __init__(self, rag_service: "RagService"):
        self._rag = rag_service

    async def __call__(self, query: str, post_id: str = "", **kwargs: Any) -> str:
        try:
            k = kwargs.get("k", 5)
            auth_context = kwargs.get("auth_context")
            if isinstance(auth_context, dict):
                auth_context = AuthorizationContext.from_payload(auth_context)

            result = await self._rag.retrieve_with_context(
                query=query,
                post_id=post_id,
                k=k,
                auth_context=auth_context,
            )
            if not result.has_results:
                return "No relevant article sections found."
            return result.context[:3000]
        except Exception as exc:
            logger.warning("[RagRetrieveTool] Retrieval failed: %s", exc)
            return f"RAG retrieval failed: {exc}"
