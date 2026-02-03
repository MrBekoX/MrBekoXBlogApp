"""Base GEO strategy interface - Strategy pattern for regional optimization."""

from abc import ABC, abstractmethod


class IGeoStrategy(ABC):
    """
    Abstract interface for GEO optimization strategies.

    Each strategy provides region-specific context for content optimization.
    New regions can be added by implementing this interface without
    modifying existing code (Open/Closed Principle).
    """

    @property
    @abstractmethod
    def region_code(self) -> str:
        """Return the region code (e.g., 'TR', 'US')."""
        pass

    @property
    @abstractmethod
    def region_name(self) -> str:
        """Return the full region name."""
        pass

    @property
    @abstractmethod
    def primary_language(self) -> str:
        """Return the primary language code."""
        pass

    @abstractmethod
    def get_cultural_context(self) -> str:
        """
        Get cultural context for content optimization.

        Returns:
            String describing cultural preferences and communication style.
        """
        pass

    @abstractmethod
    def get_market_keywords(self) -> list[str]:
        """
        Get region-specific marketing keywords.

        Returns:
            List of keywords that resonate with the target market.
        """
        pass

    @abstractmethod
    def get_seo_tips(self) -> str:
        """
        Get SEO tips specific to the region.

        Returns:
            String with SEO recommendations for the region.
        """
        pass

    @abstractmethod
    def get_content_style_guide(self) -> str:
        """
        Get content style guidelines for the region.

        Returns:
            String describing preferred content style and tone.
        """
        pass

    def get_full_context(self) -> dict:
        """
        Get complete context for GEO optimization.

        Returns:
            Dictionary with all optimization context.
        """
        return {
            "region_code": self.region_code,
            "region_name": self.region_name,
            "primary_language": self.primary_language,
            "cultural_context": self.get_cultural_context(),
            "market_keywords": self.get_market_keywords(),
            "seo_tips": self.get_seo_tips(),
            "content_style_guide": self.get_content_style_guide(),
        }
