"""Web Search interface - Contract for web search services."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchResult:
    """A single web search result."""

    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet
        }


@dataclass
class SearchResponse:
    """Response from web search."""

    query: str
    results: list[SearchResult]
    total_results: int

    @property
    def has_results(self) -> bool:
        """Check if any results were found."""
        return len(self.results) > 0


class IWebSearchProvider(ABC):
    """
    Abstract interface for web search providers.

    Implementations can be DuckDuckGo, Google, Bing, etc.
    """

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 10,
        region: str = "wt-wt",
        safe_search: str = "moderate"
    ) -> SearchResponse:
        """
        Perform a web search.

        Args:
            query: Search query
            max_results: Maximum number of results
            region: Region code (e.g., 'tr-tr', 'us-en')
            safe_search: Safe search level

        Returns:
            SearchResponse with results
        """
        pass

    @abstractmethod
    async def search_for_verification(
        self,
        claim: str,
        max_results: int = 3
    ) -> SearchResponse:
        """
        Search to verify a claim (fact-checking).

        Args:
            claim: The claim to verify
            max_results: Maximum number of results

        Returns:
            SearchResponse with verification sources
        """
        pass
