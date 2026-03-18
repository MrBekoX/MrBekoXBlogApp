from app.domain.interfaces.i_llm_provider import ILLMProvider
from typing import List
import asyncio
import logging
import re
import time

logger = logging.getLogger(__name__)

# Simple in-memory cache for query expansions (TTL-based)
_EXPANSION_CACHE: dict[str, tuple[List[str], float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


class QueryExpansionService:
    """
    Expands user queries using LLM-based generation to find related terms and synonyms.
    This provides a generalized "smart" solution (e.g., MySQL -> Database, SQL).

    Features:
    - LLM-based smart expansion with timeout
    - In-memory cache with TTL to avoid repeated LLM calls
    - Graceful fallback on timeout/error
    """

    def __init__(self, llm_provider: ILLMProvider, expand_timeout_seconds: int = 5):
        self._llm = llm_provider
        self._expand_timeout = expand_timeout_seconds
        self._initialized = False

    async def initialize(self):
        self._initialized = True

    async def expand_query(self, query: str) -> List[str]:
        """
        Generate variations of the query using LLM (Smart Expansion).

        Returns cached results when available, falls back gracefully on timeout.
        """
        if not self._initialized:
            await self.initialize()

        query_lower = query.lower().strip()

        # Check cache first
        cached = _EXPANSION_CACHE.get(query_lower)
        if cached:
            expansions, timestamp = cached
            if time.time() - timestamp < _CACHE_TTL_SECONDS:
                logger.debug(f"[QueryExpansion] Cache hit for '{query}'")
                return expansions
            else:
                # Expired, remove from cache
                del _EXPANSION_CACHE[query_lower]

        # 1. Start with original query
        variations = {query_lower}

        # 2. Use LLM for generation with timeout
        try:
            prompt = f"""You are a smart search assistant.
Generate 3 alternative, synonymous search queries for: "{query}"

Rules:
- Focus on technical synonyms (e.g., "slow" -> "latency", "bottleneck")
- Include related technologies if relevant (e.g., "Postgres" -> "Database", "SQL")
- DO NOT alter, translate, or expand specific code snippets, directives, or configuration values (e.g., "cache: 'no-store'", "GetRecentPostsAsync"). Keep them exactly as they are.
- Keep it short and precise.
- Output ONLY a comma-separated list.

Example:
Input: "connection timeout"
Output: "network error, latency issue, connectivity problem"

Output:"""

            started_at = time.perf_counter()
            try:
                expanded_text = await asyncio.wait_for(
                    self._llm.generate_text(prompt, temperature=0.1),
                    timeout=self._expand_timeout
                )
                duration = time.perf_counter() - started_at
                logger.debug(f"[QueryExpansion] LLM expansion took {duration:.3f}s")
            except asyncio.TimeoutError:
                logger.warning(
                    f"[QueryExpansion] Timeout after {self._expand_timeout}s for '{query}', "
                    "using original query only"
                )
                return [query_lower]

            # Parse results defensively: comma/newline/semicolon and numbered lists
            raw_candidates = re.split(r"[,\n;]+", expanded_text)
            generated = []
            for candidate in raw_candidates:
                normalized = re.sub(r"^\s*\d+[\).\-\s]*", "", candidate).strip().lower()
                if normalized:
                    generated.append(normalized)

            for g in generated:
                # Sadece baÅŸtaki ve sondaki tÄ±rnaklarÄ± sil, iÃ§erdeki teknik tÄ±rnaklara (Ã¶rn: 'no-store') dokunma
                clean_g = re.sub(r'\s+', ' ', g).strip(" .\"'")
                if clean_g and clean_g != query_lower and len(clean_g) > 2:
                    variations.add(clean_g)

            result = list(variations)
            logger.info(f"[QueryExpansion] '{query}' -> {result}")

            # Cache the result
            _EXPANSION_CACHE[query_lower] = (result, time.time())

            return result

        except Exception as e:
            logger.error(f"[QueryExpansion] Failed for '{query}': {type(e).__name__}: {e}")
            # Fallback to original query only
            return [query_lower]
