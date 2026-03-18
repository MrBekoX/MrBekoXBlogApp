"""RabbitMQ consumer that processes messages through LangGraph workflows."""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from langgraph.graph import END, StateGraph
from app.graph.state import AgentState
from app.core.config import settings
from app.monitoring.metrics import (
    record_idempotency_replay,
    record_stage_cache,
)
from app.logging.agent_logger import AgentLogger
from app.domain.interfaces.i_cache import ICache
from app.domain.interfaces.i_message_broker import IMessageBroker
from app.services.analysis_service import AnalysisService
from app.services.indexing_service import IndexingService
from app.services.chat_service import ChatService
from app.agents.supervisor import SupervisorAgent
from app.security.audit_logger import AuditLogger
from app.security.jailbreak_detector import SemanticJailbreakDetector
from app.security.backend_authorization_client import AuthorizationContext, BackendAuthorizationClient
from app.security.incident_tracker import incident_tracker as _incident_tracker, IncidentSeverity

logger = logging.getLogger(__name__)
_audit = AuditLogger()
_jailbreak_detector = SemanticJailbreakDetector(use_llm=False)

# Routing keys
AI_ANALYSIS_COMPLETED = "ai.analysis.completed"
CHAT_RESPONSE_KEY = "chat.message.completed"

# Event type -> target agent mapping
EVENT_AGENT_MAP: dict[str, str] = {
    "chat": "chat",
    "article": "analyzer",
    "article_published": "analyzer",
    "title": "generation",
    "excerpt": "generation",
    "tags": "generation",
    "seo": "generation",
    "content": "generation",
    "summarize": "generation",
    "keywords": "generation",
    "sentiment": "generation",
    "reading-time": "generation",
    "geo-optimize": "generation",
    "collect-sources": "generation",
}

OPERATION_CONSUMER_NAME = "langgraph"

WEB_SEARCH_INTENT_PATTERNS = [
    r"\bweb\s*'?de\b.*\b(ara|bul|arastir|search)\b",
    r"\binternet(te|ten)?\b.*\b(ara|bul|arastir|search)\b",
    r"\b(ara|bul|arastir|search|google|look up)\b.*\b(web|internet|online)\b",
    r"\b(search the web|web search|online search|look it up)\b",
    r"\b(guncel|latest|current)\b.*\b(ara|search|research)\b",
]


class RabbitMQConsumer:
    """Consumes RabbitMQ messages through a LangGraph workflow.

    The workflow is: router -> process -> respond -> END
    In Phase 1 this wraps the existing services as LangGraph nodes
    for backward compatibility while establishing the graph foundation.
    """

    def __init__(
        self,
        cache: ICache,
        message_broker: IMessageBroker,
        analysis_service: AnalysisService,
        indexing_service: IndexingService,
        chat_service: ChatService,
        supervisor: SupervisorAgent | None = None,
        backend_auth_client: BackendAuthorizationClient | None = None,
    ):
        self._cache = cache
        self._broker = message_broker
        self._analysis = analysis_service
        self._indexing = indexing_service
        self._chat = chat_service
        self._supervisor = supervisor
        self._authorization_client = backend_auth_client or BackendAuthorizationClient()
        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        """Build the LangGraph StateGraph workflow."""
        builder = StateGraph(AgentState)

        builder.add_node("router", self._router_node)
        builder.add_node("process", self._process_node)
        builder.add_node("respond", self._respond_node)

        builder.set_entry_point("router")
        builder.add_edge("router", "process")
        builder.add_edge("process", "respond")
        builder.add_edge("respond", END)

        return builder.compile()

    async def _router_node(self, state: AgentState) -> dict:
        """Route the message to the appropriate agent based on event_type."""
        event_type = state.get("event_type", "")
        target = EVENT_AGENT_MAP.get(event_type, "analyzer")
        logger.info(
            f"[LangGraph:router] event_type={event_type} -> target_agent={target} "
            f"thread_id={state.get('thread_id')}"
        )
        return {"target_agent": target, "status": "routed"}

    async def _process_node(self, state: AgentState) -> dict:
        """Process the message using legacy generation handlers or the Supervisor."""
        target = state.get("target_agent", "analyzer")
        payload = state.get("payload", {})
        event_type = state.get("event_type", "")
        language = state.get("language", "tr")
        operation_id = state.get("operation_id", state.get("message_id", ""))

        logger.info(
            f"[LangGraph:process] target={target} event_type={event_type} "
            f"thread_id={state.get('thread_id')} supervisor={'yes' if self._supervisor else 'no'}"
        )

        try:
            if target == "generation":
                cached_generation = await self._get_stage_cache(operation_id, "generation.result")
                if cached_generation is not None:
                    return {"generation_result": cached_generation, "status": "completed"}

                result = await self._handle_generation(payload, event_type, language)
                await self._set_stage_cache(operation_id, "generation.result", result)
                return {"generation_result": result, "status": "completed"}

            if self._supervisor:
                if target == "chat":
                    cached_chat = await self._get_stage_cache(operation_id, "chat.result")
                    if cached_chat is not None:
                        return {"chat_response": cached_chat, "status": "completed"}
                if target == "analyzer":
                    cached_analysis = await self._get_stage_cache(operation_id, "analysis.full")
                    if cached_analysis is not None:
                        return {"analysis_result": cached_analysis, "status": "completed"}

                result = await self._supervisor.run(event_type, payload, language)

                if not result and target == "analyzer":
                    logger.warning(
                        "[LangGraph:process] Supervisor failed for analyzer, "
                        "falling back to legacy _handle_analysis"
                    )
                    result = await self._handle_analysis(payload, language, operation_id)
                    if result:
                        await self._set_stage_cache(operation_id, "analysis.full", result)
                        return {"analysis_result": result, "status": "completed"}

                if not result:
                    return {"status": "failed", "error": "supervisor returned empty"}

                if target == "chat":
                    # Erken cache yazma: supervisor sonuç üretir üretmez yaz
                    # Timeout olsa bile sonraki denemede cached sonuç dönecek
                    await self._set_stage_cache(operation_id, "chat.result", result)
                    return {"chat_response": result, "status": "completed"}
                if target == "analyzer":
                    await self._set_stage_cache(operation_id, "analysis.full", result)
                    return {"analysis_result": result, "status": "completed"}
                return {"generation_result": result, "status": "completed"}

            if target == "chat":
                cached_chat = await self._get_stage_cache(operation_id, "chat.result")
                if cached_chat is not None:
                    return {"chat_response": cached_chat, "status": "completed"}

                result = await self._handle_chat(payload, language)
                await self._set_stage_cache(operation_id, "chat.result", result)
                return {"chat_response": result, "status": "completed"}

            if target == "analyzer":
                cached_analysis = await self._get_stage_cache(operation_id, "analysis.full")
                if cached_analysis is not None:
                    return {"analysis_result": cached_analysis, "status": "completed"}

                result = await self._handle_analysis(payload, language, operation_id)
                await self._set_stage_cache(operation_id, "analysis.full", result)
                return {"analysis_result": result, "status": "completed"}

            logger.warning(f"[LangGraph:process] Unknown target: {target}")
            return {"status": "failed", "error": f"Unknown target agent: {target}"}

        except Exception as e:
            error_text = str(e).strip() or type(e).__name__
            logger.exception(f"[LangGraph:process] Error: {error_text}")
            status = "retryable_failed" if self._is_retryable_error_text(error_text) else "failed"
            return {"status": status, "error": error_text}

    async def _respond_node(self, state: AgentState) -> dict:
        """Build the outbound result envelope without publishing it yet."""
        status = state.get("status", "")
        if status in {"failed", "retryable_failed"}:
            logger.error(
                f"[LangGraph:respond] Skipping publish because processing failed: "
                f"{state.get('error')}"
            )
            return state

        correlation_id = state.get("correlation_id", str(uuid.uuid4()))
        operation_id = state.get("operation_id", state.get("message_id", str(uuid.uuid4())))
        causation_id = state.get("message_id", "")
        event_type = state.get("event_type", "")
        payload = state.get("payload", {})

        try:
            if state.get("chat_response"):
                session_id = payload.get("sessionId", "")
                routing_key, outbound_message = self._build_chat_result_message(
                    session_id,
                    state["chat_response"],
                    correlation_id,
                    operation_id,
                    causation_id,
                )
            elif state.get("analysis_result"):
                article_id = payload.get("articleId", "")
                routing_key, outbound_message = self._build_analysis_result_message(
                    article_id,
                    state["analysis_result"],
                    correlation_id,
                    operation_id,
                    causation_id,
                )
            elif state.get("generation_result"):
                entity_id = state.get("message_id", "")
                routing_key, outbound_message = self._build_ai_result_message(
                    entity_id,
                    state["generation_result"],
                    event_type,
                    correlation_id,
                    operation_id,
                    causation_id,
                )
            else:
                return {"status": "failed", "error": "missing outbound payload"}

            logger.info(f"[LangGraph:respond] Prepared outbound result for {event_type}")
            return {
                "status": "ready_to_publish",
                "outbound_routing_key": routing_key,
                "outbound_message": outbound_message,
            }

        except Exception as e:
            logger.exception(f"[LangGraph:respond] Response preparation error: {e}")
            return {"status": "failed", "error": f"publish_error: {e}"}

    # ─── Backward-compat processing helpers ─────────────────────────────────────

    async def _handle_chat(self, payload: dict, language: str) -> dict:
        """Handle chat messages using existing ChatService."""
        from app.domain.entities.chat import ChatMessage as CM

        post_id = payload.get("postId", "")
        user_message = payload.get("userMessage", "")
        session_id = payload.get("sessionId", "")
        article_title = payload.get("articleTitle", "")
        article_content = payload.get("articleContent", "")
        enable_web_search = bool(payload.get("enableWebSearch", False))
        auth_context = AuthorizationContext.from_payload(payload.get("authContext") or payload.get("auth_context"))
        history_raw = payload.get("conversationHistory", [])

        await self._authorize_chat_post_access(post_id, auth_context)

        # ─── Jailbreak detection on user chat input ─────────────────────────────
        try:
            jb = await _jailbreak_detector.detect(user_message)
            if jb.is_jailbreak:
                logger.warning(
                    f"[LangGraph:chat] Jailbreak BLOCKED: type={jb.jailbreak_type}, "
                    f"confidence={jb.confidence:.2f}, session={session_id}"
                )
                _audit.log_event(
                    event_type="prompt_injection_blocked",
                    user_id=session_id,
                    resource_id=post_id,
                    action="chat_jailbreak_blocked",
                    success=False,
                    details={
                        "jailbreak_type": str(jb.jailbreak_type),
                        "confidence": jb.confidence,
                    },
                )
                try:
                    await _incident_tracker.create_incident(
                        title=f"Jailbreak attempt blocked ({jb.jailbreak_type})",
                        description=(
                            f"session={session_id}, post={post_id}, "
                            f"type={jb.jailbreak_type}, confidence={jb.confidence:.2f}"
                        ),
                        severity=IncidentSeverity.MEDIUM,
                        indicators={
                            "jailbreak_type": str(jb.jailbreak_type),
                            "confidence": jb.confidence,
                            "session_id": session_id,
                            "post_id": post_id,
                        },
                    )
                except Exception:
                    logger.debug("[LangGraph:chat] Incident tracking failed", exc_info=True)
                return {
                    "response": "Bu istek güvenlik politikalarına aykırı olduğu için işlenemedi.",
                    "isWebSearchResult": False,
                    "sources": None,
                }
        except Exception as e:
            logger.warning(f"[LangGraph:chat] Jailbreak detection error (non-fatal): {e}")

        normalized_message = self._normalize_intent_text(user_message)
        summary_patterns = [
            r"^(bu\s+)?makaleyi\s+ozetle",
            r"^makalenin\s+ozet",
            r"^bu\s+makalenin\s+ozeti",
            r"^summarize\s+(the\s+)?article",
            r"^article\s+summary",
        ]
        if any(re.search(pattern, normalized_message) for pattern in summary_patterns):
            summary = await self._analysis.summarize_article(
                content=article_content, max_sentences=5, language=language
            )
            return {"response": summary, "isWebSearchResult": False, "sources": None}

        if not enable_web_search and self._has_web_search_intent(user_message):
            enable_web_search = True
            logger.info("[LangGraph:chat] Web-search intent detected from message, enabling hybrid path")

        if enable_web_search:
            resp = await self._chat.chat_with_web_search(
                post_id=post_id,
                user_message=user_message,
                article_title=article_title,
                article_content=article_content,
                language=language,
                auth_context=auth_context,
            )
            return {
                "response": resp.response,
                "isWebSearchResult": bool(resp.sources),
                "sources": resp.sources,
            }

        history = [CM(role=h.get("role", "user"), content=h.get("content", "")) for h in history_raw]

        resp = await self._chat.chat(
            post_id=post_id,
            user_message=user_message,
            conversation_history=history,
            language=language,
            auth_context=auth_context,
        )
        return {"response": resp.response, "isWebSearchResult": False, "sources": None}

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
        # Additional UTF-8 normalization for common Turkish char mojibake
        replacements = {
            "Ä±": "i",
            "ÄŸ": "g",
            "Ã¼": "u",
            "ÅŸ": "s",
            "Ã¶": "o",
            "Ã§": "c",
        }
        for bad, good in replacements.items():
            normalized = normalized.replace(bad, good)
        return re.sub(r"\s+", " ", normalized)

    def _has_web_search_intent(cls, message: str) -> bool:
        """Detect explicit web-search request from user text."""
        normalized = cls._normalize_intent_text(message)
        if not normalized:
            return False
        return any(re.search(pattern, normalized) for pattern in WEB_SEARCH_INTENT_PATTERNS)

    @staticmethod
    def _classify_retryable_reason(error_text: str) -> str:
        """Map transient error text to broker retry reason."""
        normalized = (error_text or "").strip().lower()
        if not normalized:
            return "transient:unknown_error"
        if "timeout" in normalized or "timed out" in normalized:
            return "transient:timeout"
        if any(marker in normalized for marker in ("connection", "connect", "refused", "dns", "socket", "network")):
            return "transient:connection_error"
        if any(marker in normalized for marker in ("rate limit", "rate_limit", "too many requests", "429")):
            return "transient:rate_limited"
        if "circuit" in normalized:
            return "transient:circuit_open"
        return "transient:unknown_error"

    @classmethod
    def _is_retryable_error_text(cls, error_text: str) -> bool:
        """Return True when failure should be retried instead of poisoned."""
        reason = cls._classify_retryable_reason(error_text)
        if reason != "transient:unknown_error":
            return True
        normalized = (error_text or "").strip().lower()
        extra_markers = (
            "temporarily unavailable",
            "service unavailable",
            "embedding request failed",
            "all connection attempts failed",
        )
        return any(marker in normalized for marker in extra_markers)

    @staticmethod
    def _stage_cache_key(operation_id: str, stage: str) -> str:
        return f"idempotency:stage:{OPERATION_CONSUMER_NAME}:{operation_id}:{stage}"

    async def _get_stage_cache(self, operation_id: str, stage: str) -> dict[str, Any] | None:
        if not operation_id:
            return None

        cached = await self._cache.get_json(self._stage_cache_key(operation_id, stage))
        if cached is None:
            record_stage_cache(stage, "miss")
            return None

        record_stage_cache(stage, "hit")
        logger.info("[LangGraph] Stage cache hit for operation=%s stage=%s", operation_id, stage)
        return cached

    async def _set_stage_cache(self, operation_id: str, stage: str, value: dict[str, Any]) -> None:
        if not operation_id:
            return

        await self._cache.set_json(
            self._stage_cache_key(operation_id, stage),
            value,
            ttl_seconds=settings.worker_stage_cache_ttl_seconds,
        )
        record_stage_cache(stage, "store")

    async def _handle_analysis(self, payload: dict, language: str, operation_id: str) -> dict:
        """Handle article analysis using existing AnalysisService."""
        content = payload.get("content", "")
        article_id = payload.get("articleId", "")
        region = payload.get("targetRegion", "TR")

        cached_indexing = await self._get_stage_cache(operation_id, "analysis.indexing")
        if cached_indexing is None:
            await self._indexing.index_article(
                post_id=article_id,
                title=payload.get("title", ""),
                content=content,
                author_id=payload.get("authorId"),
                visibility=payload.get("visibility", "published"),
            )
            await self._set_stage_cache(
                operation_id,
                "analysis.indexing",
                {"indexed": True, "postId": article_id},
            )

        analysis = await self._analysis.full_analysis(
            content=content, target_region=region, language=language
        )

        return {
            "postId": article_id,
            "summary": analysis.summary,
            "keywords": analysis.keywords,
            "seoDescription": analysis.seo_description,
            "readingTime": analysis.reading_time.reading_time_minutes,
            "sentiment": analysis.sentiment.sentiment,
            "geoOptimization": (
                analysis.geo_optimization.model_dump()
                if analysis.geo_optimization
                else None
            ),
        }

    async def _handle_generation(
        self, payload: dict, event_type: str, language: str
    ) -> dict:
        """Handle AI generation requests using existing services."""
        content = payload.get("content", "") or payload.get("query", "")

        if event_type == "title":
            summary = await self._analysis.summarize_article(content, 1, language)
            return {"title": summary}
        if event_type == "excerpt":
            summary = await self._analysis.summarize_article(content, 3, language)
            return {"excerpt": summary}
        if event_type == "tags":
            keywords = await self._analysis.extract_keywords(content, 5, language)
            return {"tags": keywords}
        if event_type == "seo":
            desc = await self._analysis._generate_seo_description(content, language)
            return {"description": desc}
        if event_type == "content":
            summary = await self._analysis.summarize_article(content, 3, language)
            return {"improvedContent": summary}
        if event_type == "summarize":
            max_sentences = payload.get("maxSentences", 5)
            summary = await self._analysis.summarize_article(content, max_sentences, language)
            return {"summary": summary}
        if event_type == "keywords":
            max_keywords = payload.get("maxKeywords", 10)
            keywords = await self._analysis.extract_keywords(content, max_keywords, language)
            return {"keywords": keywords}
        if event_type == "sentiment":
            sentiment = await self._analysis.analyze_sentiment(content, language)
            return {
                "sentiment": sentiment.sentiment,
                "confidence": sentiment.confidence,
            }
        if event_type == "reading-time":
            reading_time = self._analysis.calculate_reading_time(content)
            return {
                "readingTimeMinutes": reading_time.reading_time_minutes,
                "wordCount": reading_time.word_count,
            }
        if event_type == "geo-optimize":
            target_region = payload.get("targetRegion", "TR")
            if self._analysis._seo_service:
                geo_opt = await self._analysis._seo_service.optimize_for_geo(content, target_region, language)
                return {"geoOptimization": geo_opt.model_dump() if geo_opt else None}
            return {"geoOptimization": None}
        if event_type == "collect-sources":
            max_sources = payload.get("maxSources", 5)
            query = content
            sources = await self._collect_web_sources(query, max_sources)
            return {"sources": sources}
        raise ValueError(f"Unknown generation type: {event_type}")

    async def _collect_web_sources(self, query: str, max_sources: int) -> list[dict[str, Any]]:
        if hasattr(self._chat, "_web_search") and self._chat._web_search:
            try:
                results = await self._chat._web_search.search(query, max_results=max_sources)
                return [
                    {
                        "title": result.title,
                        "url": result.url,
                        "snippet": result.snippet,
                    }
                    for result in results[:max_sources]
                ]
            except Exception as e:
                logger.warning(f"[LangGraph] Web source collection failed: {e}")
        return []

    @staticmethod
    def _create_message_envelope(
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str,
        operation_id: str,
        causation_id: str,
    ) -> dict[str, Any]:
        return {
            "messageId": str(uuid.uuid4()),
            "operationId": operation_id,
            "correlationId": correlation_id,
            "causationId": causation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "eventType": event_type,
            "payload": payload,
        }

    def _build_analysis_result_message(
        self,
        article_id: str,
        result: dict[str, Any],
        correlation_id: str,
        operation_id: str,
        causation_id: str,
    ) -> tuple[str, dict[str, Any]]:
        message = self._create_message_envelope(
            event_type="ai.analysis.completed",
            correlation_id=correlation_id,
            operation_id=operation_id,
            causation_id=causation_id,
            payload=result,
        )
        return AI_ANALYSIS_COMPLETED, message

    def _build_chat_result_message(
        self,
        session_id: str,
        result: dict[str, Any],
        correlation_id: str,
        operation_id: str,
        causation_id: str,
    ) -> tuple[str, dict[str, Any]]:
        message = self._create_message_envelope(
            event_type="chat.message.completed",
            correlation_id=correlation_id,
            operation_id=operation_id,
            causation_id=causation_id,
            payload={
                "sessionId": session_id,
                "response": result.get("response", ""),
                "isWebSearchResult": result.get("isWebSearchResult", False),
                "sources": result.get("sources"),
            },
        )
        return CHAT_RESPONSE_KEY, message

    def _build_ai_result_message(
        self,
        request_id: str,
        result: dict[str, Any],
        msg_type: str,
        correlation_id: str,
        operation_id: str,
        causation_id: str,
    ) -> tuple[str, dict[str, Any]]:
        event_types = {
            "title": "ai.title.generation.completed",
            "excerpt": "ai.excerpt.generation.completed",
            "tags": "ai.tags.generation.completed",
            "seo": "ai.seo.generation.completed",
            "content": "ai.content.improvement.completed",
            "summarize": "ai.summarize.completed",
            "keywords": "ai.keywords.completed",
            "sentiment": "ai.sentiment.completed",
            "reading-time": "ai.reading-time.completed",
            "geo-optimize": "ai.geo-optimize.completed",
            "collect-sources": "ai.collect-sources.completed",
        }
        event_type = event_types.get(msg_type, f"ai.{msg_type}.completed")
        message = self._create_message_envelope(
            event_type=event_type,
            correlation_id=correlation_id,
            operation_id=operation_id,
            causation_id=causation_id,
            payload={"requestId": request_id, **result},
        )
        return event_type, message

    async def _store_and_publish_response(
        self,
        operation_id: str,
        routing_key: str,
        response_message: dict[str, Any],
        correlation_id: str,
    ) -> None:
        await self._cache.store_operation_response(
            OPERATION_CONSUMER_NAME,
            operation_id,
            response_message,
            routing_key,
        )
        published = await self._broker.publish(routing_key, response_message, correlation_id)
        if not published:
            raise RuntimeError(f"publish_failed:{routing_key}")
        await self._cache.mark_operation_completed(OPERATION_CONSUMER_NAME, operation_id)

    async def _republish_stored_response(
        self,
        operation_id: str,
        claim: dict[str, Any],
        correlation_id: str,
        transport_message_id: str,
    ) -> bool:
        response_payload = claim.get("response_payload")
        routing_key = claim.get("response_routing_key")
        if not response_payload or not routing_key:
            return False
        published = await self._broker.publish(routing_key, response_payload, correlation_id)
        if not published:
            raise RuntimeError(f"republish_failed:{routing_key}")
        record_idempotency_replay("stored_response")
        await self._cache.mark_operation_completed(OPERATION_CONSUMER_NAME, operation_id)
        if transport_message_id:
            await self._cache.mark_processed(transport_message_id, settings.worker_operation_retention_seconds)
        return True

    async def process_message(self, body: bytes, source_queue: str = "") -> tuple[bool, str]:
        """Entry point called by the RabbitMQ consumer.

        Args:
            body: Raw message bytes.
            source_queue: Source queue name (for future per-queue metrics/logging).
        """
        import time as _time
        from app.services.idle_shutdown_service import record_idle_activity_sync

        # Mark activity to prevent idle timeout during message processing
        record_idle_activity_sync()

        started_at = _time.perf_counter()
        operation_id = ""
        correlation_id = ""
        message_id = ""
        entity_id = ""
        claim_state = ""
        lock_lease = None

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.error(f"[LangGraph] Invalid JSON: {e}")
            return False, "malformed:json"

        try:
            event_type_raw = data.get("eventType", "")
            message_id = data.get("messageId", str(uuid.uuid4()))
            operation_id = data.get("operationId") or message_id
            correlation_id = data.get("correlationId") or operation_id
            payload = data.get("payload", {})
            msg_type = self._classify_event(event_type_raw)
            language = payload.get("language", "tr")
            article_id = payload.get("articleId", "") or payload.get("ArticleId", "")
            entity_id = article_id or message_id

            claim = await self._cache.claim_operation(
                OPERATION_CONSUMER_NAME,
                operation_id,
                message_id,
                correlation_id,
                settings.worker_operation_timeout_seconds,
            )
            claim_state = claim.get("state", "claimed")

            if claim_state in {"duplicate_completed", "duplicate_failed"}:
                logger.info(
                    f"[LangGraph] Operation {operation_id} already finalized with state={claim_state}"
                )
                return True, "duplicate"

            if claim_state == "duplicate_processing":
                logger.info(f"[LangGraph] Operation {operation_id} is already processing")
                return False, "locked"

            if claim.get("response_payload") and claim.get("response_routing_key"):
                await self._republish_stored_response(operation_id, claim, correlation_id, message_id)
                logger.info(f"[LangGraph] Republished stored response for operation {operation_id}")
                return True, "success"

            # Timeout sonrası retry'da stage cache kontrolü
            # Chat target için erken sonuç kontrolü
            if msg_type == "chat":
                cached_chat = await self._get_stage_cache(operation_id, "chat.result")
                if cached_chat is not None:
                    logger.info(f"[LangGraph] Returning cached chat result for operation {operation_id}")
                    # Build response manually for cached result
                    session_id = payload.get("sessionId", "")
                    routing_key, outbound_message = self._build_chat_result_message(
                        session_id,
                        cached_chat,
                        correlation_id,
                        operation_id,
                        message_id,
                    )
                    await self._store_and_publish_response(
                        operation_id,
                        routing_key,
                        outbound_message,
                        correlation_id,
                    )
                    return True, "success"

            # Analyzer target için timeout sonrası retry'da cache kontrolü
            if msg_type in ("article", "article_published"):
                cached_analysis = await self._get_stage_cache(operation_id, "analysis.full")
                if cached_analysis is not None:
                    logger.info(f"[LangGraph] Returning cached analysis result for operation {operation_id}")
                    article_id = payload.get("articleId", "")
                    routing_key, outbound_message = self._build_analysis_result_message(
                        article_id,
                        cached_analysis,
                        correlation_id,
                        operation_id,
                        message_id,
                    )
                    await self._store_and_publish_response(
                        operation_id,
                        routing_key,
                        outbound_message,
                        correlation_id,
                    )
                    return True, "success"

            # Generation target için timeout sonrası retry'da cache kontrolü
            if msg_type in ("title", "excerpt", "tags", "seo", "content", "summarize", "keywords", "sentiment", "reading-time", "geo-optimize", "collect-sources"):
                cached_generation = await self._get_stage_cache(operation_id, "generation.result")
                if cached_generation is not None:
                    logger.info(f"[LangGraph] Returning cached generation result for operation {operation_id}")
                    entity_id = payload.get("messageId", "")
                    routing_key, outbound_message = self._build_ai_result_message(
                        entity_id,
                        cached_generation,
                        msg_type,
                        correlation_id,
                        operation_id,
                        message_id,
                    )
                    await self._store_and_publish_response(
                        operation_id,
                        routing_key,
                        outbound_message,
                        correlation_id,
                    )
                    return True, "success"

            thread_id = f"lg-{operation_id}"
            initial_state: AgentState = {
                "thread_id": thread_id,
                "message_id": message_id,
                "operation_id": operation_id,
                "correlation_id": correlation_id,
                "event_type": msg_type,
                "payload": {**payload, "_operationId": operation_id},
                "content": payload.get("content", payload.get("articleContent", "")),
                "language": language,
                "target_agent": "",
                "analysis_result": None,
                "chat_response": None,
                "generation_result": None,
                "status": "pending",
                "error": None,
            }

            logger.info(
                f"[LangGraph] Starting workflow thread_id={thread_id} "
                f"event_type={msg_type} message_id={message_id} operationId={operation_id}"
            )

            try:
                lock_lease = await self._cache.acquire_lock(entity_id)
            except Exception as e:
                logger.warning(f"[LangGraph] Lock acquisition failed: {e}")
                lock_lease = None

            if not lock_lease:
                await self._cache.mark_operation_retryable(OPERATION_CONSUMER_NAME, operation_id, "entity_locked")
                return False, "locked"

            final_state = await asyncio.wait_for(
                self._graph.ainvoke(initial_state),
                timeout=settings.worker_operation_timeout_seconds,
            )
            status = final_state.get("status", "unknown")
            duration = _time.perf_counter() - started_at

            AgentLogger.log_node_execution(
                thread_id=thread_id,
                node="workflow_complete",
                duration_seconds=duration,
                state_keys=list(final_state.keys()),
                extra={"status": status, "event_type": msg_type},
            )

            if status == "retryable_failed":
                error_text = final_state.get("error") or "workflow_retryable_failure"
                await self._cache.mark_operation_retryable(OPERATION_CONSUMER_NAME, operation_id, error_text)
                _audit.log_event(
                    event_type="ai_analysis",
                    user_id=correlation_id,
                    resource_id=article_id or message_id,
                    action=f"{msg_type}_retryable_failed",
                    success=False,
                    details={"status": status, "error": error_text},
                )
                return False, self._classify_retryable_reason(error_text)

            if status != "ready_to_publish":
                error_text = final_state.get("error") or "workflow_did_not_prepare_response"
                await self._cache.mark_operation_failed(OPERATION_CONSUMER_NAME, operation_id, error_text)
                _audit.log_event(
                    event_type="ai_analysis",
                    user_id=correlation_id,
                    resource_id=article_id or message_id,
                    action=f"{msg_type}_failed",
                    success=False,
                    details={"status": status, "error": error_text},
                )
                return False, "non_recoverable:processing_failed"

            outbound_routing_key = final_state.get("outbound_routing_key")
            outbound_message = final_state.get("outbound_message")
            if not outbound_routing_key or not outbound_message:
                await self._cache.mark_operation_failed(OPERATION_CONSUMER_NAME, operation_id, "missing_outbound_message")
                return False, "non_recoverable:processing_failed"

            await self._store_and_publish_response(
                operation_id,
                outbound_routing_key,
                outbound_message,
                correlation_id,
            )
            await self._cache.mark_processed(message_id, settings.worker_operation_retention_seconds)

            _audit.log_event(
                event_type="ai_analysis",
                user_id=correlation_id,
                resource_id=article_id or message_id,
                action=f"{msg_type}_completed",
                success=True,
                details={"duration_s": round(duration, 2), "status": status},
            )
            return True, "success"

        except asyncio.TimeoutError:
            logger.error(
                f"[LangGraph] Workflow TIMEOUT for operation={operation_id} message_id={message_id}"
            )
            if operation_id:
                await self._cache.mark_operation_retryable(OPERATION_CONSUMER_NAME, operation_id, "timeout")
            return False, "transient:timeout"

        except Exception as e:
            logger.exception(f"[LangGraph] Workflow failed for operation={operation_id}: {e}")
            if operation_id:
                await self._cache.mark_operation_retryable(OPERATION_CONSUMER_NAME, operation_id, str(e))
            AgentLogger.log_node_execution(
                thread_id=f"lg-{operation_id or message_id}",
                node="workflow_error",
                duration_seconds=_time.perf_counter() - started_at,
                extra={"error": str(e)},
            )
            return False, "transient:unknown_error"

        finally:
            if lock_lease and entity_id:
                try:
                    await self._cache.release_lock(lock_lease)
                except Exception as e:
                    logger.warning(f"[LangGraph] Lock release failed: {e}")

    @staticmethod
    def _classify_event(event_type: str) -> str:
        """Classify raw eventType string to normalized message type."""
        et = event_type.lower()
        if et.startswith("chat.message.requested") or et == "chatrequestedevent":
            return "chat"
        if et.startswith("article.published") or et == "articlepublishedevent":
            return "article_published"
        if et.startswith("article.created") or et == "articlecreatedevent":
            return "article"
        if et.startswith("article.updated") or et == "articleupdatedevent":
            return "article"
        if et.startswith("ai.title"):
            return "title"
        if et.startswith("ai.excerpt"):
            return "excerpt"
        if et.startswith("ai.tags"):
            return "tags"
        if et.startswith("ai.seo"):
            return "seo"
        if et.startswith("ai.content"):
            return "content"
        if et.startswith("ai.summarize"):
            return "summarize"
        if et.startswith("ai.keywords"):
            return "keywords"
        if et.startswith("ai.sentiment"):
            return "sentiment"
        if et.startswith("ai.reading-time"):
            return "reading-time"
        if et.startswith("ai.geo-optimize"):
            return "geo-optimize"
        if et.startswith("ai.collect-sources"):
            return "collect-sources"
        return "article"
