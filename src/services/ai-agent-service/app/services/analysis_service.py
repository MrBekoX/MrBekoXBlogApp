"""Analysis service - Blog content analysis operations."""

import asyncio
import logging
from typing import Any

from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.domain.entities.analysis import (
    SentimentResult,
    ReadingTimeResult,
    FullAnalysisResult,
)
from app.services.content_cleaner import ContentCleanerService
from app.services.seo_service import SeoService

logger = logging.getLogger(__name__)


class AnalysisService:
    """
    Service for blog content analysis.

    Single Responsibility: Content analysis (summary, keywords, sentiment, reading time).
    Dependencies injected via constructor (DIP).
    """

    def __init__(
        self,
        llm_provider: ILLMProvider,
        seo_service: SeoService | None = None,
        content_cleaner: ContentCleanerService | None = None,
    ):
        self._llm = llm_provider
        self._seo_service = seo_service
        self._cleaner = content_cleaner or ContentCleanerService()

    async def summarize_article(
        self,
        content: str,
        max_sentences: int = 3,
        language: str = "tr"
    ) -> str:
        """
        Generate article summary.

        Args:
            content: Article content
            max_sentences: Maximum sentences in summary
            language: Content language

        Returns:
            Summary text
        """
        cleaned = self._cleaner.strip_html_and_images(content)
        truncated = cleaned[:4000]

        if language == "tr":
            prompt = f"""Sen bir blog yazarı asistanısın. Aşağıdaki blog makalesini {max_sentences} cümle ile özetle.

Özet, makalenin ana fikrini ve en önemli noktalarını içermeli.

Makale:
{truncated}

Özet:"""
        else:
            prompt = f"""You are a blog writer assistant. Summarize the following blog article in {max_sentences} sentences.

The summary should capture the main idea and most important points of the article.

Article:
{truncated}

Summary:"""

        result = await self._llm.generate_text(prompt, think=False)
        return result.strip()

    async def extract_keywords(
        self,
        content: str,
        count: int = 5,
        language: str = "tr"
    ) -> list[str]:
        """
        Extract keywords from content.

        Args:
            content: Article content
            count: Number of keywords
            language: Content language

        Returns:
            List of keywords
        """
        cleaned = self._cleaner.strip_html_and_images(content)
        truncated = cleaned[:3000]

        if language == "tr":
            prompt = f"""Bu blog içeriğinden en önemli {count} anahtar kelimeyi çıkar.

Anahtar kelimeler, makalenin konusunu ve içeriğini en iyi şekilde tanımlamalı.

Sadece virgülle ayrılmış kelimeleri döndür, açıklama yapma.
Örnek format: kelime1, kelime2, kelime3

İçerik:
{truncated}

Anahtar kelimeler:"""
        else:
            prompt = f"""Extract the {count} most important keywords from this blog content.

Keywords should best describe the topic and content of the article.

Return only comma-separated keywords, no explanation.
Example format: keyword1, keyword2, keyword3

Content:
{truncated}

Keywords:"""

        result = await self._llm.generate_text(prompt, think=False)

        # Parse keywords
        keywords_text = result.strip()
        if "," in keywords_text:
            keywords = [kw.strip() for kw in keywords_text.split(",")]
        else:
            keywords = [keywords_text]

        return keywords[:count]

    async def analyze_sentiment(
        self,
        content: str,
        language: str = "tr"
    ) -> SentimentResult:
        """
        Analyze content sentiment.

        Args:
            content: Article content
            language: Content language

        Returns:
            SentimentResult with sentiment, confidence, and reasoning
        """
        if language == "tr":
            prompt_template = """Bu metnin duygu durumunu analiz et.

Sadece JSON formatında şu bilgileri döndür:
{{
  "sentiment": "pozitif",
  "confidence": 85,
  "reasoning": "Kısa açıklama"
}}

sentiment değerleri: "pozitif", "negatif", "notr"
confidence: 0-100 arası sayı

Metin:
{content}

Analiz:"""
        else:
            prompt_template = """Analyze the sentiment of this text.

Return only this JSON format:
{{
  "sentiment": "positive",
  "confidence": 85,
  "reasoning": "Brief explanation"
}}

sentiment values: "positive", "negative", "neutral"
confidence: number from 0-100

Text:
{content}

Analysis:"""

        cleaned = self._cleaner.strip_html_and_images(content)
        truncated = cleaned[:3000]

        try:
            result = await self._llm.generate_json(
                prompt_template.format(content=truncated)
            )
            return SentimentResult(
                sentiment=result.get("sentiment", "neutral"),
                confidence=result.get("confidence", 50),
                reasoning=result.get("reasoning")
            )
        except Exception as e:
            logger.error(f"Sentiment analysis failed: {e}")
            return SentimentResult(
                sentiment="neutral",
                confidence=50,
                reasoning="Analysis failed"
            )

    def calculate_reading_time(
        self,
        content: str,
        words_per_minute: int = 200
    ) -> ReadingTimeResult:
        """
        Calculate estimated reading time.

        Args:
            content: Article content
            words_per_minute: Reading speed

        Returns:
            ReadingTimeResult
        """
        word_count = len(content.split())
        reading_time = max(1, round(word_count / words_per_minute))

        return ReadingTimeResult(
            word_count=word_count,
            reading_time_minutes=reading_time,
            words_per_minute=words_per_minute
        )

    async def full_analysis(
        self,
        content: str,
        target_region: str = "TR",
        language: str = "tr"
    ) -> FullAnalysisResult:
        """
        Perform full article analysis (parallel execution).

        Args:
            content: Article content
            target_region: Target region for GEO
            language: Content language

        Returns:
            FullAnalysisResult with all analysis data
        """
        logger.info(f"Starting full analysis for region: {target_region}")

        # Calculate reading time synchronously
        reading_time = self.calculate_reading_time(content)

        # Run all LLM analyses in parallel
        tasks = [
            self.summarize_article(content, language=language),
            self.extract_keywords(content, language=language),
            self.analyze_sentiment(content, language=language),
        ]

        # Add SEO service tasks if available
        if self._seo_service:
            tasks.append(
                self._seo_service.generate_seo_description(content, language=language)
            )
            tasks.append(
                self._seo_service.optimize_for_geo(content, target_region, language)
            )
        else:
            tasks.append(self._generate_seo_description(content, language))
            tasks.append(asyncio.coroutine(lambda: None)())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions with detailed logging
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                task_names = ["summary", "keywords", "sentiment", "seo_description", "geo_optimization"]
                task_name = task_names[i] if i < len(task_names) else f"task_{i}"
                logger.error(f"Analysis task '{task_name}' failed: {result}")

        summary = results[0] if not isinstance(results[0], Exception) else "Özet oluşturulamadı"
        keywords = results[1] if not isinstance(results[1], Exception) else []
        sentiment = results[2] if not isinstance(results[2], Exception) else SentimentResult(
            sentiment="neutral", confidence=50
        )
        seo_desc = results[3] if not isinstance(results[3], Exception) else ""
        geo_opt = results[4] if len(results) > 4 and not isinstance(results[4], Exception) else None

        return FullAnalysisResult(
            summary=summary,
            keywords=keywords,
            seo_description=seo_desc,
            sentiment=sentiment,
            reading_time=reading_time,
            geo_optimization=geo_opt,
        )

    async def _generate_seo_description(
        self,
        content: str,
        language: str = "tr",
        max_length: int = 160
    ) -> str:
        """Fallback SEO description generation."""
        if language == "tr":
            prompt = f"""Bu blog içeriği için {max_length} karakterlik SEO meta description yaz.

İçerik:
{content[:3000]}

Meta Description:"""
        else:
            prompt = f"""Write a {max_length} character SEO meta description for this content.

Content:
{content[:3000]}

Meta Description:"""

        result = await self._llm.generate_text(prompt, think=False)
        desc = result.strip()
        if len(desc) > max_length:
            desc = desc[:max_length - 3] + "..."
        return desc
