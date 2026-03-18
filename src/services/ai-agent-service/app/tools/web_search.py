"""Web search tool using DuckDuckGo."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

# Search configuration
DEFAULT_MAX_RESULTS = 10  # Increased for better coverage
DEFAULT_REGION = "wt-wt"  # Worldwide
SEARCH_TIMEOUT = 15  # seconds per search attempt


@dataclass
class WebSearchResult:
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
class WebSearchResponse:
    """Response from web search."""

    query: str
    results: list[WebSearchResult]
    total_results: int

    @property
    def has_results(self) -> bool:
        """Check if any results were found."""
        return len(self.results) > 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "total_results": self.total_results
        }


class WebSearchTool:
    """
    Web search tool using DuckDuckGo (Async).

    Features:
    - No API key required
    - Region-aware search
    - Safe search support
    - Async implementation
    """

    def __init__(self):
        pass

    async def search(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        region: str = DEFAULT_REGION,
        safe_search: str = "moderate"
    ) -> WebSearchResponse:
        """
        Perform a web search asynchronously using synchronous DDGS client in a thread.

        Args:
            query: Search query
            max_results: Maximum number of results to return
            region: Region code (e.g., 'tr-tr' for Turkey, 'us-en' for US)
            safe_search: Safe search level ('off', 'moderate', 'strict')

        Returns:
            WebSearchResponse with search results
        """
        logger.info(f"Searching for: {query} (Region: {region})")
        from duckduckgo_search import DDGS
        import asyncio

        # Helper function for searching (parameterized)
        def _perform_sync_search(search_query: str, search_region: str):
            """Helper to run search synchronously."""
            try:
                # Use DDGS context manager (removed backend parameter which may cause issues)
                with DDGS() as ddgs:
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
        
        # Clean query: remove excessive negative filters that break DDGS
        def _clean_query(search_query: str) -> str:
            """Remove excessive negative filters that cause DDGS to return no results."""
            negative_filters = ["-wordpress", "-blogspot", "-wix", "-squarespace"]
            words = search_query.split()
            negative_count = sum(1 for w in words if w in negative_filters)
            
            if negative_count > 1:
                cleaned_words = []
                kept_negative = False
                for word in words:
                    if word in negative_filters:
                        if not kept_negative:
                            cleaned_words.append(word)
                            kept_negative = True
                    else:
                        cleaned_words.append(word)
                return " ".join(cleaned_words)
            return search_query

        # Trusted domains allowlist
        ALLOWLIST_DOMAINS = {
            "github.com", "gitlab.com", "readthedocs.io", "pypi.org", "npmjs.com",
            "developer.mozilla.org", "microsoft.com", "cloud.google.com", "aws.amazon.com",
            "medium.com", "towardsdatascience.com", "dev.to", "stackoverflow.com",
            "redis.io", "docker.com", "kubernetes.io", "postgresql.org", "mongodb.com",
            "react.dev", "nextjs.org", "vuejs.org", "angular.io", "python.org",
            "go.dev", "rust-lang.org", "oracle.com", "ibm.com", "linux.org",
            "geeksforgeeks.org", "freecodecamp.org", "w3schools.com"  # Added popular learning sites
        }

        # Filtering logic - Enhanced with scoring and better spam detection
        def _filter_results(results):
            filtered = []
            
            # Spam and irrelevant terms
            excluded_domain_terms = ["baidu", "qq", "163", "casino", "bet", "porn", "xxx"]
            spam_terms_in_url_or_title = [
                "casino", "bet", "porn", "mp3", "torrent", "download free", 
                "coupon", "discount", "sale", "crack", "hack", "warez"
            ]

            results_with_score = []

            for result in results:
                url = result.get("href", result.get("link", "")).lower()
                title = result.get("title", "").lower()
                snippet = result.get("body", result.get("snippet", "")).lower()

                # 1. Critical Filters (Pass/Fail)
                
                # Filter spam domains
                if any(term in url for term in excluded_domain_terms):
                    continue

                # Filter spam content in title or URL
                if any(term in title or term in url for term in spam_terms_in_url_or_title):
                    continue

                # Filter Chinese characters in title (keeps results clean for this context)
                if any(u'\u4e00' <= c <= u'\u9fff' for c in result.get("title", "")):
                    continue

                # 2. Scoring System
                score = 0
                
                # Check for allowlisted domains
                domain_match = False
                for domain in ALLOWLIST_DOMAINS:
                    if domain in url:
                        score += 3
                        domain_match = True
                        break
                
                # Keyword matches
                query_terms = query.lower().split()
                matches = 0
                for term in query_terms:
                    # Only count significant words
                    if len(term) > 3 and (term in title or term in snippet):
                        matches += 1
                
                score += matches * 1.0  # Increased from 0.5 to 1.0

                # Penalize very short snippets
                if len(snippet) < 50:
                    score -= 1

                # 3. Threshold Check
                # Stricter threshold: Must have at least 2 points.
                # This means either:
                # - Allowlisted domain (3 points) -> Pass
                # - Unknown domain with at least 2 relevant keywords -> Pass
                # - Unknown domain with 1 keyword -> Fail (Score 1 < 2)
                
                if score >= 2.0:
                     results_with_score.append((score, result))

            # Sort by score descending
            results_with_score.sort(key=lambda x: x[0], reverse=True)

            # Return just the result objects
            for score, result_data in results_with_score:
                 filtered.append(WebSearchResult(
                    title=result_data.get("title", ""),
                    url=result_data.get("href", result_data.get("link", "")),
                    snippet=result_data.get("body", result_data.get("snippet", ""))
                ))

            return filtered

        try:
            # Clean query before searching
            clean_query = _clean_query(query)
            
            # 1. Primary Search with timeout
            results = await asyncio.wait_for(
                asyncio.to_thread(_perform_sync_search, clean_query, region),
                timeout=SEARCH_TIMEOUT
            )
            search_results = _filter_results(results)

            # 2. Fallback: Try original query if cleaned query failed
            if len(search_results) == 0 and clean_query != query:
                logger.info(f"Clean query failed, trying original: '{query[:50]}...'")
                results = await asyncio.wait_for(
                    asyncio.to_thread(_perform_sync_search, query, region),
                    timeout=SEARCH_TIMEOUT
                )
                search_results = _filter_results(results)

            # 3. Fallback: Broader Query (if 0 results)
            if len(search_results) == 0 and len(query.split()) > 3:
                words = query.split()
                broader_query = " ".join(words[:4])  # Use first 4 words
                logger.info(f"0 results. Retrying with broader query: '{broader_query}'...")
                
                results = await asyncio.wait_for(
                    asyncio.to_thread(_perform_sync_search, broader_query, region),
                    timeout=SEARCH_TIMEOUT
                )
                search_results = _filter_results(results)

            # 4. Fallback: Global Region (if still 0 results and region was not global)
            if len(search_results) == 0 and region != "wt-wt":
                logger.info("Retrying in global region (wt-wt)...")
                results = await asyncio.wait_for(
                    asyncio.to_thread(_perform_sync_search, clean_query, "wt-wt"),
                    timeout=SEARCH_TIMEOUT
                )
                search_results = _filter_results(results)

            logger.info(f"Found {len(search_results)} results total (after fallbacks)")

            return WebSearchResponse(
                query=query,
                results=search_results,
                total_results=len(search_results)
            )

        except asyncio.TimeoutError:
            logger.warning(f"Web search timed out after {SEARCH_TIMEOUT}s for '{query[:50]}...'")
            return WebSearchResponse(query=query, results=[], total_results=0)
        except Exception as e:
            logger.error(f"Web search failed for '{query}': {e}")
            return WebSearchResponse(
                query=query,
                results=[],
                total_results=0
            )

    async def search_for_article(
        self,
        article_title: str,
        question: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        language: str = "tr"
    ) -> WebSearchResponse:
        """
        Search for information related to an article and a question.

        Constructs an optimized search query combining the article context
        and the user's question.

        Args:
            article_title: Title of the article for context
            question: User's question
            max_results: Maximum number of results
            language: Language code for region targeting

        Returns:
            WebSearchResponse with search results
        """
        # Determine region based on language
        region = "tr-tr" if language.lower() == "tr" else "wt-wt"
        if language.lower() == "en":
            region = "us-en"

        # Construct search query
        # Always include article title for context to ensure relevant results
        # Cleaner query construction
        search_query = f"{article_title} {question}"
        
        # Log the constructed query
        logger.info(f"Constructed search query: '{search_query}' (Region: {region})")

        return await self.search(search_query, max_results=max_results, region=region)

    async def search_for_verification(
        self,
        claim: str,
        max_results: int = 3
    ) -> WebSearchResponse:
        """
        Search to verify a claim from an article.

        Adds verification-focused keywords to the search.

        Args:
            claim: The claim to verify
            max_results: Maximum number of results

        Returns:
            WebSearchResponse with verification sources
        """
        # Add fact-checking context
        search_query = f"{claim} fact check verify"
        return await self.search(search_query, max_results=max_results)


# Singleton instance for backward compatibility
web_search_tool = WebSearchTool()

