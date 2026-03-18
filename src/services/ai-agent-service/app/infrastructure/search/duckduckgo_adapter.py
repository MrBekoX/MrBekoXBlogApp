"""DuckDuckGo search adapter - Concrete implementation of IWebSearchProvider."""

import asyncio
import logging
import time
from typing import Any

from ddgs import DDGS

from app.domain.interfaces.i_web_search import (
    IWebSearchProvider,
    SearchResult,
    SearchResponse,
)
from app.monitoring.metrics import record_tool_invocation

logger = logging.getLogger(__name__)

# Search configuration
SEARCH_TIMEOUT_SECONDS = 15  # Max time for search operation
MAX_RETRY_ATTEMPTS = 2

def _sanitize_query(query: str) -> str:
    """Replace smart/curly quotes and other problematic chars with ASCII equivalents."""
    replacements = {
        "\u201c": '"', "\u201d": '"',  # left/right double quotes → "
        "\u2018": "'", "\u2019": "'",  # left/right single quotes → '
        "\u2026": "...",               # ellipsis → ...
        "\u2013": "-", "\u2014": "-",  # en/em dash → -
    }
    for char, replacement in replacements.items():
        query = query.replace(char, replacement)
    return query.strip()

# Trusted domains allowlist
ALLOWLIST_DOMAINS = {
    "github.com", "gitlab.com", "readthedocs.io", "pypi.org", "npmjs.com",
    "developer.mozilla.org", "microsoft.com", "cloud.google.com", "aws.amazon.com",
    "medium.com", "towardsdatascience.com", "dev.to", "stackoverflow.com",
    "redis.io", "docker.com", "kubernetes.io", "postgresql.org", "mongodb.com",
    "react.dev", "nextjs.org", "vuejs.org", "angular.io", "python.org",
    "go.dev", "rust-lang.org", "oracle.com", "ibm.com", "linux.org",
    "geeksforgeeks.org", "freecodecamp.org", "w3schools.com"
}


class DuckDuckGoAdapter(IWebSearchProvider):
    """
    DuckDuckGo implementation of web search provider.

    Features:
    - No API key required
    - Region-aware search
    - Safe search support
    - Result filtering and scoring
    """

    def __init__(self):
        pass

    async def search(
        self,
        query: str,
        max_results: int = 10,
        region: str = "wt-wt",
        safe_search: str = "moderate"
    ) -> SearchResponse:
        """
        Perform a web search with timeout handling.

        Args:
            query: Search query
            max_results: Maximum number of results
            region: Region code (e.g., 'tr-tr', 'us-en')
            safe_search: Safe search level

        Returns:
            SearchResponse with results
        """
        started_at = time.perf_counter()
        error: Exception | None = None
        query = _sanitize_query(query)
        logger.info(f"Searching for: {query} (Region: {region})")

        def _perform_sync_search(search_query: str, search_region: str) -> list[dict[str, Any]]:
            """Helper to run search synchronously with timeout protection."""
            try:
                with DDGS() as ddgs:
                    # Use shorter timeout for DDGS internal operations
                    results = list(ddgs.text(
                        search_query,
                        region=search_region,
                        safesearch=safe_search,
                        max_results=max_results,
                    ))
                return results
            except Exception as e:
                logger.error(f"DDGS internal error for '{search_query}': {e}")
                return []

        async def _search_with_timeout(
            search_query: str, 
            search_region: str, 
            timeout: float = SEARCH_TIMEOUT_SECONDS
        ) -> list[dict[str, Any]]:
            """Run search with explicit timeout."""
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(_perform_sync_search, search_query, search_region),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"Search timeout for '{search_query}' after {timeout}s")
                return []
            except Exception as e:
                logger.error(f"Search error for '{search_query}': {e}")
                return []

        try:
            # Clean query: remove excessive negative filters that break DDGS
            clean_query = self._clean_query_for_search(query)
            
            # Primary search with timeout
            results = await _search_with_timeout(clean_query, region)
            search_results = self._filter_results(results, query)

            # Fallback 1: Try original query if cleaned query failed
            if len(search_results) == 0 and clean_query != query:
                logger.info(f"Clean query failed, retrying with original: '{query[:50]}...'")
                results = await _search_with_timeout(query, region, timeout=10)
                search_results = self._filter_results(results, query)

            # Fallback 2: Broader query (first 3-4 words)
            if len(search_results) == 0 and len(query.split()) > 3:
                words = query.split()
                broader_query = " ".join(words[:4])
                logger.info(f"0 results. Retrying with broader query: '{broader_query}'")
                results = await _search_with_timeout(broader_query, region, timeout=10)
                search_results = self._filter_results(results, broader_query)

            # Fallback 3: Global region if regional search failed
            if len(search_results) == 0 and region != "wt-wt":
                logger.info("Retrying in global region (wt-wt)...")
                results = await _search_with_timeout(clean_query, "wt-wt", timeout=10)
                search_results = self._filter_results(results, query)

            logger.info(f"Found {len(search_results)} results")

            return SearchResponse(
                query=query,
                results=search_results,
                total_results=len(search_results)
            )

        except Exception as e:
            error = e
            logger.error(f"Web search failed: {e}")
            return SearchResponse(query=query, results=[], total_results=0)
        finally:
            record_tool_invocation(
                tool="web_search",
                operation="duckduckgo_search",
                duration_seconds=time.perf_counter() - started_at,
                error=error,
            )

    def _clean_query_for_search(self, query: str) -> str:
        """Clean query by removing problematic negative filters for DuckDuckGo.
        
        DuckDuckGo doesn't handle multiple negative filters well and often
        returns no results when they're used extensively.
        """
        # Remove excessive negative filters that cause DDGS to return no results
        # Keep at most one negative filter if present
        negative_filters = ["-wordpress", "-blogspot", "-wix", "-squarespace"]
        words = query.split()
        
        # Count negative filters
        negative_count = sum(1 for w in words if w in negative_filters)
        
        if negative_count > 1:
            # Keep only the first negative filter, remove others
            cleaned_words = []
            kept_negative = False
            for word in words:
                if word in negative_filters:
                    if not kept_negative:
                        cleaned_words.append(word)
                        kept_negative = True
                    # Skip additional negative filters
                else:
                    cleaned_words.append(word)
            return " ".join(cleaned_words)
        
        return query

    def _filter_results(self, results: list, query: str) -> list[SearchResult]:
        """Filter and score search results."""
        excluded_domain_terms = ["baidu", "qq", "163", "casino", "bet", "porn", "xxx"]
        spam_terms = [
            "casino", "bet", "porn", "mp3", "torrent", "download free",
            "coupon", "discount", "sale", "crack", "hack", "warez"
        ]

        results_with_score = []

        for result in results:
            url = result.get("href", result.get("link", "")).lower()
            title = result.get("title", "").lower()
            snippet = result.get("body", result.get("snippet", "")).lower()

            # Filter spam domains
            if any(term in url for term in excluded_domain_terms):
                continue

            # Filter spam content
            if any(term in title or term in url for term in spam_terms):
                continue

            # Filter Chinese characters
            if any(u'\u4e00' <= c <= u'\u9fff' for c in result.get("title", "")):
                continue

            # Scoring - start with base score for passing spam filters
            score = 1.0

            # Allowlisted domains get bonus
            for domain in ALLOWLIST_DOMAINS:
                if domain in url:
                    score += 3
                    break

            # Keyword matches
            query_terms = query.lower().split()
            for term in query_terms:
                if len(term) > 3 and (term in title or term in snippet):
                    score += 1.0

            # Penalize short snippets (reduced penalties)
            if len(snippet) < 30:
                score -= 0.5
            elif len(snippet) < 50:
                score -= 0.25

            # Lower threshold from 2.0 to 1.0
            if score >= 1.0:
                results_with_score.append((score, result))

        # Sort by score descending
        results_with_score.sort(key=lambda x: x[0], reverse=True)

        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("href", r.get("link", "")),
                snippet=r.get("body", r.get("snippet", ""))
            )
            for _, r in results_with_score
        ]

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
        search_query = f"{claim} fact check verify"
        return await self.search(search_query, max_results=max_results)
