"""UK GEO strategy - Optimization for British market."""

from app.strategies.geo.base import IGeoStrategy


class UKGeoStrategy(IGeoStrategy):
    """GEO optimization strategy for United Kingdom (GB)."""

    @property
    def region_code(self) -> str:
        return "GB"

    @property
    def region_name(self) -> str:
        return "United Kingdom"

    @property
    def primary_language(self) -> str:
        return "en"

    def get_cultural_context(self) -> str:
        return """British readers appreciate wit and understatement.
- Subtle humor works well
- Avoid over-the-top claims
- Quality over quantity messaging
- Tradition and heritage can be valuable
- Privacy and data protection awareness is high"""

    def get_market_keywords(self) -> list[str]:
        return [
            "quality",
            "trusted",
            "established",
            "reliable",
            "premium",
            "bespoke",
            "value",
            "British",
            "award-winning",
            "sustainable",
            "ethical",
            "compliant",
        ]

    def get_seo_tips(self) -> str:
        return """UK SEO Tips:
- Use British English spelling (colour, centre, optimise)
- Target google.co.uk
- Include UK-specific terms and references
- GDPR compliance is essential
- Local business schema for UK addresses"""

    def get_content_style_guide(self) -> str:
        return """UK Content Style:
- Slightly more formal than US content
- Understated tone - avoid hyperbole
- Use 's' endings (realise, organise)
- Include relevant UK regulations/standards
- Tea references are always appreciated (light humor)"""
