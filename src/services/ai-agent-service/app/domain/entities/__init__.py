"""Domain entities - Pydantic models for request/response schemas."""

from app.domain.entities.article import (
    ArticlePayload,
    ArticleMessage,
    ProcessingResult,
)
from app.domain.entities.analysis import (
    AnalyzeRequest,
    SummarizeRequest,
    KeywordsRequest,
    SeoRequest,
    SentimentRequest,
    ReadingTimeRequest,
    GeoOptimizeRequest,
    SentimentResult,
    ReadingTimeResult,
    GeoOptimizationResult,
    FullAnalysisResult,
)
from app.domain.entities.chat import (
    ChatMessage,
    ChatHistoryItem,
    ChatRequestPayload,
    ChatRequestMessage,
    ChatResponse,
)
from app.domain.entities.ai_generation import (
    AiTitleGenerationPayload,
    AiExcerptGenerationPayload,
    AiTagsGenerationPayload,
    AiSeoDescriptionGenerationPayload,
    AiContentImprovementPayload,
    AiTitleGenerationMessage,
    AiExcerptGenerationMessage,
    AiTagsGenerationMessage,
    AiSeoDescriptionGenerationMessage,
    AiContentImprovementMessage,
)

__all__ = [
    # Article
    "ArticlePayload",
    "ArticleMessage",
    "ProcessingResult",
    # Analysis
    "AnalyzeRequest",
    "SummarizeRequest",
    "KeywordsRequest",
    "SeoRequest",
    "SentimentRequest",
    "ReadingTimeRequest",
    "GeoOptimizeRequest",
    "SentimentResult",
    "ReadingTimeResult",
    "GeoOptimizationResult",
    "FullAnalysisResult",
    # Chat
    "ChatMessage",
    "ChatHistoryItem",
    "ChatRequestPayload",
    "ChatRequestMessage",
    "ChatResponse",
    # AI Generation
    "AiTitleGenerationPayload",
    "AiExcerptGenerationPayload",
    "AiTagsGenerationPayload",
    "AiSeoDescriptionGenerationPayload",
    "AiContentImprovementPayload",
    "AiTitleGenerationMessage",
    "AiExcerptGenerationMessage",
    "AiTagsGenerationMessage",
    "AiSeoDescriptionGenerationMessage",
    "AiContentImprovementMessage",
]
