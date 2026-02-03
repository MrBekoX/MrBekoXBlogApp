"""Message processor with idempotency pattern"""

import json
import logging
import re
import uuid
from enum import Enum
from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, ValidationError, Field, field_validator
import aio_pika
import httpx
import asyncio

from app.core.config import settings
from app.core.cache import cache
from app.agent.simple_blog_agent import simple_blog_agent
from app.agent.indexer import article_indexer
from app.agent.rag_chat_handler import rag_chat_handler, ChatMessage
from app.rag.retriever import retriever
from app.tools.web_search import web_search_tool

logger = logging.getLogger(__name__)

# RabbitMQ Constants
EXCHANGE_NAME = "blog.events"
AI_ANALYSIS_COMPLETED_ROUTING_KEY = "ai.analysis.completed"
CHAT_RESPONSE_ROUTING_KEY = "chat.message.completed"

# Validation patterns
GUID_PATTERN = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

# Maximum content length (100KB)
MAX_CONTENT_LENGTH = 100_000


class TargetRegion(str, Enum):
    """Supported target regions for GEO optimization."""
    TR = "TR"
    US = "US"
    GB = "GB"
    DE = "DE"
    FR = "FR"
    ES = "ES"
    IT = "IT"
    NL = "NL"
    JP = "JP"
    KR = "KR"
    CN = "CN"
    IN = "IN"
    BR = "BR"
    AU = "AU"
    CA = "CA"


class SupportedLanguage(str, Enum):
    """Supported content languages."""
    TR = "tr"
    EN = "en"
    DE = "de"
    FR = "fr"
    ES = "es"


class AiTitleGenerationPayload(BaseModel):
    """Payload for AI title generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: Optional[str] = Field(default="tr", description="Content language")

    @field_validator('userId')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate userId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower


class AiExcerptGenerationPayload(BaseModel):
    """Payload for AI excerpt generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: Optional[str] = Field(default="tr", description="Content language")

    @field_validator('userId')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate userId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower


class AiTagsGenerationPayload(BaseModel):
    """Payload for AI tags generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: Optional[str] = Field(default="tr", description="Content language")

    @field_validator('userId')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate userId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower


class AiSeoDescriptionGenerationPayload(BaseModel):
    """Payload for AI SEO description generation requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: Optional[str] = Field(default="tr", description="Content language")

    @field_validator('userId')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate userId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower


class AiContentImprovementPayload(BaseModel):
    """Payload for AI content improvement requests."""

    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    userId: str = Field(..., description="User GUID")
    requestedAt: str
    language: Optional[str] = Field(default="tr", description="Content language")

    @field_validator('userId')
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        """Validate userId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower


class ArticlePayload(BaseModel):
    """Article payload from message with validation."""

    articleId: str = Field(..., description="Article GUID")
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=10, max_length=MAX_CONTENT_LENGTH)
    authorId: Optional[str] = None
    language: Optional[str] = Field(default="tr", description="Content language")
    targetRegion: Optional[str] = Field(default="TR", description="Target region for GEO")

    @field_validator('articleId')
    @classmethod
    def validate_article_id(cls, v: str) -> str:
        """Validate articleId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('authorId')
    @classmethod
    def validate_author_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate authorId is a valid GUID format if provided."""
        if v is not None and not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format for authorId: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: Optional[str]) -> str:
        """Validate and normalize language code."""
        if v is None:
            return "tr"
        v_lower = v.lower()
        # Accept common language codes
        valid_languages = {"tr", "en", "de", "fr", "es", "it", "nl", "ja", "ko", "zh", "pt"}
        if v_lower not in valid_languages:
            logger.warning(f"Unknown language '{v}', defaulting to 'tr'")
            return "tr"
        return v_lower

    @field_validator('targetRegion')
    @classmethod
    def validate_target_region(cls, v: Optional[str]) -> str:
        """Validate and normalize target region."""
        if v is None:
            return "TR"
        v_upper = v.upper()
        # Accept common region codes
        valid_regions = {"TR", "US", "GB", "DE", "FR", "ES", "IT", "NL", "JP", "KR", "CN", "IN", "BR", "AU", "CA"}
        if v_upper not in valid_regions:
            logger.warning(f"Unknown region '{v}', defaulting to 'TR'")
            return "TR"
        return v_upper


class ArticleMessage(BaseModel):
    """Message structure for article events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: ArticlePayload


class AiTitleGenerationMessage(BaseModel):
    """Message structure for AI title generation events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: AiTitleGenerationPayload


class AiExcerptGenerationMessage(BaseModel):
    """Message structure for AI excerpt generation events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: AiExcerptGenerationPayload


class AiTagsGenerationMessage(BaseModel):
    """Message structure for AI tags generation events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: AiTagsGenerationPayload


class AiSeoDescriptionGenerationMessage(BaseModel):
    """Message structure for AI SEO description generation events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: AiSeoDescriptionGenerationPayload


class AiContentImprovementMessage(BaseModel):
    """Message structure for AI content improvement events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: AiContentImprovementPayload


class ProcessingResult(BaseModel):
    """Result of article processing."""

    article_id: str
    summary: str
    keywords: list[str]
    seo_description: str
    reading_time_minutes: float
    word_count: int
    sentiment: str
    sentiment_confidence: int
    geo_optimization: Optional[dict[str, Any]] = None
    processed_at: str


# Chat Message Models
class ChatHistoryItem(BaseModel):
    """A single chat history item."""
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class ChatRequestPayload(BaseModel):
    """Payload for chat message requests."""

    sessionId: str = Field(..., min_length=1)
    postId: str = Field(..., description="Post GUID")
    articleTitle: str = Field(default="", max_length=500)
    articleContent: str = Field(default="", max_length=MAX_CONTENT_LENGTH)
    userMessage: str = Field(..., min_length=1, max_length=2000)
    conversationHistory: list[ChatHistoryItem] = Field(default_factory=list)
    language: str = Field(default="tr")
    enableWebSearch: bool = Field(default=False)

    @field_validator('postId')
    @classmethod
    def validate_post_id(cls, v: str) -> str:
        """Validate postId is a valid GUID format."""
        if not GUID_PATTERN.match(v):
            raise ValueError(f'Invalid GUID format: {v}')
        return v

    @field_validator('language')
    @classmethod
    def validate_language(cls, v: str) -> str:
        """Validate and normalize language code."""
        v_lower = v.lower()
        valid_languages = {"tr", "en", "de", "fr", "es"}
        if v_lower not in valid_languages:
            return "tr"
        return v_lower


class ChatRequestMessage(BaseModel):
    """Message structure for chat request events."""

    messageId: str
    correlationId: Optional[str] = None
    timestamp: str
    eventType: str
    payload: ChatRequestPayload


class MessageProcessor:
    """
    Process article messages with idempotency (RAG-free).

    Implements the Redis-based idempotency pattern:
    1. Check if message was already processed
    2. Acquire distributed lock for article
    3. Process article with Simple Blog Agent
    4. Publish results to RabbitMQ (event-driven)
    5. Mark message as processed
    6. Release lock
    """

    def __init__(self):
        self._connection: Optional[aio_pika.RobustConnection] = None
        self._channel: Optional[aio_pika.Channel] = None
        self._exchange: Optional[aio_pika.Exchange] = None

    async def initialize(self) -> None:
        """Initialize RabbitMQ connection and Simple Blog Agent."""
        # Initialize RabbitMQ connection for publishing results
        self._connection = await aio_pika.connect_robust(
            settings.rabbitmq_url,
            client_properties={"connection_name": "ai-agent-publisher"},
        )
        self._channel = await self._connection.channel()

        # Declare exchange (idempotent)
        self._exchange = await self._channel.declare_exchange(
            EXCHANGE_NAME,
            aio_pika.ExchangeType.DIRECT,
            durable=True,
        )

        # Initialize Simple Blog Agent
        simple_blog_agent.initialize()
        logger.info("Message processor initialized with RabbitMQ publisher")

    async def shutdown(self) -> None:
        """Close RabbitMQ connection."""
        if self._channel:
            await self._channel.close()
            self._channel = None
        if self._connection:
            await self._connection.close()
            self._connection = None
        self._exchange = None
        logger.info("Message processor shutdown complete")

    def parse_message(self, body: bytes) -> tuple[Any, str]:
        """
        Parse and validate message body.

        Args:
            body: Raw message body

        Returns:
            Tuple of (parsed_message, message_type)

        Raises:
            ValidationError: If message format is invalid
            json.JSONDecodeError: If body is not valid JSON
        """
        data = json.loads(body)
        event_type = data.get("eventType", "")

        # Route to appropriate message type based on eventType
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
            return AiContentImprovementMessage.model_validate(data), "content_improvement"
        else:
            # Default to article message
            return ArticleMessage.model_validate(data), "article"

    async def process_message(self, body: bytes) -> tuple[bool, str]:
        """
        Process a message with idempotency checks.

        Args:
            body: Raw message body

        Returns:
            Tuple of (success: bool, reason: str)
        """
        # Parse message
        try:
            message, message_type = self.parse_message(body)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Invalid message format: {e}")
            return False, f"malformed: {e}"

        message_id = getattr(message, "messageId", "")
        
        # Get ID based on message type
        if message_type == "article":
            entity_id = message.payload.articleId
        else:
            # For AI generation requests, use messageId as the lock key
            entity_id = message_id

        logger.info(f"Processing {message_type} message {message_id} for entity {entity_id}")

        # Step 1: Check if already processed
        if await cache.is_processed(message_id):
            logger.info(f"Message {message_id} already processed, skipping")
            return True, "duplicate"

        # Step 2: Try to acquire lock
        if not await cache.acquire_lock(entity_id):
            logger.info(f"Entity {entity_id} is locked, requeue")
            return False, "locked"

        try:
            # Step 3: Process message based on type
            if message_type == "chat":
                result = await self._process_chat(message)
                correlation_id = message.correlationId
                published = await self._save_chat_result(
                    message.payload.sessionId,
                    result,
                    correlation_id
                )
            elif message_type == "article_published":
                # Index article for RAG (async, fire-and-forget style for indexing)
                result = await self._index_article(message)
                # Also run full analysis
                analysis_result = await self._process_article(message)
                correlation_id = message.correlationId
                published = await self._save_article_result(entity_id, analysis_result, correlation_id)
            elif message_type == "article":
                # Also index article for RAG when processing analysis requests
                await self._index_article(message)
                result = await self._process_article(message)
                # Step 4: Publish result to RabbitMQ (event-driven)
                correlation_id = message.correlationId
                published = await self._save_article_result(entity_id, result, correlation_id)
            else:
                result = await self._process_ai_request(message, message_type)
                # Step 4: Publish AI result to RabbitMQ
                correlation_id = message.correlationId
                published = await self._save_ai_result(entity_id, result, message_type, correlation_id)

            if not published:
                logger.warning(f"Failed to publish result for {message_type} {entity_id}")

            # Step 5: Mark as processed
            await cache.mark_processed(message_id)

            logger.info(f"Successfully processed {message_type} for entity {entity_id}")
            return True, "success"

        except httpx.HTTPStatusError as e:
            # HTTP errors that cannot be fixed by retrying
            if e.response.status_code in (400, 401, 403, 404):
                logger.error(f"Non-recoverable HTTP error for {message_type} {entity_id}: {e}")
                return False, f"non_recoverable: HTTP {e.response.status_code} - {e}"
            # Other HTTP errors might be transient (5xx)
            logger.exception(f"HTTP error processing {message_type} {entity_id}: {e}")
            return False, f"error: {e}"
        except Exception as e:
            logger.exception(f"Error processing {message_type} {entity_id}: {e}")
            return False, f"error: {e}"

        finally:
            # Step 6: Always release lock with proper error handling
            try:
                await cache.release_lock(entity_id)
            except Exception as e:
                logger.error(f"Error releasing lock for entity {entity_id}: {e}")

    async def _process_article(self, message: ArticleMessage) -> ProcessingResult:
        """
        Process article using Simple Blog Agent (RAG-free).

        Args:
            message: Article message

        Returns:
            Processing result
        """
        payload = message.payload

        # Get language and region from payload
        language = payload.language or "tr"
        target_region = payload.targetRegion or "TR"

        logger.info(f"Processing article {payload.articleId} (lang: {language}, region: {target_region})")

        # Run full analysis with Simple Blog Agent
        analysis = await simple_blog_agent.full_analysis(
            content=payload.content,
            target_region=target_region,
            language=language
        )

        return ProcessingResult(
            article_id=payload.articleId,
            summary=analysis["summary"],
            keywords=analysis["keywords"],
            seo_description=analysis["seo_description"],
            reading_time_minutes=analysis["reading_time"]["reading_time_minutes"],
            word_count=analysis["reading_time"]["word_count"],
            sentiment=analysis["sentiment"]["sentiment"],
            sentiment_confidence=analysis["sentiment"]["confidence"],
            geo_optimization=analysis.get("geo_optimization"),
            processed_at=datetime.utcnow().isoformat(),
        )

    async def _process_ai_request(self, message: Any, message_type: str) -> dict:
        """
        Process AI generation request using Simple Blog Agent.

        Args:
            message: AI generation message
            message_type: Type of AI request

        Returns:
            AI generation result
        """
        payload = message.payload
        content = payload.content
        language = payload.language or "tr"

        logger.info(f"Processing {message_type} request for user {payload.userId} (lang: {language})")

        # Route to appropriate AI method based on message type
        if message_type == "title":
            result = await simple_blog_agent.generate_title(content, language)
            return {"title": result["title"]}
        elif message_type == "excerpt":
            result = await simple_blog_agent.summarize_article(content, 3, language)
            return {"excerpt": result["summary"]}
        elif message_type == "tags":
            result = await simple_blog_agent.extract_keywords(content, 5, language)
            return {"tags": result["keywords"]}
        elif message_type == "seo":
            result = await simple_blog_agent.generate_seo_description(content, 160, language)
            return {"description": result["seo_description"]}
        elif message_type == "content_improvement":
            result = await simple_blog_agent.improve_content(content, language)
            return {"content": result["improved_content"]}
        else:
            raise ValueError(f"Unknown AI message type: {message_type}")

    async def _save_article_result(self, article_id: str, result: ProcessingResult, correlation_id: Optional[str] = None) -> bool:
        """
        Publish article processing result to RabbitMQ (event-driven).

        Backend will consume this event and update the database.

        Args:
            article_id: Article ID
            result: Processing result
            correlation_id: Original message correlation ID for tracking

        Returns:
            True if published successfully
        """
        if self._exchange is None:
            logger.error("RabbitMQ exchange not initialized")
            return False

        try:
            # Prepare event message
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

            # Publish to RabbitMQ
            await self._exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message).encode(),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    message_id=message["messageId"],
                    correlation_id=message["correlationId"],
                ),
                routing_key=AI_ANALYSIS_COMPLETED_ROUTING_KEY,
            )

            logger.info(
                f"Published AI analysis result for article {article_id} "
                f"(correlationId: {message['correlationId']})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to publish result to RabbitMQ: {e}")
            return False

    async def _save_ai_result(self, request_id: str, result: dict, message_type: str, correlation_id: Optional[str] = None) -> bool:
        """
        Publish AI generation result to RabbitMQ (event-driven).

        Backend will consume this event and return the result to the frontend.

        Args:
            request_id: Request ID (messageId)
            result: AI generation result
            message_type: Type of AI request
            correlation_id: Original message correlation ID for tracking

        Returns:
            True if published successfully
        """
        if self._exchange is None:
            logger.error("RabbitMQ exchange not initialized")
            return False

        try:
            # Determine event type and routing key based on message type
            event_type_map = {
                "title": "ai.title.generation.completed",
                "excerpt": "ai.excerpt.generation.completed", 
                "tags": "ai.tags.generation.completed",
                "seo": "ai.seo.generation.completed",
                "content_improvement": "ai.content.improvement.completed"
            }
            
            event_type = event_type_map.get(message_type, f"ai.{message_type}.completed")
            routing_key = event_type

            # Prepare event message
            message = {
                "messageId": str(uuid.uuid4()),
                "correlationId": correlation_id or str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat(),
                "eventType": event_type,
                "payload": {
                    "requestId": request_id,
                    **result
                }
            }

            # Publish to RabbitMQ
            await self._exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message).encode(),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    message_id=message["messageId"],
                    correlation_id=message["correlationId"],
                ),
                routing_key=routing_key,
            )

            logger.info(
                f"Published AI {message_type} result for request {request_id} "
                f"(correlationId: {message['correlationId']})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to publish AI result to RabbitMQ: {e}")
            return False

    async def _process_chat(self, message: ChatRequestMessage) -> dict:
        """
        Process chat message using RAG and optionally web search.

        Args:
            message: Chat request message

        Returns:
            Chat response dict
        """
        payload = message.payload
        post_id = payload.postId
        user_message = payload.userMessage
        language = payload.language
        enable_web_search = payload.enableWebSearch

        logger.info(f"Processing chat for post {post_id}: {user_message[:50]}...")

        # Convert history to ChatMessage objects
        history = [
            ChatMessage(role=item.role, content=item.content)
            for item in payload.conversationHistory
        ]

        # If web search is enabled, perform hybrid search (Web + RAG)
        if enable_web_search:
            logger.info(f"Processing hybrid search for: {user_message[:50]}...")

            # 1. Generate smart search query using LLM with article content for keyword extraction
            smart_query = await rag_chat_handler.generate_search_query(
                article_title=payload.articleTitle,
                user_question=user_message,
                article_content=payload.articleContent,
                language=language
            )
            logger.info(f"Generated smart query: '{smart_query}'")
            
            # 2. Determine region
            region = "tr-tr" if language.lower() == "tr" else "wt-wt"
            if language.lower() == "en":
                region = "us-en"
                
            # 3. Parallel Execution: Web Search + RAG Retrieval
            # Retrieve RAG context to ground the answer
            rag_task = retriever.retrieve_with_context(
                query=user_message,
                post_id=post_id,
                k=5
            )
            
            # Execute web search with smart query
            web_task = web_search_tool.search(
                query=smart_query,
                max_results=10,
                region=region
            )
            
            # Wait for both
            retrieval_result, search_results = await asyncio.gather(rag_task, web_task)
            
            logger.info(f"Web search returned {len(search_results.results)} results")
            logger.info(f"RAG retrieval found {len(retrieval_result.chunks)} chunks")

            # 4. Generate Answer using Hybrid Context
            if search_results.has_results:
                response = await rag_chat_handler.chat_with_web_search(
                    post_id=post_id,
                    user_message=user_message,
                    article_title=payload.articleTitle,
                    web_search_results=[r.to_dict() for r in search_results.results],
                    rag_context=retrieval_result.context,
                    language=language
                )

                return {
                    "response": response.response,
                    "isWebSearchResult": True,
                    "sources": [r.to_dict() for r in search_results.results]
                }
            
            # Fallback to pure RAG if web search fails
            logger.warning("Web search yielded no results, falling back to standard RAG")

        # Use RAG chat handler
        response = await rag_chat_handler.chat(
            post_id=post_id,
            user_message=user_message,
            conversation_history=history,
            language=language
        )

        return {
            "response": response.response,
            "isWebSearchResult": False,
            "sources": None
        }

    async def _index_article(self, message: ArticleMessage) -> dict:
        """
        Index article for RAG retrieval.

        Args:
            message: Article message

        Returns:
            Indexing result dict
        """
        payload = message.payload

        logger.info(f"Indexing article {payload.articleId} for RAG...")
        logger.info(f"Article title: {payload.title}")
        logger.info(f"Content length: {len(payload.content)} characters")
        logger.info(f"Content preview: {payload.content[:300]}...")

        result = await article_indexer.index_article(
            post_id=payload.articleId,
            title=payload.title,
            content=payload.content,
            delete_existing=True
        )

        logger.info(f"Article {payload.articleId} indexed: {result}")
        return result

    async def _save_chat_result(
        self,
        session_id: str,
        result: dict,
        correlation_id: Optional[str] = None
    ) -> bool:
        """
        Publish chat response to RabbitMQ.

        Args:
            session_id: Chat session ID
            result: Chat response
            correlation_id: Original message correlation ID

        Returns:
            True if published successfully
        """
        if self._exchange is None:
            logger.error("RabbitMQ exchange not initialized")
            return False

        try:
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

            await self._exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message).encode(),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    message_id=message["messageId"],
                    correlation_id=message["correlationId"],
                ),
                routing_key=CHAT_RESPONSE_ROUTING_KEY,
            )

            logger.info(
                f"Published chat response for session {session_id} "
                f"(correlationId: {message['correlationId']})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to publish chat result to RabbitMQ: {e}")
            return False
