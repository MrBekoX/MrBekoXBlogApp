"""Message processor service - Handles RabbitMQ message processing."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from pydantic import ValidationError

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
)
from app.services.analysis_service import AnalysisService
from app.services.indexing_service import IndexingService
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

# Routing keys
AI_ANALYSIS_COMPLETED = "ai.analysis.completed"
CHAT_RESPONSE_KEY = "chat.message.completed"


class MessageProcessorService:
    """
    Service for processing messages from the message broker.

    Implements idempotency pattern with distributed locking.
    """

    def __init__(
        self,
        cache: ICache,
        message_broker: IMessageBroker,
        analysis_service: AnalysisService,
        indexing_service: IndexingService,
        chat_service: ChatService
    ):
        self._cache = cache
        self._broker = message_broker
        self._analysis = analysis_service
        self._indexing = indexing_service
        self._chat = chat_service

    async def process_message(self, body: bytes) -> tuple[bool, str]:
        """
        Process a message with idempotency checks.

        Args:
            body: Raw message body

        Returns:
            Tuple of (success, reason)
        """
        # Parse message
        try:
            message, message_type = self._parse_message(body)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Invalid message format: {e}")
            return False, f"malformed: {e}"

        message_id = getattr(message, "messageId", "")
        entity_id = self._get_entity_id(message, message_type)

        logger.info(f"Processing {message_type} message {message_id}")

        # Check if already processed
        if await self._cache.is_processed(message_id):
            logger.info(f"Message {message_id} already processed")
            return True, "duplicate"

        # Acquire lock
        if not await self._cache.acquire_lock(entity_id):
            logger.info(f"Entity {entity_id} is locked")
            return False, "locked"

        try:
            # Process based on type
            correlation_id = getattr(message, "correlationId", None)

            if message_type == "chat":
                result = await self._process_chat(message)
                await self._publish_chat_result(
                    message.payload.sessionId, result, correlation_id
                )

            elif message_type in ("article", "article_published"):
                # Index for RAG
                await self._indexing.index_article(
                    post_id=message.payload.articleId,
                    title=message.payload.title,
                    content=message.payload.content
                )
                # Run analysis
                analysis = await self._process_article(message)
                await self._publish_analysis_result(
                    message.payload.articleId, analysis, correlation_id
                )

            else:
                result = await self._process_ai_request(message, message_type)
                await self._publish_ai_result(
                    entity_id, result, message_type, correlation_id
                )

            # Mark as processed
            await self._cache.mark_processed(message_id)
            logger.info(f"Successfully processed {message_type}")
            return True, "success"

        except Exception as e:
            logger.exception(f"Error processing {message_type}: {e}")
            return False, f"error: {e}"

        finally:
            try:
                await self._cache.release_lock(entity_id)
            except Exception as e:
                logger.error(f"Error releasing lock: {e}")

    def _parse_message(self, body: bytes) -> tuple[Any, str]:
        """Parse message body and determine type."""
        data = json.loads(body)
        event_type = data.get("eventType", "")
        logger.info(f"Parsing message with eventType: {event_type}")

        if event_type.startswith("chat.message.requested"):
            return ChatRequestMessage.model_validate(data), "chat"
        elif event_type.startswith("article.published"):
            return ArticleMessage.model_validate(data), "article_published"
        elif event_type.startswith("ai.title"):
            return AiTitleGenerationMessage.model_validate(data), "title"
        elif event_type.startswith("ai.excerpt"):
            return AiExcerptGenerationMessage.model_validate(data), "excerpt"
        elif event_type.startswith("ai.tags"):
            return AiTagsGenerationMessage.model_validate(data), "tags"
        elif event_type.startswith("ai.seo"):
            return AiSeoDescriptionGenerationMessage.model_validate(data), "seo"
        elif event_type.startswith("ai.content"):
            return AiContentImprovementMessage.model_validate(data), "content"
        else:
            return ArticleMessage.model_validate(data), "article"

    def _get_entity_id(self, message: Any, message_type: str) -> str:
        """Get entity ID for locking."""
        if message_type in ("article", "article_published"):
            return message.payload.articleId
        return message.messageId

    async def _process_article(self, message: ArticleMessage) -> ProcessingResult:
        """Process article with full analysis."""
        payload = message.payload
        language = payload.language or "tr"
        region = payload.targetRegion or "TR"

        analysis = await self._analysis.full_analysis(
            content=payload.content,
            target_region=region,
            language=language
        )

        return ProcessingResult(
            article_id=payload.articleId,
            summary=analysis.summary,
            keywords=analysis.keywords,
            seo_description=analysis.seo_description,
            reading_time_minutes=analysis.reading_time.reading_time_minutes,
            word_count=analysis.reading_time.word_count,
            sentiment=analysis.sentiment.sentiment,
            sentiment_confidence=analysis.sentiment.confidence,
            geo_optimization=analysis.geo_optimization.model_dump() if analysis.geo_optimization else None,
            processed_at=datetime.utcnow().isoformat()
        )

    async def _process_chat(self, message: ChatRequestMessage) -> dict:
        """Process chat message."""
        payload = message.payload
        logger.info(f"Processing chat: postId={payload.postId}, sessionId={payload.sessionId}")

        # Special case: Summary request triggers
        summary_triggers = [
            "bu makalenin özetini oluştur",
            "makalenin özetini oluştur",
            "make a summary of this article",
            "summarize this article"
        ]

        user_message_lower = payload.userMessage.strip().lower()
        is_summary_request = any(trigger in user_message_lower for trigger in summary_triggers)

        if is_summary_request:
            logger.info("Summary request detected, generating AI summary")
            summary = await self._analysis.summarize_article(
                content=payload.articleContent,
                max_sentences=5,
                language=payload.language
            )
            return {
                "response": summary,
                "isWebSearchResult": False,
                "sources": None
            }

        if payload.enableWebSearch:
            response = await self._chat.chat_with_web_search(
                post_id=payload.postId,
                user_message=payload.userMessage,
                article_title=payload.articleTitle,
                article_content=payload.articleContent,
                language=payload.language
            )
            return {
                "response": response.response,
                "isWebSearchResult": True,
                "sources": response.sources
            }

        history = [
            ChatMessage(role=h.role, content=h.content)
            for h in payload.conversationHistory
        ]

        response = await self._chat.chat(
            post_id=payload.postId,
            user_message=payload.userMessage,
            conversation_history=history,
            language=payload.language
        )

        return {
            "response": response.response,
            "isWebSearchResult": False,
            "sources": None
        }

    async def _process_ai_request(self, message: Any, msg_type: str) -> dict:
        """Process AI generation request."""
        payload = message.payload
        content = payload.content
        language = payload.language or "tr"

        if msg_type == "title":
            # Title generation would need separate method
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
            "timestamp": datetime.utcnow().isoformat(),
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
        correlation_id: str | None
    ) -> bool:
        """Publish chat response."""
        message = {
            "messageId": str(uuid.uuid4()),
            "correlationId": correlation_id or str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "eventType": "chat.message.completed",
            "payload": {
                "sessionId": session_id,
                "response": result.get("response", ""),
                "isWebSearchResult": result.get("isWebSearchResult", False),
                "sources": result.get("sources")
            }
        }
        return await self._broker.publish(CHAT_RESPONSE_KEY, message, correlation_id)

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
        }
        event_type = event_types.get(msg_type, f"ai.{msg_type}.completed")

        message = {
            "messageId": str(uuid.uuid4()),
            "correlationId": correlation_id or str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "eventType": event_type,
            "payload": {"requestId": request_id, **result}
        }
        return await self._broker.publish(event_type, message, correlation_id)
