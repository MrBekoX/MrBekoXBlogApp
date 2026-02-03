"""GEO optimization strategies for different regions."""

from app.strategies.geo.base import IGeoStrategy
from app.strategies.geo.factory import GeoStrategyFactory
from app.strategies.geo.tr_strategy import TurkeyGeoStrategy
from app.strategies.geo.us_strategy import USAGeoStrategy
from app.strategies.geo.uk_strategy import UKGeoStrategy
from app.strategies.geo.de_strategy import GermanyGeoStrategy

__all__ = [
    "IGeoStrategy",
    "GeoStrategyFactory",
    "TurkeyGeoStrategy",
    "USAGeoStrategy",
    "UKGeoStrategy",
    "GermanyGeoStrategy",
]
