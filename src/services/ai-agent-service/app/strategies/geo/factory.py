"""GEO Strategy Factory - Creates appropriate strategy based on region code."""

import logging
from typing import Type

from app.strategies.geo.base import IGeoStrategy
from app.strategies.geo.tr_strategy import TurkeyGeoStrategy
from app.strategies.geo.us_strategy import USAGeoStrategy
from app.strategies.geo.uk_strategy import UKGeoStrategy
from app.strategies.geo.de_strategy import GermanyGeoStrategy

logger = logging.getLogger(__name__)

# Registry of available strategies
_STRATEGY_REGISTRY: dict[str, Type[IGeoStrategy]] = {
    "TR": TurkeyGeoStrategy,
    "US": USAGeoStrategy,
    "GB": UKGeoStrategy,
    "UK": UKGeoStrategy,  # Alias
    "DE": GermanyGeoStrategy,
}

# Default strategy for unknown regions
_DEFAULT_REGION = "TR"


class GeoStrategyFactory:
    """
    Factory for creating GEO optimization strategies.

    Uses Factory Pattern to create appropriate strategy based on region code.
    New strategies can be registered without modifying existing code (OCP).
    """

    @staticmethod
    def get_strategy(region_code: str) -> IGeoStrategy:
        """
        Get the appropriate GEO strategy for a region.

        Args:
            region_code: ISO region code (e.g., 'TR', 'US', 'GB', 'DE')

        Returns:
            IGeoStrategy instance for the region
        """
        code_upper = region_code.upper()

        if code_upper in _STRATEGY_REGISTRY:
            strategy_class = _STRATEGY_REGISTRY[code_upper]
            return strategy_class()

        logger.warning(
            f"No strategy found for region '{region_code}', "
            f"using default ({_DEFAULT_REGION})"
        )
        return _STRATEGY_REGISTRY[_DEFAULT_REGION]()

    @staticmethod
    def register_strategy(region_code: str, strategy_class: Type[IGeoStrategy]) -> None:
        """
        Register a new GEO strategy.

        Args:
            region_code: ISO region code
            strategy_class: Strategy class implementing IGeoStrategy
        """
        code_upper = region_code.upper()
        _STRATEGY_REGISTRY[code_upper] = strategy_class
        logger.info(f"Registered GEO strategy for region: {code_upper}")

    @staticmethod
    def get_available_regions() -> list[str]:
        """Get list of available region codes."""
        return list(_STRATEGY_REGISTRY.keys())

    @staticmethod
    def is_region_supported(region_code: str) -> bool:
        """Check if a region is supported."""
        return region_code.upper() in _STRATEGY_REGISTRY
