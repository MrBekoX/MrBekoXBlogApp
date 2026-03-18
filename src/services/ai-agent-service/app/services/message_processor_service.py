"""Message processor service - Handles RabbitMQ message processing.

Integrates autonomous agent for complex multi-step queries while maintaining
article-bound constraints (off-topic questions are rejected).
"""

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import ValidationError

from app.core.config import settings
from app.core.logging_utils import set_request_id, clear_request_id, trace_span, log_error_with_context
from app.monitoring.metrics import (
    classify_failure_reason,
    record_worker_message,
)
from app.domain.interfaces.i_cache import ICache
from app.domain.interfaces.i_message_broker import IMessageBroker
from app.domain.entities.article import ArticleMessage, ProcessingResult
from app.domain.entities.chat import ChatRequestMessage, ChatMessage
from app.domain.entities.ai_generation import (
    AiTitleGenerationMessage,
    AiExcerptGenerationMessage,
    AiTagsGenerationMessage,
    AiSeoDescriptionGenerationMessage,
    AiContentImprovementMessage,
    AiSummarizeMessage,
    AiKeywordsMessage,
    AiSentimentMessage,
    AiReadingTimeMessage,
    AiGeoOptimizeMessage,
    AiCollectSourcesMessage,
)
from app.services.analysis_service import AnalysisService
from app.services.indexing_service import IndexingService
from app.services.chat_service import ChatService
from app.security.backend_authorization_client import AuthorizationContext, BackendAuthorizationClient
logger = logging.getLogger(__name__)

# Article-bound constraint markers - queries with these are likely off-topic
OFF_TOPIC_MARKERS = [
    # General knowledge questions
    "hava nasil", "what is the weather", "bugun hava",
    "saat kac", "what time is it",
    "kim president", "who is the president", "bakan kim",
    "tarif", "recipe", "yemek tarifi",
    "film oner", "movie recommendation", "dizi oner",
    # Personal questions
    "sen kimsin", "who are you", "adin ne", "what is your name",
    "nasilsin", "how are you", "canin var mi",
    # Unrelated technical topics (not in blog context)
    "bitcoin fiyat", "bitcoin price", "borsa", "stock market",
    "futbol", "football", "mac sonuc",
]

# Complex query markers that trigger autonomous agent
COMPLEX_QUERY_MARKERS = [
    "karsilastir", "compare", "fark", "difference", "vs",
    "ve sonra", "and then", "ayrica", "also", "sonra",
    "analiz", "analyze", "neden", "why", "nasil", "how does",
    "once", "first", "ardindan", "after that", "ve",
    "kapsamli", "comprehensive", "detayli", "detailed",
]

# Intent markers used to infer web search when UI flag is not provided.
WEB_SEARCH_INTENT_PATTERNS = [
    r"\bweb\s*'?de\b.*\b(ara|bul|arastir|search)\b",
    r"\binternet(te|ten)?\b.*\b(ara|bul|arastir|search)\b",
    r"\b(ara|bul|arastir|search|google|look up)\b.*\b(web|internet|online)\b",
    r"\b(search the web|web search|online search|look it up)\b",
    r"\b(guncel|latest|current)\b.*\b(ara|search|research)\b",
]

# Routing keys
AI_ANALYSIS_COMPLETED = "ai.analysis.completed"
CHAT_RESPONSE_KEY = "chat.message.completed"
CHAT_CHUNK_KEY = "chat.chunk.completed"
T = TypeVar("T")
OPERATION_CONSUMER_NAME = "message-processor"


class TransientProcessingError(RuntimeError):
    """Raised for transient worker failures that should be retried."""


class MessageProcessorService:
    """
    Service for processing messages from the message broker.

    Implements idempotency pattern with distributed locking.

    Features:
    - RAG-based chat for simple article questions
    - Autonomous agent for complex multi-step queries
    - Article-bound constraint: off-topic questions are rejected
    """

    def __init__(
        self,
        cache: ICache,
        message_broker: IMessageBroker,
        analysis_service: AnalysisService,
        indexing_service: IndexingService,
        chat_service: ChatService,
        autonomous_agent: Any | None = None,
        backend_auth_client: BackendAuthorizationClient | None = None,
    ):
        self._cache = cache
        self._broker = message_broker
        self._analysis = analysis_service
        self._indexing = indexing_service
        self._chat = chat_service
        self._autonomous = autonomous_agent
        self._authorization_client = backend_auth_client or BackendAuthorizationClient()
        self._operation_timeout_seconds = max(1, settings.worker_operation_timeout_seconds)
        self._publish_timeout_seconds = max(1, settings.broker_publish_timeout_seconds)
        self._retry_attempts = max(1, settings.worker_retry_attempts)
        self._retry_base_delay_seconds = max(0.05, settings.worker_retry_base_delay_seconds)
        self._max_retry_backoff_seconds = max(
            self._retry_base_delay_seconds,
            settings.worker_retry_max_backoff_seconds,
        )

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        """Classify exceptions that are safe to retry."""
        if isinstance(error, (TransientProcessingError, TimeoutError, ConnectionError, OSError)):
            return True

        text = str(error).lower()
        retry_markers = (
            "timeout",
            "timed out",
            "temporarily unavailable",
            "service unavailable",
            "connection",
            "429",
            "503",
            "too many requests",
        )
        return any(marker in text for marker in retry_markers)

    @staticmethod
    def _classify_processing_failure(error: Exception) -> str:
        """Map processing exceptions to broker retry semantics."""
        reason = classify_failure_reason(error)

        if reason == "timeout":
            return "transient:timeout"
        if reason == "connection_error":
            return "transient:connection_error"
        if reason == "rate_limited":
            return "transient:rate_limited"
        if reason == "circuit_open":
            return "transient:circuit_open"
        if reason == "validation_error":
            return "malformed:validation_error"
        if reason == "permission_denied":
            return "non_recoverable:permission_denied"
        if reason == "not_found":
            return "non_recoverable:not_found"
        return f"error:{reason}"

    async def _process_chat(self, message: ChatRequestMessage) -> dict:
        """Process chat message with article-bound constraints.

        Flow:
        1. Check if query is off-topic (reject if so)
        2. Check complexity level
        3. Route to appropriate handler:
           - Simple: Direct RAG via ChatService
           - Complex + Autonomous enabled: AutonomousAgent
           - Web search enabled: Hybrid search
        """
        payload = message.payload
        user_message = payload.userMessage.strip()
        user_message_lower = user_message.lower()
        language = payload.language or "tr"

        auth_context = AuthorizationContext.from_payload(payload.authContext.model_dump())
        logger.info(f"Processing chat: postId={payload.postId}, sessionId={payload.sessionId}")

        await self._authorize_chat_post_access(payload.postId, auth_context)

        if self._is_off_topic(user_message_lower):
            logger.info(f"[ChatBound] Off-topic query rejected: {user_message[:50]}...")
            return {
                "response": self._get_off_topic_response(language),
                "isWebSearchResult": False,
                "sources": None,
            }

        normalized_message = self._normalize_intent_text(user_message)
        summary_patterns = [
            r"^(bu\s+)?makaleyi\s+ozetle",
            r"^makalenin\s+ozet",
            r"^bu\s+makalenin\s+ozeti",
            r"^summarize\s+(the\s+)?article",
            r"^article\s+summary",
        ]
        if any(re.search(pattern, normalized_message) for pattern in summary_patterns):
            logger.info("Summary request detected, generating AI summary")
            summary = await self._analysis.summarize_article(
                content=payload.articleContent,
                max_sentences=5,
                language=language,
            )
            return {
                "response": summary,
                "isWebSearchResult": False,
                "sources": None,
            }

        use_web_search = bool(payload.enableWebSearch) or self._has_web_search_intent(user_message)
        if use_web_search and not payload.enableWebSearch:
            logger.info("[ChatRoute] Web-search intent detected from message, enabling hybrid path")

        if use_web_search:
            response = await self._chat.chat_with_web_search(
                post_id=payload.postId,
                user_message=user_message,
                article_title=payload.articleTitle,
                article_content=payload.articleContent,
                language=language,
                auth_context=auth_context,
            )
            return {
                "response": response.response,
                "isWebSearchResult": bool(response.sources),
                "sources": response.sources,
            }

        is_complex = self._is_complex_query(user_message_lower)
        is_highly_complex = self._is_highly_complex_query(user_message_lower)

        if self._autonomous and (is_complex or is_highly_complex):
            complexity = "highly_complex" if is_highly_complex else "complex"
            logger.info(f"[ChatRoute] {complexity} query -> ChatAgent (ReAct/Autonomous)")

            try:
                agent_payload = {
                    "postId": payload.postId,
                    "userMessage": user_message,
                    "sessionId": payload.sessionId,
                    "articleTitle": payload.articleTitle,
                    "articleContent": payload.articleContent,
                    "operationId": getattr(message, "operationId", None),
                    "enableWebSearch": payload.enableWebSearch,
                    "complexityLevel": complexity,
                    "conversationHistory": [
                        {"role": h.role, "content": h.content}
                        for h in payload.conversationHistory
                    ],
                    "authContext": {
                        "subjectType": auth_context.subject_type,
                        "subjectId": auth_context.subject_id,
                        "roles": auth_context.roles,
                        "fingerprint": auth_context.fingerprint,
                    },
                }

                result = await self._autonomous.execute(agent_payload, language)
                response_text = result.get("response", "")

                if self._response_violates_bounds(response_text, payload.articleContent):
                    logger.warning("[ChatBound] Agent response violated bounds, using RAG fallback")
                else:
                    return {
                        "response": response_text,
                        "isWebSearchResult": result.get("isWebSearchResult", False),
                        "sources": result.get("sources"),
                        "plan": result.get("plan"),
                        "iterations": result.get("iterations"),
                    }

            except Exception as e:
                logger.warning(f"[ChatRoute] ChatAgent failed: {e}, falling back to RAG")

        history = [
            ChatMessage(role=h.role, content=h.content)
            for h in payload.conversationHistory
        ]

        response = await self._chat.chat(
            post_id=payload.postId,
            user_message=user_message,
            conversation_history=history,
            language=language,
            auth_context=auth_context,
        )

        return {
            "response": response.response,
            "isWebSearchResult": False,
            "sources": None,
        }

    async def _authorize_chat_post_access(
        self,
        post_id: str,
        auth_context: AuthorizationContext,
    ) -> None:
        decision = await self._authorization_client.authorize_post_access(
            post_id=post_id,
            action="ViewPublished",
            auth_context=auth_context,
        )
        if not decision.allowed:
            raise PermissionError(f"Access denied to post {post_id}")

    @staticmethod
    def _is_off_topic(message_lower: str) -> bool:
        """Check if query is clearly off-topic (not article-related)."""
        # Check for off-topic markers
        for marker in OFF_TOPIC_MARKERS:
            if marker in message_lower:
                return True

        # Very short greetings without article context
        greeting_only = [
            "merhaba", "selam", "hi", "hello", "hey",
            "nasilsin", "how are you", "naber",
        ]
        words = message_lower.split()
        if len(words) <= 3:
            for greeting in greeting_only:
                if greeting in message_lower:
                    return False  # Allow greetings, ChatService handles them

        return False

    @staticmethod
    def _normalize_intent_text(message: str) -> str:
        """Normalize text for lightweight intent matching."""
        normalized = (message or "").lower().strip()
        normalized = normalized.translate(
            str.maketrans(
                {
                    "\u0131": "i",
                    "\u011f": "g",
                    "\u00fc": "u",
                    "\u015f": "s",
                    "\u00f6": "o",
                    "\u00e7": "c",
                }
            )
        )
        replacements = {
            "ÃƒÆ’Ã¢â‚¬ÂÃƒâ€šÃ‚Â±": "i",
            "ÃƒÆ’Ã¢â‚¬ÂÃƒâ€¦Ã‚Â¸": "g",
            "ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¼": "u",
            "ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€¦Ã‚Â¸": "s",
            "ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¶": "o",
            "ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§": "c",
        }
        for bad, good in replacements.items():
            normalized = normalized.replace(bad, good)
        return re.sub(r"\s+", " ", normalized)

    def _has_web_search_intent(cls, message: str) -> bool:
        """Detect explicit web-search request from natural language."""
        normalized = cls._normalize_intent_text(message)
        if not normalized:
            return False
        return any(re.search(pattern, normalized) for pattern in WEB_SEARCH_INTENT_PATTERNS)

    @staticmethod
    def _is_complex_query(message_lower: str) -> bool:
        """Detect queries that benefit from multi-step reasoning."""
        # Multi-part questions
        if message_lower.count("?") > 1:
            return True

        # Complexity markers
        for marker in COMPLEX_QUERY_MARKERS:
            if marker in message_lower:
                return True

        # Long queries likely need reasoning
        if len(message_lower.split()) > 20:
            return True

        return False

    @staticmethod
    def _is_highly_complex_query(message_lower: str) -> bool:
        """Detect queries requiring autonomous planning.

        Uses stricter thresholds to avoid over-classification:
        - Requires 3+ task indicators (was 2)
        - Requires 40+ words (was 30)
        - Uses more specific multi-step patterns
        """
        # Count task indicators more strictly
        task_count = 0
        task_indicators = [
            " ve ", " and ", "sonra", "then", "ardindan",
            "ayrica", "also", "plus", "ve sonra", "and then",
        ]
        for indicator in task_indicators:
            # Count each indicator only once, use longer phrases first
            if indicator in message_lower:
                task_count += 1

        # Require 3+ task indicators (was 2)
        if task_count >= 3:
            return True

        # More specific multi-step action markers (require at least 2)
        multi_step = [
            "once", "first", "sonra", "then", "ardindan", "after",
            "kapsamli", "comprehensive", "rapor", "report",
            "analiz et", "analyze", "detayli", "detailed",
            "adim adim", "step by step", "sirasiyla", "sequentially",
        ]
        multi_step_count = sum(1 for m in multi_step if m in message_lower)
        if multi_step_count >= 2:
            return True

        # Very long queries - increased threshold from 30 to 40
        if len(message_lower.split()) > 40:
            return True

        return False

    @staticmethod
    def _response_violates_bounds(response: str, article_content: str) -> bool:
        """Check if response contains content clearly outside article scope."""
        if not response or not article_content:
            return False

        # Check for obvious hallucination markers
        violation_markers = [
            "as a language model",
            "i don't have access to",
            "i cannot browse",
            "my knowledge cutoff",
        ]
        response_lower = response.lower()
        for marker in violation_markers:
            if marker in response_lower:
                return True

        return False

    @staticmethod
    def _get_off_topic_response(language: str) -> str:
        """Get response for off-topic questions."""
        if language == "tr":
            return (
                "Bu soru makalenin kapsami disindadir. "
                "Ben sadece bu blog makalesindeki konular hakkinda yardimci olabilirim. "
                "Lutfen makale ile ilgili bir soru sorun."
            )
        return (
            "This question is outside the article's scope. "
            "I can only help with topics covered in this blog article. "
            "Please ask a question related to the article."
        )

    async def _process_ai_request(self, message: Any, msg_type: str) -> dict:
        """Process AI generation request.

        NOTE: When ``settings.agent_use_langgraph`` is True, messages are routed
        through ``RabbitMQConsumer`` *before* reaching this method.
        This path serves as the legacy fallback.
        """
        payload = message.payload
        content = getattr(payload, "content", "") or getattr(payload, "query", "")
        language = payload.language or "tr"

        if msg_type == "title":
            summary = await self._analysis.summarize_article(content, 1, language)
            return {"title": summary}
        elif msg_type == "excerpt":
            summary = await self._analysis.summarize_article(content, 3, language)
            return {"excerpt": summary}
        elif msg_type == "tags":
            keywords = await self._analysis.extract_keywords(content, 5, language)
            return {"tags": keywords}
        elif msg_type == "seo":
            desc = await self._analysis._generate_seo_description(content, language)
            return {"description": desc}
        elif msg_type == "content":
            summary = await self._analysis.summarize_article(content, 3, language)
            return {"improvedContent": summary}
        elif msg_type == "summarize":
            max_sentences = getattr(payload, "maxSentences", 5)
            summary = await self._analysis.summarize_article(content, max_sentences, language)
            return {"summary": summary}
        elif msg_type == "keywords":
            max_keywords = getattr(payload, "maxKeywords", 10)
            keywords = await self._analysis.extract_keywords(content, max_keywords, language)
            return {"keywords": keywords}
        elif msg_type == "sentiment":
            sentiment = await self._analysis.analyze_sentiment(content, language)
            return {
                "sentiment": sentiment.sentiment,
                "confidence": sentiment.confidence
            }
        elif msg_type == "reading-time":
            # calculate_reading_time is synchronous
            reading_time = self._analysis.calculate_reading_time(content)
            return {
                "readingTimeMinutes": reading_time.reading_time_minutes,
                "wordCount": reading_time.word_count
            }
        elif msg_type == "geo-optimize":
            target_region = getattr(payload, "targetRegion", "TR")
            # Use seo_service if available, otherwise fallback
            if self._analysis._seo_service:
                geo_opt = await self._analysis._seo_service.optimize_for_geo(content, target_region, language)
                return {"geoOptimization": geo_opt.model_dump() if geo_opt else None}
            else:
                # Fallback to basic optimization
                return {"geoOptimization": None}
        elif msg_type == "collect-sources":
            # Web search for sources
            max_sources = getattr(payload, "maxSources", 5)
            query = content  # In this case, content is actually the query
            sources = await self._collect_web_sources(query, max_sources, language)
            return {"sources": sources}
        else:
            raise ValueError(f"Unknown message type: {msg_type}")

    async def _publish_analysis_result(
        self,
        article_id: str,
        result: ProcessingResult,
        correlation_id: str | None
    ) -> bool:
        """Publish analysis result."""
        message = {
            "messageId": str(uuid.uuid4()),
            "correlationId": correlation_id or str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "eventType": "ai.analysis.completed",
            "payload": {
                "postId": article_id,
                "summary": result.summary,
                "keywords": result.keywords,
                "seoDescription": result.seo_description,
                "readingTime": result.reading_time_minutes,
                "sentiment": result.sentiment,
                "geoOptimization": result.geo_optimization,
            }
        }
        return await self._broker.publish(AI_ANALYSIS_COMPLETED, message, correlation_id)

    async def _publish_chat_result(
        self,
        session_id: str,
        result: dict,
        correlation_id: str | None,
        operation_id: str | None = None,
    ) -> bool:
        """Publish chat response."""
        message = {
            "messageId": str(uuid.uuid4()),
            "correlationId": correlation_id or str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "eventType": "chat.message.completed",
            "operationId": operation_id,
            "payload": {
                "sessionId": session_id,
                "response": result.get("response", ""),
                "isWebSearchResult": result.get("isWebSearchResult", False),
                "sources": result.get("sources")
            }
        }
        return await self._broker.publish(CHAT_RESPONSE_KEY, message, correlation_id)

    async def _publish_chat_chunk(
        self,
        session_id: str,
        chunk: str,
        sequence: int,
        is_final: bool,
        correlation_id: str | None,
        operation_id: str | None = None,
    ) -> bool:
        """Publish chat chunk for streaming responses."""
        message = {
            "messageId": str(uuid.uuid4()),
            "correlationId": correlation_id or str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "eventType": "chat.chunk.completed",
            "operationId": operation_id,
            "payload": {
                "sessionId": session_id,
                "chunk": chunk,
                "sequence": sequence,
                "isFinal": is_final
            }
        }
        return await self._broker.publish(CHAT_CHUNK_KEY, message, correlation_id)

    async def _process_chat_stream(
        self,
        message: ChatRequestMessage,
        correlation_id: str | None
    ) -> None:
        """Process chat message with streaming chunks via RabbitMQ."""
        payload = message.payload
        session_id = payload.sessionId
        user_message = payload.userMessage.strip()
        language = payload.language or "tr"
        operation_id = getattr(message, "operationId", None)

        logger.info(f"Processing streaming chat: postId={payload.postId}, sessionId={session_id}")

        sequence = 0
        full_response = ""

        try:
            async for chunk in self._chat.chat_stream(
                post_id=payload.postId,
                user_message=user_message,
                conversation_history=[
                    ChatMessage(role=h.role, content=h.content)
                    for h in payload.conversationHistory
                ],
                language=language
            ):
                full_response += chunk
                await self._publish_chat_chunk(
                    session_id=session_id,
                    chunk=chunk,
                    sequence=sequence,
                    is_final=False,
                    correlation_id=correlation_id,
                    operation_id=operation_id,
                )
                sequence += 1

            await self._publish_chat_chunk(
                session_id=session_id,
                chunk="",
                sequence=sequence,
                is_final=True,
                correlation_id=correlation_id,
                operation_id=operation_id,
            )

            logger.info(f"Streaming chat completed: sessionId={session_id}, chunks={sequence}")

        except Exception as e:
            logger.error(f"Streaming chat failed: {e}")
            await self._publish_chat_chunk(
                session_id=session_id,
                chunk=f"Error: {str(e)}",
                sequence=sequence,
                is_final=True,
                correlation_id=correlation_id,
                operation_id=operation_id,
            )
            raise

    async def _publish_ai_result(
        self,
        request_id: str,
        result: dict,
        msg_type: str,
        correlation_id: str | None
    ) -> bool:
        """Publish AI generation result."""
        event_types = {
            "title": "ai.title.generation.completed",
            "excerpt": "ai.excerpt.generation.completed",
            "tags": "ai.tags.generation.completed",
            "seo": "ai.seo.generation.completed",
            "summarize": "ai.summarize.completed",
            "keywords": "ai.keywords.completed",
            "sentiment": "ai.sentiment.completed",
            "reading-time": "ai.reading-time.completed",
            "geo-optimize": "ai.geo-optimize.completed",
            "collect-sources": "ai.collect-sources.completed",
        }
        event_type = event_types.get(msg_type, f"ai.{msg_type}.completed")

        message = {
            "messageId": str(uuid.uuid4()),
            "correlationId": correlation_id or str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "eventType": event_type,
            "payload": {"requestId": request_id, **result}
        }
        return await self._broker.publish(event_type, message, correlation_id)

    async def _collect_web_sources(self, query: str, max_sources: int, language: str) -> list[dict]:
        """Collect web sources for a query using web search."""
        try:
            # Use web search if available via chat service
            if hasattr(self._chat, '_web_search') and self._chat._web_search:
                results = await self._chat._web_search.search(query, max_results=max_sources)
                return [
                    {
                        "title": r.title,
                        "url": r.url,
                        "snippet": r.snippet
                    }
                    for r in results[:max_sources]
                ]
        except Exception as e:
            logger.warning(f"Web source collection failed: {e}")

        return []

    # ─── Event classification ─────────────────────────────────────────

    _EVENT_TYPE_MAP: dict[str, str] = {
        "chat.message.requested": "chat",
        "chatrequestedevent": "chat",
        "article.published": "article_published",
        "articlepublishedevent": "article_published",
        "article.created": "article",
        "articlecreatedevent": "article",
        "article.updated": "article",
        "articleupdatedevent": "article",
    }

    _AI_EVENT_PREFIXES: list[tuple[str, str]] = [
        ("ai.title", "title"),
        ("ai.excerpt", "excerpt"),
        ("ai.tags", "tags"),
        ("ai.seo", "seo"),
        ("ai.content", "content"),
        ("ai.summarize", "summarize"),
        ("ai.keywords", "keywords"),
        ("ai.sentiment", "sentiment"),
        ("ai.reading-time", "reading-time"),
        ("ai.geo-optimize", "geo-optimize"),
        ("ai.collect-sources", "collect-sources"),
    ]

    _AI_MESSAGE_MODELS: dict[str, type] = {
        "title": AiTitleGenerationMessage,
        "excerpt": AiExcerptGenerationMessage,
        "tags": AiTagsGenerationMessage,
        "seo": AiSeoDescriptionGenerationMessage,
        "content": AiContentImprovementMessage,
        "summarize": AiSummarizeMessage,
        "keywords": AiKeywordsMessage,
        "sentiment": AiSentimentMessage,
        "reading-time": AiReadingTimeMessage,
        "geo-optimize": AiGeoOptimizeMessage,
        "collect-sources": AiCollectSourcesMessage,
    }

    @classmethod
    def _classify_event(cls, event_type: str) -> str:
        """Classify raw eventType string to normalized message type."""
        et = event_type.lower()
        mapped = cls._EVENT_TYPE_MAP.get(et)
        if mapped:
            return mapped
        for prefix, msg_type in cls._AI_EVENT_PREFIXES:
            if et.startswith(prefix):
                return msg_type
        return "article"

    # ─── Public entry point ───────────────────────────────────────────

    async def process_message(self, body: bytes) -> tuple[bool, str]:
        """Parse, route and process a single RabbitMQ message.

        Returns:
            (success, reason) tuple compatible with the broker consumer contract.
        """
        started_at = time.perf_counter()

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            logger.error("[MPS] Invalid JSON: %s", exc)
            return False, "malformed:json"

        event_type_raw = data.get("eventType", "")
        message_id = data.get("messageId", str(uuid.uuid4()))
        correlation_id = data.get("correlationId") or message_id
        payload = data.get("payload", {})
        msg_type = self._classify_event(event_type_raw)

        set_request_id(correlation_id)
        try:
            logger.info(
                "[MPS] Processing message_id=%s event=%s type=%s",
                message_id, event_type_raw, msg_type,
            )

            published = False
            with trace_span("mps.process", event_type=msg_type):
                if msg_type == "chat":
                    try:
                        chat_msg = ChatRequestMessage(**data)
                    except ValidationError as exc:
                        logger.error("[MPS] Chat validation failed: %s", exc)
                        return False, "malformed:validation_error"
                    result = await self._process_chat(chat_msg)
                    session_id = chat_msg.payload.sessionId
                    operation_id = getattr(chat_msg, "operationId", None)
                    published = await self._publish_chat_result(
                        session_id, result, correlation_id, operation_id,
                    )

                elif msg_type in ("article", "article_published"):
                    try:
                        article_msg = ArticleMessage(**data)
                    except ValidationError as exc:
                        logger.error("[MPS] Article validation failed: %s", exc)
                        return False, "malformed:validation_error"
                    ap = article_msg.payload
                    await self._indexing.index_article(
                        post_id=ap.articleId,
                        title=ap.title,
                        content=ap.content,
                        author_id=ap.authorId,
                        visibility=getattr(ap, "visibility", "published"),
                    )
                    region = getattr(ap, "targetRegion", "TR")
                    language = ap.language or "tr"
                    analysis = await self._analysis.full_analysis(
                        content=ap.content, target_region=region, language=language,
                    )
                    processing_result = ProcessingResult(
                        article_id=ap.articleId,
                        summary=analysis.summary,
                        keywords=analysis.keywords,
                        seo_description=analysis.seo_description,
                        reading_time_minutes=analysis.reading_time.reading_time_minutes,
                        word_count=analysis.reading_time.word_count,
                        sentiment=analysis.sentiment.sentiment,
                        sentiment_confidence=analysis.sentiment.confidence,
                        geo_optimization=(
                            analysis.geo_optimization.model_dump()
                            if analysis.geo_optimization
                            else None
                        ),
                        processed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    published = await self._publish_analysis_result(
                        ap.articleId, processing_result, correlation_id,
                    )

                else:
                    # AI generation request
                    model_cls = self._AI_MESSAGE_MODELS.get(msg_type)
                    if not model_cls:
                        logger.error("[MPS] Unknown message type: %s", msg_type)
                        return False, f"malformed:unknown_type:{msg_type}"
                    try:
                        typed_msg = model_cls(**data)
                    except ValidationError as exc:
                        logger.error("[MPS] AI generation validation failed: %s", exc)
                        return False, "malformed:validation_error"
                    result = await self._process_ai_request(typed_msg, msg_type)
                    published = await self._publish_ai_result(
                        message_id, result, msg_type, correlation_id,
                    )

            if not published:
                logger.error("[MPS] Publish failed for %s", msg_type)
                return False, "transient:publish_failed"

            duration = time.perf_counter() - started_at
            record_worker_message(msg_type, True, duration)
            logger.info(
                "[MPS] Completed message_id=%s type=%s in %.2fs",
                message_id, msg_type, duration,
            )
            return True, "success"

        except PermissionError as exc:
            logger.warning("[MPS] Permission denied: %s", exc)
            return False, "non_recoverable:permission_denied"
        except ValidationError as exc:
            logger.error("[MPS] Validation error: %s", exc)
            return False, "malformed:validation_error"
        except Exception as exc:
            duration = time.perf_counter() - started_at
            record_worker_message(msg_type, False, duration)
            if self._is_retryable_error(exc):
                reason = self._classify_processing_failure(exc)
                logger.warning("[MPS] Retryable error: %s (%s)", exc, reason)
                return False, reason
            logger.exception("[MPS] Non-recoverable error for message_id=%s", message_id)
            return False, f"non_recoverable:{type(exc).__name__}"
        finally:
            clear_request_id()


















