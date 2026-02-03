"""Simple Blog Agent - RAG-free, direct LLM calls for blog analysis."""

import asyncio
import hashlib
import json
import logging
import re
from typing import Optional
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser

from app.core.config import settings
from app.core.sanitizer import sanitize_content, detect_injection

logger = logging.getLogger(__name__)


def strip_html_and_images(content: str) -> str:
    """
    Remove HTML tags, base64 images, and excessive whitespace.
    Also applies sanitization to protect against prompt injection.
    This significantly speeds up LLM processing by removing non-text data.
    """
    # Check for potential injection attempts (warning only)
    is_suspicious, patterns = detect_injection(content)
    if is_suspicious:
        logger.warning(f"Content contains potential injection patterns: {patterns[:3]}")

    # Remove base64 images (data:image/xxx;base64,...)
    content = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '', content)
    # Remove markdown images ![alt](url)
    content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
    # Remove HTML image tags
    content = re.sub(r'<img[^>]*>', '', content, flags=re.IGNORECASE)
    # Remove HTML tags but keep text content
    content = re.sub(r'<[^>]+>', ' ', content)
    # Remove URLs (http/https)
    content = re.sub(r'https?://\S+', '', content)
    # Apply sanitization for prompt injection protection
    content = sanitize_content(content)
    # Normalize whitespace
    content = re.sub(r'\s+', ' ', content).strip()
    return content


class SimpleBlogAgent:
    """
    RAG'siz blog analiz agent'i - Ollama Gemma3 ile.

    Blog makaleleri için doğrudan LLM çağrıları ile:
    - Özetleme
    - Anahtar kelime çıkarma
    - SEO meta description oluşturma
    - GEO optimizasyonu
    - Duygu analizi
    - Okuma süresi hesaplama
    """

    def __init__(self):
        self._llm: Optional[ChatOllama] = None
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the agent with Ollama Gemma3."""
        if self._initialized:
            return

        logger.info("Initializing SimpleBlogAgent with Ollama Gemma3...")

        # Initialize LLM with Ollama
        self._llm = ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=settings.ollama_temperature,
            timeout=settings.ollama_timeout,
            num_ctx=settings.ollama_num_ctx,
        )

        self._initialized = True
        logger.info("SimpleBlogAgent initialized successfully")

    def _ensure_initialized(self) -> None:
        """Ensure agent is initialized before use."""
        if not self._initialized:
            self.initialize()

    async def warmup(self) -> None:
        """
        Warm up the model by making a simple call.
        This loads the model into memory so first real request is fast.
        """
        self._ensure_initialized()
        logger.info("Starting model warmup...")

        # Simple prompt to load model into memory
        prompt = ChatPromptTemplate.from_template("Say 'ready' in one word:")
        chain = prompt | self._llm | StrOutputParser()

        result = await chain.ainvoke({})
        logger.info(f"Warmup complete, model response: {result.strip()}")

    async def summarize_article(
        self,
        content: str,
        max_sentences: int = 3,
        language: str = "tr"
    ) -> str:
        """
        Makale özeti oluştur.

        Args:
            content: Makale içeriği
            max_sentences: Maksimum cümle sayısı
            language: Dil (tr, en)

        Returns:
            Özet metin
        """
        self._ensure_initialized()

        if language == "tr":
            prompt_template = """Sen bir blog yazarı asistanısın. Aşağıdaki blog makalesini {max_sentences} cümle ile özetle.

Özet, makalenin ana fikrini ve en önemli noktalarını içermeli.

Makale:
{content}

Özet:"""
        else:
            prompt_template = """You are a blog writer assistant. Summarize the following blog article in {max_sentences} sentences.

The summary should capture the main idea and most important points of the article.

Article:
{content}

Summary:"""

        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | self._llm | StrOutputParser()

        # Clean content from images, HTML, URLs then truncate
        cleaned_content = strip_html_and_images(content)
        truncated_content = cleaned_content[:4000]

        result = await chain.ainvoke({
            "max_sentences": max_sentences,
            "content": truncated_content
        })

        return result.strip()

    async def extract_keywords(
        self,
        content: str,
        count: int = 5,
        language: str = "tr"
    ) -> list[str]:
        """
        Anahtar kelime çıkar.

        Args:
            content: Makale içeriği
            count: Anahtar kelime sayısı
            language: Dil (tr, en)

        Returns:
            Anahtar kelimeler listesi
        """
        self._ensure_initialized()

        if language == "tr":
            prompt_template = """Bu blog içeriğinden en önemli {count} anahtar kelimeyi çıkar.

Anahtar kelimeler, makalenin konusunu ve içeriğini en iyi şekilde tanımlamalı.

Sadece virgülle ayrılmış kelimeleri döndür, açıklama yapma.
Örnek format: kelime1, kelime2, kelime3

İçerik:
{content}

Anahtar kelimeler:"""
        else:
            prompt_template = """Extract the {count} most important keywords from this blog content.

Keywords should best describe the topic and content of the article.

Return only comma-separated keywords, no explanation.
Example format: keyword1, keyword2, keyword3

Content:
{content}

Keywords:"""

        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | self._llm | StrOutputParser()

        # Clean and truncate content
        cleaned_content = strip_html_and_images(content)
        truncated_content = cleaned_content[:3000]

        result = await chain.ainvoke({
            "count": count,
            "content": truncated_content
        })

        # Parse keywords from result
        keywords_text = result.strip()
        if "," in keywords_text:
            keywords = [kw.strip() for kw in keywords_text.split(",")]
        else:
            keywords = [keywords_text]

        return keywords[:count]

    async def generate_seo_description(
        self,
        content: str,
        max_length: int = 160,
        language: str = "tr"
    ) -> str:
        """
        SEO meta description oluştur.

        Args:
            content: Makale içeriği
            max_length: Maksimum karakter uzunluğu
            language: Dil (tr, en)

        Returns:
            SEO meta description
        """
        self._ensure_initialized()

        if language == "tr":
            prompt_template = """Bu blog içeriği için Google arama sonuçlarında görünecek {max_length} karakterlik SEO meta description yaz.

Description:
- Tıklama oranını artıracak ilgi çekici olmalı
- Anahtar kelimeleri içermeli
- Mümkünse {max_length} karakterden uzun olmamalı
- Cümle tam ve anlaşılır olmalı

İçerik:
{content}

Meta Description ({max_length} karakter max):"""
        else:
            prompt_template = """Write a {max_length} character SEO meta description for this blog content to appear in Google search results.

Description should:
- Be compelling to increase click-through rate
- Include relevant keywords
- Be no longer than {max_length} characters if possible
- Be a complete and understandable sentence

Content:
{content}

Meta Description (max {max_length} characters):"""

        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | self._llm | StrOutputParser()

        # Clean and truncate content
        cleaned_content = strip_html_and_images(content)
        truncated_content = cleaned_content[:3000]

        result = await chain.ainvoke({
            "max_length": max_length,
            "content": truncated_content
        })

        # Trim to max_length if needed
        description = result.strip()
        if len(description) > max_length:
            description = description[:max_length-3] + "..."

        return description

    async def analyze_sentiment(
        self,
        content: str,
        language: str = "tr"
    ) -> dict:
        """
        Duygu analizi yap.

        Args:
            content: Makale içeriği
            language: Dil (tr, en)

        Returns:
            Duygu analizi sonucu: {"sentiment": "pozitif/negatif/notr", "confidence": 0-100}
        """
        self._ensure_initialized()

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

        prompt = ChatPromptTemplate.from_template(prompt_template)
        parser = JsonOutputParser()
        chain = prompt | self._llm | parser

        # Clean and truncate content
        cleaned_content = strip_html_and_images(content)
        truncated_content = cleaned_content[:3000]

        try:
            result = await chain.ainvoke({"content": truncated_content})
            return result
        except Exception as e:
            logger.error(f"Sentiment analysis failed: {e}")
            # Fallback with safe default (confidence: 0-100 integer as per prompt)
            return {
                "sentiment": "neutral",
                "confidence": 50,
                "reasoning": "Analysis failed, using fallback"
            }

    def calculate_reading_time(
        self,
        content: str,
        words_per_minute: int = 200
    ) -> dict:
        """
        Okuma süresi hesapla.

        Args:
            content: Makale içeriği
            words_per_minute: Dakikadaki kelime sayısı

        Returns:
            Okuma süresi bilgisi
        """
        word_count = len(content.split())
        reading_time_minutes = max(1, round(word_count / words_per_minute))

        return {
            "word_count": word_count,
            "reading_time_minutes": reading_time_minutes,
            "words_per_minute": words_per_minute
        }

    async def optimize_for_geo(
        self,
        content: str,
        target_region: str = "TR",
        language: str = "tr"
    ) -> dict:
        """
        İçeriği belirli bir bölge için optimize et (GEO targeting).

        Args:
            content: Makale içeriği
            target_region: Hedef bölge (TR, US, DE, GB, etc.)
            language: İçerik dili

        Returns:
            GEO optimizasyon sonuçları
        """
        self._ensure_initialized()

        region_tips = {
            "TR": """Türkiye için ipuçları:
- Türkçe kültürel referanslar kullan
- Yerel keywordler: Türkiye, Türk, İstanbul, Ankara, vs.
- Türkçeye özgü deyimler ve ifadeler""",
            "US": """USA için ipuçları:
- American English spelling (color, center, vs.)
- US cultural references and holidays
- US-specific terminology""",
            "GB": """UK için ipuçları:
- British English spelling (colour, centre, vs.)
- UK cultural references
- Metric system""",
            "DE": """Germany için ipuçları:
- German language
- German cultural references
- EU regulations""",
        }

        tip = region_tips.get(target_region, f"{target_region} bölgesi için optimize et")

        if language == "tr":
            prompt_template = """Bu blog içeriğini {region} bölgesi için SEO ve GEO olarak optimize et.

Bölge ipuçları:
{tip}

Şu bilgileri JSON formatında döndür:
{{
  "optimized_title": "SEO uyumlu başlık",
  "meta_description": "160 karakter meta description",
  "geo_keywords": ["bölgeye özel keyword1", "keyword2", "keyword3"],
  "cultural_adaptations": "Kültürel uyarlama notları",
  "language_adjustments": "Dil düzeltmeleri",
  "target_audience": "Hedef kitle tanımı"
}}

İçerik:
{content}

Optimizasyon:"""
        else:
            prompt_template = """Optimize this blog content for SEO and GEO targeting in {region} region.

Region tips:
{tip}

Return this information in JSON format:
{{
  "optimized_title": "SEO-optimized title",
  "meta_description": "160 character meta description",
  "geo_keywords": ["region-specific keyword1", "keyword2", "keyword3"],
  "cultural_adaptations": "Cultural adaptation notes",
  "language_adjustments": "Language adjustments",
  "target_audience": "Target audience definition"
}}

Content:
{content}

Optimization:"""

        prompt = ChatPromptTemplate.from_template(prompt_template)
        parser = JsonOutputParser()
        chain = prompt | self._llm | parser

        # Clean and truncate content
        cleaned_content = strip_html_and_images(content)
        truncated_content = cleaned_content[:4000]

        try:
            result = await chain.ainvoke({
                "region": target_region,
                "tip": tip,
                "content": truncated_content
            })
            return result
        except Exception as e:
            logger.error(f"GEO optimization failed: {e}")
            # Fallback with safe default - matching expected response structure
            return {
                "optimized_title": "",
                "meta_description": "",
                "geo_keywords": [],
                "cultural_adaptations": "Analysis failed, no adaptations applied",
                "language_adjustments": "No adjustments applied",
                "target_audience": "General audience"
            }

    async def full_analysis(
        self,
        content: str,
        target_region: str = "TR",
        language: str = "tr"
    ) -> dict:
        """
        Tam blog analizi - tüm özellikler (paralel çalıştırma).

        Args:
            content: Makale içeriği
            target_region: Hedef bölge
            language: Dil

        Returns:
            Tam analiz sonuçları
        """
        logger.info(f"Starting full analysis for region: {target_region}")

        # Calculate reading time synchronously (no LLM call)
        reading_time = self.calculate_reading_time(content)

        # Run all LLM analyses in parallel for maximum performance
        summary_task = self.summarize_article(content, language=language)
        keywords_task = self.extract_keywords(content, language=language)
        seo_desc_task = self.generate_seo_description(content, language=language)
        sentiment_task = self.analyze_sentiment(content, language=language)
        geo_task = self.optimize_for_geo(content, target_region, language)

        # Execute all tasks concurrently
        summary, keywords, seo_desc, sentiment, geo = await asyncio.gather(
            summary_task,
            keywords_task,
            seo_desc_task,
            sentiment_task,
            geo_task,
            return_exceptions=True
        )

        # Handle any exceptions from individual tasks
        if isinstance(summary, Exception):
            logger.error(f"Summary failed: {summary}")
            summary = "Özet oluşturulamadı"
        if isinstance(keywords, Exception):
            logger.error(f"Keywords failed: {keywords}")
            keywords = []
        if isinstance(seo_desc, Exception):
            logger.error(f"SEO desc failed: {seo_desc}")
            seo_desc = ""
        if isinstance(sentiment, Exception):
            logger.error(f"Sentiment failed: {sentiment}")
            sentiment = {"sentiment": "neutral", "confidence": 50}
        if isinstance(geo, Exception):
            logger.error(f"GEO failed: {geo}")
            geo = {"optimized_title": "", "meta_description": "", "geo_keywords": []}

        result = {
            "summary": summary,
            "keywords": keywords,
            "seo_description": seo_desc,
            "sentiment": sentiment,
            "reading_time": reading_time,
            "geo_optimization": geo,
        }

        logger.info("Full analysis completed (parallel execution)")
        return result


# Global agent instance
simple_blog_agent = SimpleBlogAgent()
