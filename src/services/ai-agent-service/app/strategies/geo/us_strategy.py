"""USA GEO strategy - Optimization for US market."""

from app.strategies.geo.base import IGeoStrategy


class USAGeoStrategy(IGeoStrategy):
    """GEO optimization strategy for United States (US)."""

    @property
    def region_code(self) -> str:
        return "US"

    @property
    def region_name(self) -> str:
        return "United States"

    @property
    def primary_language(self) -> str:
        return "en"

    def get_cultural_context(self) -> str:
        return """American readers appreciate directness and value.
- Get to the point quickly - time is valuable
- Use success stories and case studies
- Emphasize individual achievement and innovation
- Data-driven arguments work well
- Diversity and inclusivity matter"""

    def get_market_keywords(self) -> list[str]:
        return [
            "free",
            "best",
            "top",
            "ultimate",
            "proven",
            "guaranteed",
            "exclusive",
            "limited time",
            "save",
            "easy",
            "fast",
            "innovative",
        ]

    def get_seo_tips(self) -> str:
        return """US SEO Tips:
- Use American English spelling (color, center, optimize)
- Target google.com
- Include state/city names for local SEO
- Voice search optimization is important
- Featured snippets are highly valuable"""

    def get_content_style_guide(self) -> str:
        return """US Content Style:
- Clear, concise, and action-oriented
- Use contractions (you're, it's, don't)
- Include clear CTAs (Call to Action)
- Break up text with subheadings
- Use numbered lists for step-by-step content"""
