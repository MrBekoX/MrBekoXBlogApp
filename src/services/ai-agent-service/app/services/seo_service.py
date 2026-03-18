"""SEO service - Search engine and GEO optimization."""

import json
import logging
from typing import Any

from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.domain.entities.analysis import GeoOptimizationResult
from app.strategies.geo.factory import GeoStrategyFactory
from app.services.content_cleaner import ContentCleanerService

logger = logging.getLogger(__name__)


def _to_string(value: Any) -> str:
    """Convert any value to string for Pydantic validation.

    LLM may return dict/list instead of string, so we need to handle this.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        # Pretty-print complex types as JSON string
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


class SeoService:
    """
    Service for SEO and GEO optimization.

    Single Responsibility: SEO and regional content optimization.
    Uses Strategy Pattern for GEO optimization (OCP).
    """

    def __init__(
        self,
        llm_provider: ILLMProvider,
        content_cleaner: ContentCleanerService | None = None,
    ):
        self._llm = llm_provider
        self._cleaner = content_cleaner or ContentCleanerService()

    async def generate_seo_description(
        self,
        content: str,
        max_length: int = 160,
        language: str = "tr"
    ) -> str:
        """
        Generate SEO meta description.

        Args:
            content: Article content
            max_length: Maximum character length
            language: Content language

        Returns:
            SEO meta description
        """
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

        cleaned = self._cleaner.strip_html_and_images(content)
        truncated = cleaned[:3000]
        prompt = prompt_template.format(max_length=max_length, content=truncated)

        result = await self._llm.generate_text(prompt)

        description = result.strip()
        if len(description) > max_length:
            description = description[:max_length - 3] + "..."

        return description

    async def optimize_for_geo(
        self,
        content: str,
        target_region: str = "TR",
        language: str = "tr"
    ) -> GeoOptimizationResult:
        """
        Optimize content for specific region using Strategy Pattern.

        Args:
            content: Article content
            target_region: Target region code (TR, US, GB, DE)
            language: Content language

        Returns:
            GeoOptimizationResult with optimized content
        """
        # Get strategy for the region (OCP - new regions don't require code changes)
        strategy = GeoStrategyFactory.get_strategy(target_region)
        context = strategy.get_full_context()

        if language == "tr":
            prompt_template = """Bu blog içeriğini {region} bölgesi için SEO ve GEO olarak optimize et.

BÖLGE BİLGİLERİ:
- Bölge: {region_name}
- Kültürel Bağlam: {cultural_context}
- Pazar Anahtar Kelimeleri: {market_keywords}
- SEO İpuçları: {seo_tips}
- İçerik Stili: {content_style}

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

REGION INFO:
- Region: {region_name}
- Cultural Context: {cultural_context}
- Market Keywords: {market_keywords}
- SEO Tips: {seo_tips}
- Content Style: {content_style}

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

        cleaned = self._cleaner.strip_html_and_images(content)
        truncated = cleaned[:4000]

        try:
            prompt = prompt_template.format(
                region=context["region_code"],
                region_name=context["region_name"],
                cultural_context=context["cultural_context"],
                market_keywords=", ".join(context["market_keywords"]),
                seo_tips=context["seo_tips"],
                content_style=context["content_style_guide"],
                content=truncated
            )

            result = await self._llm.generate_json(prompt)

            # Use _to_string to handle LLM returning dict/list instead of string
            return GeoOptimizationResult(
                optimized_title=_to_string(result.get("optimized_title")),
                meta_description=_to_string(result.get("meta_description")),
                geo_keywords=result.get("geo_keywords", []) if isinstance(result.get("geo_keywords"), list) else [],
                cultural_adaptations=_to_string(result.get("cultural_adaptations")),
                language_adjustments=_to_string(result.get("language_adjustments")),
                target_audience=_to_string(result.get("target_audience"))
            )

        except Exception as e:
            logger.error(f"GEO optimization failed: {e}")
            return GeoOptimizationResult(
                optimized_title="",
                meta_description="",
                geo_keywords=[],
                cultural_adaptations="Optimization failed",
                language_adjustments="No adjustments",
                target_audience="General audience"
            )

    async def generate_title_suggestions(
        self,
        content: str,
        count: int = 3,
        language: str = "tr"
    ) -> list[str]:
        """
        Generate SEO-optimized title suggestions.

        Args:
            content: Article content
            count: Number of suggestions
            language: Content language

        Returns:
            List of title suggestions
        """
        if language == "tr":
            prompt = f"""Bu içerik için {count} adet SEO uyumlu başlık önerisi yaz.

Başlıklar:
- Dikkat çekici ve merak uyandırıcı olmalı
- 60 karakteri geçmemeli
- Anahtar kelimeler içermeli

İçerik:
{content[:2000]}

Başlık önerileri (her biri yeni satırda):"""
        else:
            prompt = f"""Write {count} SEO-optimized title suggestions for this content.

Titles should:
- Be attention-grabbing and intriguing
- Not exceed 60 characters
- Include keywords

Content:
{content[:2000]}

Title suggestions (each on new line):"""

        result = await self._llm.generate_text(prompt)
        titles = [t.strip() for t in result.strip().split("\n") if t.strip()]
        return titles[:count]
