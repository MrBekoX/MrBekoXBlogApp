from app.domain.interfaces.i_llm_provider import ILLMProvider
from typing import List
import logging

logger = logging.getLogger(__name__)

class QueryExpansionService:
    """
    Expands user queries using LLM-based generation to find related terms and synonyms.
    This provides a generalized "smart" solution (e.g., MySQL -> Database, SQL).
    """

    def __init__(self, llm_provider: ILLMProvider):
        self._llm = llm_provider
        self._initialized = False

    async def initialize(self):
        self._initialized = True

    async def expand_query(self, query: str) -> List[str]:
        """
        Generate variations of the query using LLM (Smart Expansion).
        """
        # 1. Start with original query
        variations = {query.lower()}

        # 2. Use LLM for generation
        try:
            prompt = f"""
            You are a smart search assistant.
            Generate 3 alternative, synonymous search queries for: "{query}"
            
            Rules:
            - Focus on technical synonyms (e.g., "slow" -> "latency", "bottleneck")
            - Include related technologies if relevant (e.g., "Postgres" -> "Database", "SQL")
            - Keep it short and precise.
            - Output ONLY a comma-separated list.
            
            Example: 
            Input: "connection timeout"
            Output: "network error, latency issue, connectivity problem"
            """
            
            # Helper: Use a low temperature for consistency if supported by provider
            expanded_text = await self._llm.generate_response(prompt)
            
            # Parse results
            generated = [s.strip().lower() for s in expanded_text.split(',') if s.strip()]
            
            for g in generated:
                clean_g = g.replace('"', '').replace("'", "").replace(".", "")
                if clean_g and clean_g != query.lower():
                    variations.add(clean_g)
                    
            logger.info(f"Smart Expansion: '{query}' -> {list(variations)}")
            
        except Exception as e:
            logger.error(f"Smart Query Expansion failed: {e}")
            # Fallback to original query only implies no expansion
            
        return list(variations)
