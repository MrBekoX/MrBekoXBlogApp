"""RAG service - Retrieval Augmented Generation operations."""

import asyncio
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass

from app.core.config import settings
from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.domain.interfaces.i_vector_store import IVectorStore, VectorChunk
from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.services.retrieval_quality_scorer import RetrievalQualityScorer
from app.monitoring.metrics import record_tool_invocation
from app.security.backend_authorization_client import AuthorizationContext, BackendAuthorizationClient, PostAccessDecision
from app.services.bm25_index import BM25Index
from app.services.reranking_service import RerankingService
from app.services.query_expansion_service import QueryExpansionService

logger = logging.getLogger(__name__)

# Default retrieval parameters
DEFAULT_TOP_K = 5
MIN_SIMILARITY_THRESHOLD = 0.3


@contextmanager
def _log_step(step_name: str, timeout: float | None = None):
    """Context manager for logging RAG sub-step durations."""
    started_at = time.perf_counter()
    logger.debug(f"[RAG] Step '{step_name}' started{f' (timeout={timeout}s)' if timeout else ''}")
    try:
        yield
        duration = time.perf_counter() - started_at
        logger.info(f"[RAG] Step '{step_name}' completed in {duration:.3f}s")
    except asyncio.TimeoutError:
        duration = time.perf_counter() - started_at
        logger.warning(f"[RAG] Step '{step_name}' timed out after {duration:.3f}s")
        raise
    except Exception as e:
        duration = time.perf_counter() - started_at
        logger.error(f"[RAG] Step '{step_name}' failed after {duration:.3f}s: {type(e).__name__}: {e}")
        raise


@dataclass
class RetrievalResult:
    """Result of a retrieval operation."""

    chunks: list[VectorChunk]
    query: str
    post_id: str | None

    @property
    def context(self) -> str:
        """Get concatenated context from all chunks."""
        return "\n\n---\n\n".join(chunk.content for chunk in self.chunks)

    @property
    def has_results(self) -> bool:
        """Check if any results were found."""
        return len(self.chunks) > 0

    @property
    def average_similarity(self) -> float:
        """Get average similarity score of retrieved chunks."""
        if not self.chunks:
            return 0.0
        return sum(chunk.similarity_score for chunk in self.chunks) / len(self.chunks)


class RagService:
    """
    Service for RAG (Retrieval Augmented Generation) operations.

    Single Responsibility: Vector search and retrieval.
    Dependencies injected via constructor (DIP).

    Features:
    - Sub-step timing for observability (expand/embed/search/rerank)
    - Async reranking via to_thread
    - Configurable timeouts for query expansion
    """

    def __init__(
        self,
        embedding_provider: IEmbeddingProvider,
        vector_store: IVectorStore,
        llm_provider: ILLMProvider, # Added dependency
        scorer: RetrievalQualityScorer | None = None,
        bm25_index: BM25Index | None = None,
        reranker: RerankingService | None = None,
        query_expander: QueryExpansionService | None = None,
        backend_auth_client: BackendAuthorizationClient | None = None,
    ):
        self._embedding = embedding_provider
        self._vector_store = vector_store
        self._llm = llm_provider # Store it
        self._scorer = scorer or RetrievalQualityScorer()
        self._bm25 = bm25_index or BM25Index()
        self._reranker = reranker or RerankingService()
        self._query_expander = query_expander or QueryExpansionService(
            llm_provider,
            expand_timeout_seconds=getattr(settings, 'rag_expand_timeout_seconds', 5)
        )
        self._initialized = False
        self._authorization_client = backend_auth_client or BackendAuthorizationClient()

    async def initialize(self) -> None:
        """Initialize the RAG service."""
        if self._initialized:
            return

        await self._embedding.initialize()
        self._vector_store.initialize()
        self._bm25.initialize()
        self._reranker.initialize()
        await self._query_expander.initialize()
        self._initialized = True
        logger.info("RagService initialized")

    async def retrieve(
        self,
        query: str,
        post_id: str | None = None,
        k: int = DEFAULT_TOP_K,
        min_similarity: float = MIN_SIMILARITY_THRESHOLD,
        auth_context: AuthorizationContext | None = None
    ) -> RetrievalResult:
        """
        Retrieve relevant chunks using Query Expansion + Hybrid Search + Re-ranking.

        Args:
            query: The search query
            post_id: Optional post_id to limit search scope
            k: Number of chunks to retrieve
            min_similarity: Minimum similarity threshold (0-1)

        Returns:
            RetrievalResult containing relevant chunks
        """
        started_at = time.perf_counter()
        error: Exception | None = None
        if not self._initialized:
            await self.initialize()

        try:
            total_count = self._vector_store.get_total_count()
            if total_count <= 0:
                logger.info("[RAG] Vector store is empty, skipping retrieval")
                return RetrievalResult(
                    chunks=[],
                    query=query,
                    post_id=post_id,
                )

            access_decision: PostAccessDecision | None = None
            metadata_filter: dict[str, str] | None = None

            if post_id:
                access_decision = await self._authorize_post_access(post_id, auth_context)
                metadata_filter = self._build_metadata_filter(access_decision)
                self._backfill_post_metadata(post_id, access_decision)
                post_chunks = self._vector_store.get_post_chunks(post_id, metadata_filter=metadata_filter)
                if not post_chunks:
                    logger.info(f"[RAG] No indexed chunks for post_id={post_id}, skipping retrieval")
                    return RetrievalResult(
                        chunks=[],
                        query=query,
                        post_id=post_id,
                    )
            # 0. Query Expansion with sub-step logging
            with _log_step("expand"):
                queries = await self._query_expander.expand_query(query)
            if len(queries) > 1:
                logger.info(f"[RAG] Expanded query '{query}' to {len(queries)} variations")
            
            # We need to Aggregate results from ALL queries
            # Strategy: Perform lightweight retrieval for each query, then merge
            
            # INCREASE_CANDIDATES: Fetch more chunks for re-ranking (3x K)
            initial_k = k * 3
            
            all_candidates_map = {} # Map chunk_id -> chunk data (to deduplicate)
            
            for q in queries:
                # 1. Vector Search (Dense) with sub-step logging
                with _log_step("embed"):
                    q_embedding = await self._embedding.embed(q)

                with _log_step("search"):
                    vector_chunks = self._vector_store.search(
                        query_embedding=q_embedding,
                        post_id=post_id,
                        k=initial_k,
                        metadata_filter=metadata_filter,
                    )
                
                # 2. BM25 Search (Sparse)
                bm25_results = []
                if post_id:
                    bm25_results = self._bm25.search(q, post_id, k=initial_k)
                    
                # Normalize BM25
                if bm25_results:
                    max_bm25 = max(r['score'] for r in bm25_results)
                    if max_bm25 > 0:
                        for r in bm25_results:
                            r['normalized_score'] = r['score'] / max_bm25
                    else:
                        for r in bm25_results:
                            r['normalized_score'] = 0.0
                            
                # Merge into aggregated map
                # We treat occurrences in multiple queries as a signal boost?
                # For now, let's just take the max score if found multiple times
                
                current_q_map = {}
                
                for vc in vector_chunks:
                    current_q_map[vc.id] = {
                        'chunk': vc,
                        'vector_score': vc.similarity_score,
                        'bm25_score': 0.0
                    }
                    
                for bm in bm25_results:
                    chunk_id = f"{post_id}_{bm['chunk_index']}"
                    if chunk_id in current_q_map:
                        current_q_map[chunk_id]['bm25_score'] = bm['normalized_score']
                    else:
                        vc = VectorChunk(
                            id=chunk_id,
                            content=bm['content'],
                            post_id=post_id,
                            chunk_index=bm['chunk_index'],
                            section_title=bm.get('section_title'),
                            distance=1.0 - bm.get('normalized_score', 0)
                        )
                        current_q_map[chunk_id] = {
                            'chunk': vc,
                            'vector_score': 0.0,
                            'bm25_score': bm['normalized_score']
                        }
                
                # Fuse and add to global map
                # When BM25 index is missing, use vector-only scoring to avoid collapsing scores to near-zero
                has_bm25 = len(bm25_results) > 0
                vector_weight = 0.6 if has_bm25 else 1.0
                bm25_weight = 0.4 if has_bm25 else 0.0
                for chunk_id, data in current_q_map.items():
                    final_score = (vector_weight * data['vector_score']) + (bm25_weight * data['bm25_score'])
                    data['chunk'].distance = max(0.0, 1.0 - final_score)
                    
                    # Add to global map - keep the one with highest score
                    if chunk_id in all_candidates_map:
                        if final_score > all_candidates_map[chunk_id]['score']:
                            all_candidates_map[chunk_id] = {'chunk': data['chunk'], 'score': final_score}
                    else:
                        all_candidates_map[chunk_id] = {'chunk': data['chunk'], 'score': final_score}

            # Collect unique aggregated candidates
            aggregated_candidates = [item['chunk'] for item in all_candidates_map.values()]
            
            # Sort by score
            aggregated_candidates.sort(key=lambda x: x.similarity_score, reverse=True)
            
            # Limit candidates passed to re-ranker (don't send too many duplicates)
            # Maybe 3x K or 4x K depending on how many we expanded
            top_candidates = aggregated_candidates[:initial_k * 2] # Slightly more candidates due to expansion

            # 4. Re-ranking (Cross-Encoder) - Use async version to avoid blocking
            # Rerank against the ORIGINAL query (or maybe the best matching query?)
            # Re-ranking against the original query is safest to determine true intent match.
            if top_candidates:
                with _log_step("rerank"):
                    reranked_chunks = await self._reranker.rerank_async(query, top_candidates, top_k=k)
            else:
                reranked_chunks = []

            # 5. Final Filtering
            final_chunks = [
                chunk for chunk in reranked_chunks
                if chunk.similarity_score >= min_similarity
            ][:k]

            # Fallback: if filtering is too strict and drops all candidates, return best-ranked chunks.
            if not final_chunks and reranked_chunks:
                final_chunks = reranked_chunks[:k]

            return RetrievalResult(
                chunks=final_chunks,
                query=query,
                post_id=post_id
            )
        except Exception as exc:
            error = exc
            raise
        finally:
            record_tool_invocation(
                tool="rag",
                operation="retrieve",
                duration_seconds=time.perf_counter() - started_at,
                error=error,
            )

    async def retrieve_with_context(
        self,
        query: str,
        post_id: str,
        k: int = DEFAULT_TOP_K,
        include_neighbors: bool = True,
        auth_context: AuthorizationContext | None = None
    ) -> RetrievalResult:
        """
        Retrieve chunks with additional context from neighboring chunks.

        Args:
            query: The search query
            post_id: Post ID to search within
            k: Number of primary chunks to retrieve
            include_neighbors: Whether to include neighboring chunks

        Returns:
            RetrievalResult with expanded context
        """
        result = await self.retrieve(query, post_id, k, auth_context=auth_context)

        if not result.has_results or not include_neighbors:
            return result

        access_decision = await self._authorize_post_access(post_id, auth_context)
        metadata_filter = self._build_metadata_filter(access_decision)
        self._backfill_post_metadata(post_id, access_decision)

        # Get all chunks for the post to find neighbors
        all_chunks = self._vector_store.get_post_chunks(post_id, metadata_filter=metadata_filter)
        chunk_map = {chunk.chunk_index: chunk for chunk in all_chunks}

        # Expand results with neighbors
        expanded_indices: set[int] = set()
        for chunk in result.chunks:
            expanded_indices.add(chunk.chunk_index)
            if chunk.chunk_index - 1 in chunk_map:
                expanded_indices.add(chunk.chunk_index - 1)
            if chunk.chunk_index + 1 in chunk_map:
                expanded_indices.add(chunk.chunk_index + 1)

        # Build expanded chunk list
        expanded_chunks = [
            chunk_map[idx]
            for idx in sorted(expanded_indices)
            if idx in chunk_map
        ]

        return RetrievalResult(
            chunks=expanded_chunks,
            query=query,
            post_id=post_id
        )

    async def _authorize_post_access(
        self,
        post_id: str,
        auth_context: AuthorizationContext | None,
    ) -> PostAccessDecision:
        context = auth_context or AuthorizationContext.anonymous()
        action = "ViewPublished" if context.subject_type == "anonymous" else "ViewUnpublished"
        try:
            decision = await self._authorization_client.authorize_post_access(
                post_id=post_id,
                action=action,
                auth_context=context,
            )
        except Exception as exc:
            raise PermissionError("rag_authorization_unavailable") from exc

        if not decision.allowed:
            raise PermissionError(f"Access denied to post {post_id}")

        return decision

    @staticmethod
    def _build_metadata_filter(decision: PostAccessDecision) -> dict[str, str]:
        metadata_filter = {"visibility": decision.visibility}
        if decision.visibility != "published" and decision.author_id:
            metadata_filter["author_id"] = decision.author_id
        return metadata_filter

    def _backfill_post_metadata(self, post_id: str, decision: PostAccessDecision) -> None:
        ensure_method = getattr(self._vector_store, "ensure_post_metadata", None)
        if not callable(ensure_method):
            return

        try:
            ensure_method(post_id, decision.visibility, decision.author_id)
        except Exception as exc:
            logger.warning("[RAG] Failed to backfill metadata for post_id=%s: %s", post_id, exc)

    def get_post_chunks(self, post_id: str) -> list[VectorChunk]:
        """Get all chunks for a specific post."""
        return self._vector_store.get_post_chunks(post_id)

    def get_total_count(self) -> int:
        """Get total number of indexed chunks."""
        return self._vector_store.get_total_count()







