"""DuckDuckGo search adapter - Concrete implementation of IWebSearchProvider."""

import asyncio
import logging

from duckduckgo_search import DDGS

from app.domain.interfaces.i_web_search import (
    IWebSearchProvider,
    SearchResult,
    SearchResponse,
)

logger = logging.getLogger(__name__)

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
        Perform a web search.

        Args:
            query: Search query
            max_results: Maximum number of results
            region: Region code (e.g., 'tr-tr', 'us-en')
            safe_search: Safe search level

        Returns:
            SearchResponse with results
        """
        logger.info(f"Searching for: {query} (Region: {region})")

        def _perform_sync_search(search_query: str, search_region: str):
            """Helper to run search synchronously."""
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(
                        search_query,
                        region=search_region,
                        safesearch=safe_search,
                        max_results=max_results,
                        backend="duckduckgo"
                    ))
                return results
            except Exception as e:
                logger.error(f"DDGS internal error for '{search_query}': {e}")
                return []

        try:
            # Primary search
            results = await asyncio.to_thread(_perform_sync_search, query, region)
            search_results = self._filter_results(results, query)

            # Fallback: Broader query if 0 results
            if len(search_results) == 0 and len(query.split()) > 3:
                words = query.split()
                broader_query = " ".join(words[:3])
                logger.info(f"0 results. Retrying with: '{broader_query}'")
                results = await asyncio.to_thread(_perform_sync_search, broader_query, region)
                search_results = self._filter_results(results, query)

            # Fallback: Global region if still 0 results
            if len(search_results) == 0 and region == "tr-tr":
                logger.info("Still 0 results. Retrying in global region...")
                results = await asyncio.to_thread(_perform_sync_search, query, "wt-wt")
                search_results = self._filter_results(results, query)

            logger.info(f"Found {len(search_results)} results")

            return SearchResponse(
                query=query,
                results=search_results,
                total_results=len(search_results)
            )

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return SearchResponse(query=query, results=[], total_results=0)

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

            # Scoring
            score = 0

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

            # Penalize short snippets
            if len(snippet) < 50:
                score -= 1

            # Threshold check
            if score >= 2.0:
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
