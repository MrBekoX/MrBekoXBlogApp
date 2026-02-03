"""Germany GEO strategy - Optimization for German market."""

from app.strategies.geo.base import IGeoStrategy


class GermanyGeoStrategy(IGeoStrategy):
    """GEO optimization strategy for Germany (DE)."""

    @property
    def region_code(self) -> str:
        return "DE"

    @property
    def region_name(self) -> str:
        return "Germany"

    @property
    def primary_language(self) -> str:
        return "de"

    def get_cultural_context(self) -> str:
        return """German readers value precision and thoroughness.
- Detailed, well-researched content is expected
- Technical accuracy is crucial
- Direct communication style preferred
- Quality and engineering excellence matter
- Environmental consciousness is important"""

    def get_market_keywords(self) -> list[str]:
        return [
            "Qualität",
            "Made in Germany",
            "zuverlässig",
            "präzise",
            "nachhaltig",
            "umweltfreundlich",
            "sicher",
            "geprüft",
            "zertifiziert",
            "Datenschutz",
            "DSGVO-konform",
            "effizient",
        ]

    def get_seo_tips(self) -> str:
        return """Germany SEO Tips:
- German language content is essential
- Target google.de
- DSGVO (GDPR) compliance is mandatory
- Include German certifications (TÜV, etc.)
- Technical specifications are valued"""

    def get_content_style_guide(self) -> str:
        return """Germany Content Style:
- Formal tone using 'Sie' (formal you)
- Comprehensive and detailed explanations
- Include data, statistics, and sources
- Clear structure with logical flow
- Avoid marketing fluff - substance over style"""
