"""Chat service - RAG-powered article Q&A."""

import asyncio
import logging
import re
from collections import Counter
from typing import Any, Set, AsyncGenerator

from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.domain.interfaces.i_web_search import IWebSearchProvider
from app.domain.entities.chat import ChatMessage, ChatResponse
from app.services.rag_service import RagService
from app.services.analysis_service import AnalysisService
from app.security.content_guardrails import ContentGuardrails
from app.monitoring.anomaly_detector import AnomalyDetector

logger = logging.getLogger(__name__)

# Chat prompts
RAG_SYSTEM_PROMPT_TR = """Sen profesyonel bir teknik blog asistanısın.
Aşağıdaki makale bölümlerini kullanarak kullanıcının sorusunu cevapla.

TEMEL PRENSİPLER:
- KONU BAĞLILIĞI: SADECE makalede geçen konularla ilgili konuş. Alakasız konuları (Örn: Spor, Siyaset) reddet.
- GERÇEKÇİLİK: Makalede olmayan bir *bilgiyi* uydurma.
- KOD ÜRETİMİ: Kullanıcı AÇIKÇA kod istemedikçe KESİNLİKLE kod bloğu yazma.

SORU TİPLERİNE GÖRE DAVRANIŞ:

1. 🧠 BİLGİ/AÇIKLAMA SORULARI (Örn: "X nedir?", "Neden Y kullanılır?", "Özetle"):
   - SADECE verilen metindeki bilgileri kullan.
   - Dışarıdan bilgi katma.
   - Asla kendi kendine kod örneği ekleme.

2. 💻 KOD/UYGULAMA SORULARI (Örn: "Örnek kod ver", "Nasıl implamente edilir?"):
   - BU ALANDA YARATICI OL.
   - Makalede kod olmasa bile, anlatılan KAVRAMLARI (Örn: Redis Cache, Decorator) al.
   - Kendi teknik uzmanlığını kullanarak bu kavramlar için çalışan, kaliteli ÖRNEK KODLAR üret.
   - Kural: Ürettiğin kod makaledeki konuyu örneklendirmeli.

MAKALE BÖLÜMLERİ:
{context}"""

RAG_SYSTEM_PROMPT_EN = """You are a professional technical blog assistant.
Use the article sections below to answer the user's question.

CORE PRINCIPLES:
- TOPIC RELEVANCE: Speak ONLY about topics discussed in the article. Reject unrelated topics.
- FACTUALITY: Do not invent *information* not present in the article.
- CODE GENERATION: NEVER generate code blocks unless ensuring the user EXPLICITLY asked for code.

BEHAVIOR BY QUESTION TYPE:

1. 🧠 FACT/EXPLANATION QUESTIONS (e.g., "What is X?", "Summarize"):
   - Use ONLY information from the provided text.
   - Do NOT add outside information.
   - Do NOT volunteer code examples.

2. 💻 CODE/IMPLEMENTATION QUESTIONS (e.g., "Give example code", "How to implement?"):
   - BE CREATIVE IN THIS AREA.
   - Even if there is no code in the article, take the CONCEPTS (e.g., Redis Cache, Decorator) discussed.
   - Use your own technical expertise to generate working, high-quality EXAMPLE CODE for these concepts.
   - Rule: The code you produce must exemplify the topic in the article.

ARTICLE SECTIONS:
{context}"""


class ChatService:
    """
    Service for RAG-powered chat functionality.

    Single Responsibility: Article Q&A with RAG and optional web search.
    """

    def __init__(
        self,
        llm_provider: ILLMProvider,
        rag_service: RagService,
        web_search_provider: IWebSearchProvider | None = None,
        analysis_service: AnalysisService | None = None,
        anomaly_detector: AnomalyDetector | None = None
    ):
        self._llm = llm_provider
        self._rag = rag_service
        self._web_search = web_search_provider
        self._analysis = analysis_service
        self._guardrails = ContentGuardrails()
        self._anomaly_detector = anomaly_detector

    @staticmethod
    def _extract_keywords(text: str, max_words: int = 5, min_len: int = 4) -> list[str]:
        """
        Extract meaningful keywords from text using frequency-based filtering.

        Language-agnostic: short words (articles, prepositions, conjunctions) and
        overly common words are filtered out automatically — no hardcoded stopword list.
        """
        clean = re.sub(r'[^\w\s]', ' ', text)
        words = [w for w in clean.lower().split() if len(w) >= min_len and w.isalpha()]

        if not words:
            return []

        freq = Counter(words)

        # Words appearing too frequently are likely functional/stop words
        # (e.g. "this", "olan", "with" repeat heavily in natural text)
        high_freq_threshold = max(len(words) * 0.05, 3)
        candidates = [
            w for w, count in freq.most_common()
            if count <= high_freq_threshold
        ]

        # Among remaining candidates, prefer mid-frequency words (not too rare, not too common)
        # Sort by frequency descending — most repeated technical terms rise to the top
        candidate_freq = {w: freq[w] for w in candidates}
        sorted_candidates = sorted(candidate_freq, key=candidate_freq.get, reverse=True)

        return sorted_candidates[:max_words]

    async def chat(
        self,
        post_id: str,
        user_message: str,
        auth_context: Any,
        conversation_history: list[ChatMessage] | None = None,
        language: str = "tr",
        k: int = 5
    ) -> ChatResponse:
        """
        Process a chat message using RAG.

        Args:
            post_id: Article ID to search within
            user_message: User's question
            auth_context: Authorization context for access control
            conversation_history: Previous messages
            language: Response language
            k: Number of chunks to retrieve

        Returns:
            ChatResponse with the generated answer
        """
        logger.info(f"Processing chat for post {post_id}: {user_message[:50]}...")

        # Boundary check: Greeting detection (fast, reliable)
        if self._is_greeting(user_message):
            logger.info(f"Greeting detected, returning out-of-scope response")
            return ChatResponse(
                response=self._get_greeting_response(language),
                sources_used=0,
                is_rag_response=False
            )

        # Retrieve relevant chunks
        result = await self._rag.retrieve_with_context(
            query=user_message,
            post_id=post_id,
            k=k
        )

        # Boundary check 1: No relevant content found
        if not result.has_results or not result.context.strip():
            logger.info(f"No relevant chunks found for post {post_id}")
            return ChatResponse(
                response=self._get_out_of_scope_response(language),
                sources_used=0,
                is_rag_response=False
            )

        # Boundary check 2: Multi-signal relevance validation
        # Based on research: ELOQ, Semantic Boundary Detection, AI Guardrails
        # Uses LLM as primary gatekeeper to prevent hallucination on unrelated topics
        is_relevant, rejection_reason = await self._check_relevance_multi_signal(
            user_message=user_message,
            context=result.context,
            similarity_score=result.average_similarity,
            language=language
        )

        if not is_relevant:
            logger.warning(
                f"Query '{user_message[:30]}...' rejected: {rejection_reason} "
                f"(similarity={result.average_similarity:.3f}, chunks={len(result.chunks)})"
            )
            return ChatResponse(
                response=self._get_out_of_scope_response(language),
                sources_used=0,
                is_rag_response=False
            )

        # Log successful relevance check
        logger.info(
            f"Query '{user_message[:30]}...' passed relevance check "
            f"(similarity={result.average_similarity:.3f}, chunks={len(result.chunks)})"
        )

        # Build prompt
        system_prompt = RAG_SYSTEM_PROMPT_TR if language == "tr" else RAG_SYSTEM_PROMPT_EN

        # Build conversation
        messages_text = ""
        if conversation_history:
            for msg in conversation_history[-4:]:
                messages_text += f"{msg.role}: {msg.content}\n"
        messages_text += f"user: {user_message}"

        prompt = f"""{system_prompt.format(context=result.context)}

{messages_text}

assistant:"""

        # Generate response with timeout to prevent infinite hangs
        try:
            response = await asyncio.wait_for(
                self._llm.generate_text(prompt),
                timeout=120,  # 2 minute timeout
            )
        except asyncio.TimeoutError:
            logger.warning("[chat] LLM timed out after 120s, returning out-of-scope response")
            return ChatResponse(
                response=self._get_out_of_scope_response(language),
                sources_used=0,
                is_rag_response=False,
            )

        # Apply content guardrails to LLM response
        guardrail_result = self._guardrails.check_response(response, original_query=user_message)
        if not guardrail_result.is_safe:
            logger.warning(f"Response blocked by guardrails: {guardrail_result.violations}")
            response = guardrail_result.sanitized_response or self._get_out_of_scope_response(language)

        # Record request for anomaly detection
        if self._anomaly_detector:
            user_id = getattr(auth_context, "subject_id", "anonymous") if auth_context else "anonymous"
            await self._anomaly_detector.record_request(
                user_id=user_id,
                success=True,
                token_count=len(response.split()),
                ip_address=getattr(auth_context, "fingerprint", None)
            )

        return ChatResponse(
            response=response.strip(),
            sources_used=0,
            is_rag_response=True,
            context_preview=result.context[:200]
        )

    async def chat_stream(
        self,
        post_id: str,
        user_message: str,
        conversation_history: list[ChatMessage] | None = None,
        language: str = "tr",
        k: int = 5
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat response token by token.
        """
        logger.info(f"Processing chat stream for post {post_id}...")

        # Greeting check
        if self._is_greeting(user_message):
            yield self._get_greeting_response(language)
            return

        # RAG Retrieval
        result = await self._rag.retrieve_with_context(
            query=user_message,
            post_id=post_id,
            k=k
        )

        # No results check
        if not result.has_results or not result.context.strip():
            yield self._get_out_of_scope_response(language)
            return

        # Relevance check (simplied for stream to avoid double latency, or keep same)
        # For streaming, we might want to start streaming faster, but relevance check is critical.
        # We'll keep the check.
        is_relevant, rejection_reason = await self._check_relevance_multi_signal(
            user_message=user_message,
            context=result.context,
            similarity_score=result.average_similarity,
            language=language
        )

        if not is_relevant:
            logger.warning(f"Stream query rejected: {rejection_reason}")
            yield self._get_out_of_scope_response(language)
            return

        # Build Prompt
        system_prompt = RAG_SYSTEM_PROMPT_TR if language == "tr" else RAG_SYSTEM_PROMPT_EN
        
        messages_text = ""
        if conversation_history:
            for msg in conversation_history[-4:]:
                messages_text += f"{msg.role}: {msg.content}\n"
        messages_text += f"user: {user_message}"

        prompt = f"""{system_prompt.format(context=result.context)}

{messages_text}

assistant:"""

        # Stream from LLM
        async for chunk in self._llm.generate_stream(prompt):
            yield chunk

    async def chat_with_web_search(
        self,
        post_id: str,
        user_message: str,
        article_title: str,
        auth_context: Any,
        article_content: str = "",
        language: str = "tr"
    ) -> ChatResponse:
        """
        Process chat with hybrid RAG + web search.

        Args:
            post_id: Article ID
            user_message: User's question
            article_title: Article title
            auth_context: Authorization context for access control
            article_content: Article content for keyword extraction
            language: Response language

        Returns:
            ChatResponse with web search results
        """
        if not self._web_search:
            return await self.chat(post_id, user_message, auth_context, language=language)

        logger.info(f"Processing hybrid search for: {user_message[:50]}...")

        # Start RAG retrieval immediately — does not depend on the search query
        rag_task = asyncio.create_task(
            self._rag.retrieve_with_context(query=user_message, post_id=post_id, k=5)
        )

        # Generate search query with hard timeout (LLM can be very slow on low VRAM)
        try:
            search_query = await asyncio.wait_for(
                self._generate_search_query(article_title, user_message, article_content, language),
                timeout=15,
            )
        except asyncio.TimeoutError:
            logger.warning("Search query generation timed out, falling back to keyword extraction")
            search_query = self._keyword_query(article_title, user_message)

        # Determine region
        region = "tr-tr" if language.lower() == "tr" else "us-en"

        # Web search with timeout protection (RAG is already running in the background)
        try:
            web_result = await asyncio.wait_for(
                self._web_search.search(query=search_query, max_results=10, region=region),
                timeout=30  # 30 second timeout for web search
            )
        except asyncio.TimeoutError:
            logger.warning("Web search timed out after 30s, falling back to RAG only")
            web_result = None
        except Exception as e:
            logger.error(f"Web search failed: {e}, falling back to RAG only")
            web_result = None
        
        rag_result = await rag_task  # likely already done by now

        if not web_result or not web_result.has_results:
            logger.warning("Web search yielded no results or failed, using RAG only")
            # Reuse the already-retrieved rag_result — avoids a duplicate RAG + LLM round-trip
            return await self._respond_from_rag(user_message, rag_result, auth_context, language)

        logger.info(f"[chat_with_web_search] Web search successful with {len(web_result.results)} results, building hybrid prompt...")

        # Format web results — top 3 only, snippets capped at 250 chars each
        # (keeps the hybrid prompt under ~4000 chars so the LLM finishes in time)
        # Strip URLs from snippets to prevent small LLMs from hallucinating more URLs
        web_context = "\n\n".join([
            re.sub(r'https?://\S+', '', r.snippet[:250]).strip()
            for r in web_result.results[:3]
        ])

        # Cap RAG context to keep total prompt manageable on low-VRAM hardware
        rag_context_for_prompt = rag_result.context[:3000]

        # Build hybrid prompt
        # IMPORTANT: Instructions go BEFORE context to prevent small LLMs (phi4-mini)
        # from echoing them as part of the answer (prompt leakage).
        # The prompt ends with "CEVAP:" so the model generates the answer directly.
        if language == "tr":
            prompt = f"""Sen "{article_title}" hakkında sorulara cevap veren bir asistansın.
Cevabını makale bağlamı ve web arama sonuçlarını kullanarak yaz.
Link, URL veya kaynak listesi ekleme. "[1]", "https://" gibi kaynak belirtileri kullanma.
Kod sorusu sorulursa kısa ve anlaşılır örnek kod yaz.

MAKALE BAGLAMI:
{rag_context_for_prompt}

WEB ARAMA SONUCLARI:
{web_context}

SORU: {user_message}

CEVAP:"""
        else:
            prompt = f"""You are an assistant answering questions about "{article_title}".
Use the article context and web search results to write your answer.
Do not include links, URLs, or source lists. Do not use citations like [1] or "https://".
If asked for code, write short and clear example code.

ARTICLE CONTEXT:
{rag_context_for_prompt}

WEB SEARCH RESULTS:
{web_context}

QUESTION: {user_message}

ANSWER:"""

        logger.info(f"[chat_with_web_search] Calling LLM with prompt length {len(prompt)} chars...")
        
        try:
            response = await asyncio.wait_for(
                self._llm.generate_text(prompt),
                timeout=120,
            )
            logger.info(f"[chat_with_web_search] LLM response received, length: {len(response)} chars")
        except asyncio.TimeoutError:
            logger.warning("[chat_with_web_search] LLM timed out after 120s, falling back to RAG only")
            return await self._respond_from_rag(user_message, rag_result, auth_context, language)

        # Strip any URLs the LLM hallucinated despite instructions
        original_len = len(response)
        response = self._strip_hallucinated_urls(response)
        stripped_len = len(response)

        # If >30% of the response was URLs, the LLM likely hallucinated heavily — fall back to RAG
        if original_len > 0 and (original_len - stripped_len) / original_len > 0.30:
            logger.warning(
                f"[chat_with_web_search] {original_len - stripped_len}/{original_len} chars were "
                f"hallucinated URLs ({(original_len - stripped_len) / original_len:.0%}), falling back to RAG"
            )
            return await self._respond_from_rag(user_message, rag_result, auth_context, language)

        # Apply content guardrails to web search response
        guardrail_result = self._guardrails.check_response(response, original_query=user_message)
        if not guardrail_result.is_safe:
            logger.warning(f"Web search response blocked by guardrails: {guardrail_result.violations}")
            response = guardrail_result.sanitized_response or self._get_out_of_scope_response(language)

        # Record request for anomaly detection
        if self._anomaly_detector:
            user_id = getattr(auth_context, "subject_id", "anonymous") if auth_context else "anonymous"
            await self._anomaly_detector.record_request(
                user_id=user_id,
                success=True,
                token_count=len(response.split()),
                ip_address=getattr(auth_context, "fingerprint", None)
            )

        logger.info(f"[chat_with_web_search] Returning hybrid response with {len(web_result.results)} sources")
        
        return ChatResponse(
            response=response.strip(),
            sources_used=len(web_result.results),
            is_rag_response=False,
            sources=[r.to_dict() for r in web_result.results]
        )

    @staticmethod
    def _strip_hallucinated_urls(text: str) -> str:
        """Remove URLs and markdown links that small LLMs hallucinate despite instructions."""
        # Remove markdown links: [text](url) → text
        text = re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)', r'\1', text)
        # Remove bare URLs
        text = re.sub(r'https?://\S+', '', text)
        # Clean up leftover empty lines from removed URLs
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        return text.strip()

    def _keyword_query(self, article_title: str, user_message: str) -> str:
        """Sync keyword-based query (used when LLM search-query generation times out)."""
        title_keywords = self._extract_keywords(article_title, max_words=4, min_len=3)
        question_keywords = self._extract_keywords(user_message, max_words=2, min_len=3)
        query = " ".join(title_keywords)
        if question_keywords:
            query += " " + " ".join(question_keywords)
        return query + " -wordpress -blogspot"

    async def _respond_from_rag(
        self,
        user_message: str,
        rag_result: Any,
        auth_context: Any,
        language: str,
    ) -> "ChatResponse":
        """Build a chat response from a pre-retrieved RAG result (skips re-retrieval)."""
        if not rag_result.has_results or not rag_result.context.strip():
            return ChatResponse(
                response=self._get_out_of_scope_response(language),
                sources_used=0,
                is_rag_response=False,
            )

        is_relevant, rejection_reason = await self._check_relevance_multi_signal(
            user_message=user_message,
            context=rag_result.context,
            similarity_score=rag_result.average_similarity,
            language=language,
        )
        if not is_relevant:
            logger.warning(f"Query '{user_message[:30]}...' rejected: {rejection_reason}")
            return ChatResponse(
                response=self._get_out_of_scope_response(language),
                sources_used=0,
                is_rag_response=False,
            )

        logger.info(
            f"Query '{user_message[:30]}...' passed relevance check "
            f"(similarity={rag_result.average_similarity:.3f}, chunks={len(rag_result.chunks)})"
        )

        system_prompt = RAG_SYSTEM_PROMPT_TR if language == "tr" else RAG_SYSTEM_PROMPT_EN
        prompt = f"""{system_prompt.format(context=rag_result.context)}

user: {user_message}

A:"""
        
        # Add timeout for LLM generation to prevent infinite hangs
        try:
            response = await asyncio.wait_for(
                self._llm.generate_text(prompt),
                timeout=120,  # 2 minute timeout
            )
        except asyncio.TimeoutError:
            logger.warning("[_respond_from_rag] LLM timed out after 120s, returning out-of-scope response")
            return ChatResponse(
                response=self._get_out_of_scope_response(language),
                sources_used=0,
                is_rag_response=False,
            )

        guardrail_result = self._guardrails.check_response(response, original_query=user_message)
        if not guardrail_result.is_safe:
            response = guardrail_result.sanitized_response or self._get_out_of_scope_response(language)

        if self._anomaly_detector:
            user_id = getattr(auth_context, "subject_id", "anonymous") if auth_context else "anonymous"
            await self._anomaly_detector.record_request(
                user_id=user_id,
                success=True,
                token_count=len(response.split()),
                ip_address=getattr(auth_context, "fingerprint", None),
            )

        return ChatResponse(
            response=response.strip(),
            sources_used=0,
            is_rag_response=True,
            context_preview=rag_result.context[:200],
        )

    async def _generate_search_query(
        self,
        article_title: str,
        user_question: str,
        article_content: str,
        language: str
    ) -> str:
        """Generate optimized search query using LLM for better relevance."""

        # 1. Use LLM to analyze intent and generate query (universal approach)
        content_preview = article_content[:500] if article_content else ""

        prompt = f"""Analyze the user's question about the article and generate an optimized search query.

Article Title: {article_title}
Article Content Preview: {content_preview}
User Question: {user_question}

Task:
1. Determine if this is a general question about the article (asking for overview/summary/explanation) OR a specific technical question
2. Generate a 3-5 word technical search query accordingly

For general questions (what is this about, summarize, explain, detail):
- Extract the PRIMARY technical topic from the article title AND content
- Include the most specific technical terms from the article (e.g. "dependency inversion", "hexagonal architecture")
- Add resource type: tutorial OR guide OR examples OR best practices
- IMPORTANT: Use the article content to make the query more specific, not just the title

For specific technical questions (how does X work, error with Y, comparison):
- Combine the article topic with the specific technical keywords from the question
- Focus on the exact problem or concept being asked

Output only the search query text, lowercase, no additional formatting or explanation."""

        try:
            query = await self._llm.generate_text(prompt)
            query = query.strip().lower()

            # Clean up LLM output
            query = re.sub(r'["\'`]', '', query)
            query = re.sub(r'\s+', ' ', query)

            # Add negative filters to avoid low-quality content (only for non-technical queries)
            # Note: DuckDuckGo doesn't always handle negative filters well, use sparingly
            if len(query.split()) > 2:
                query += " -wordpress -blogspot"

            logger.info(f"LLM-generated query: {query}")
            return query

        except Exception as e:
            logger.warning(f"LLM query generation failed: {e}, falling back to keyword extraction")

        # 2. Fallback: Keyword extraction from title + content (language-agnostic)
        title_keywords = self._extract_keywords(article_title, max_words=3, min_len=3)
        content_keywords = self._extract_keywords(article_content[:1000], max_words=3, min_len=5) if article_content else []
        question_keywords = self._extract_keywords(user_question, max_words=2, min_len=3)

        query = " ".join(title_keywords)
        if content_keywords:
            # Avoid duplicating title keywords
            extra = [w for w in content_keywords if w not in title_keywords][:2]
            if extra:
                query += " " + " ".join(extra)
        if question_keywords:
            query += " " + " ".join(question_keywords[:1])

        # Add minimal negative filters for keyword-based queries
        if len(query.split()) > 2:
            query += " -wordpress"

        logger.info(f"Keyword-based query: {query}")
        return query

    async def collect_sources(
        self,
        post_id: str,
        article_title: str,
        article_content: str,
        user_question: str,
        language: str = "tr",
        max_results: int = 10
    ) -> list[dict]:
        """Collect web sources for an article question."""
        if not self._web_search:
            return []

        query = await self._generate_search_query(
            article_title, user_question, article_content, language
        )

        region = "tr-tr" if language.lower() == "tr" else "us-en"
        response = await self._web_search.search(query, max_results, region)

        return [r.to_dict() for r in response.results]

    async def _check_relevance_multi_signal(
        self,
        user_message: str,
        context: str,
        similarity_score: float,
        language: str
    ) -> tuple[bool, str]:
        """
        Multi-signal relevance validation based on research from ELOQ, Semantic Boundary Detection, AI Guardrails.

        Combines multiple signals:
        1. Similarity score (hard filter for very low scores)
        2. LLM semantic relevance (primary gatekeeper)
        3. Context quality check

        Returns:
            (is_relevant, rejection_reason) - reason explains why query was rejected (for logging)
        """
        # Signal 0: Meta-question detection (Bypass)
        if self._is_meta_question(user_message):
            logger.info(f"Meta-question detected, bypassing validations: '{user_message}'")
            return True, "meta_question_bypass"

        # Signal 1: Very low similarity hard filter
        # Adjusted from 0.15 back to 0.30 to match RAG retrieval threshold and avoid noise
        if similarity_score < 0.30:
            return False, f"very_low_similarity_{similarity_score:.3f}"

        # Signal 2: LLM semantic relevance check (primary gatekeeper)
        # Runs for ALL queries regardless of similarity score
        # This is the key to preventing hallucination on unrelated topics like "Galatasaray"
        is_semantically_relevant = await self._check_query_relevance(
            user_message, context, language
        )

        if not is_semantically_relevant:
            return False, f"llm_relevance_check_failed"

        # Signal 3: Context quality check
        # Ensure we have meaningful context to work with
        if len(context.strip()) < 50:
            return False, "insufficient_context_length"

        return True, "passed_all_checks"

    def _is_meta_question(self, message: str) -> bool:
        """
        Detect if question is ABOUT the article itself (meta-questions).
        These should always be allowed.
        """
        message_lower = message.lower().strip()
        
        meta_patterns = [
            "makalede ne anlat",
            "makalede ne var",
            "makalede neler",
            "makaleyi özet",
            "anlatılanlar",
            "makale hakkında",
            "bu makale",
            "içeriği nedir",
            "içerik nedir",
            "konu nedir",
            "anlatılmaktadır",
            "makalenin konusu",
            "what is this article about",
            "summarize the article",
            "article summary",
            "what does it cover"
        ]
        
        for pattern in meta_patterns:
            if pattern in message_lower:
                return True
                
        return False

    async def _check_query_relevance(
        self,
        query: str,
        context: str,
        language: str
    ) -> bool:
        """
        LLM-based semantic relevance check (primary gatekeeper).

        Based on research from ELOQ paper and Semantic Boundary Detection:
        - Uses LLM to intelligently determine if query relates to article content
        - Prevents hallucination on completely unrelated topics
        - More accurate than similarity thresholds or keyword matching
        """
        # Use first 5000 chars for context (Increased from 1500 to capture end of article)
        context_preview = context[:5000] if len(context) > 5000 else context

        if language == "tr":
            # Improved prompt with fewer constraints on "DIRECT" relevance
            prompt = f"""Aşağıdaki makale içeriği ve kullanıcı sorusunu analiz et.

MAKALE İÇERİĞİ:
{context_preview}

KULLANICI SORUSU:
{query}

GÖREV: Soru makale bağlamı içinde cevaplanabilir mi veya makale ile ilgili mi?

DEĞERLENDİRME KRİTERLERİ:
1. ✅ Makale hakkında genel sorular (örn: "makalede ne anlatılıyor", "özetle") → EVET
2. ✅ Makalenin ANA KONUSU ile ilgili sorular → EVET
3. ❌ Makalede sadece ÖRNEK olarak geçen kavramlar hakkında sorular → HAYIR
4. ❌ TAMAMEN alakasız ve makalede geçmeyen konular (örn: Spor, siyaset, yemek tarifi) → HAYIR

ÖRNEKLER:
✅ EVET:
- "Makalede ne anlatılmaktadır?"
- "3 Katmanlı Savunma Hattı nedir?" (eğer makalede geçiyorsa)
- "Cache stratejileri nelerdir?"

❌ HAYIR:
- "Galatasaray maçı ne oldu?" (spor - makalede örnek olarak geçse bile HAYIR)
- "CQRS nasıl kullanılır?" (eğer makalede hiç bahsedilmiyorsa)

ÖZEL KURAL:
Eğer bir kelime/cümle makalede sadece "örnek", "uğursuz örnek", "alakasız", "kötü örnek" 
gibi ibarelerle birlikte geçiyorsa veya makalenin konusuyla ilgisiz bir örnekse, 
bu kelime hakkında soru sorulduğunda HAYIR de.

KARAR:
SADECE "EVET" veya "HAYIR" cevabını ver."""
        else:
            # Improved prompt for English
            prompt = f"""Analyze the article content and user question.

ARTICLE CONTENT:
{context_preview}

USER QUESTION:
{query}

TASK: Can the question be answered within the context of the article or is it related?

EVALUATION CRITERIA:
1. ✅ General questions about the article (e.g. "summarize", "what is this about") -> YES
2. ✅ Questions about the MAIN TOPIC of the article -> YES
3. ❌ Questions about concepts mentioned ONLY as EXAMPLES -> NO
4. ❌ COMPLETELY unrelated topics (e.g. Sports, Politics, Recipes) -> NO

EXAMPLES:
✅ YES:
- "What is this article about?"
- "What is 3-Layer Defense?" (if mentioned in article)
- "What are the caching strategies?"

❌ NO:
- "Who won the football match?" (sports - even if mentioned as example)
- "How to use CQRS?" (if not mentioned in article)

SPECIAL RULE:
If a concept appears in the article ONLY as an "example", "bad example", "irrelevant example",
or is unrelated to the technical topic, answer NO.

DECISION:
Answer ONLY "YES" or "NO"."""

        try:
            response = await self._llm.generate_text(prompt)
            # Clean and normalize response
            response = response.strip().upper().replace(".", "").replace("EVET.", "EVET").replace("YES.", "YES").replace("HAYIR.", "HAYIR").replace("NO.", "NO")

            is_relevant = response in ["EVET", "YES"]

            # Comprehensive logging for monitoring (Datadog/Kong best practices)
            logger.info(
                f"[RELEVANCE_CHECK] query='{query[:40]}...' "
                f"llm_verdict='{response}' is_relevant={is_relevant} "
                f"context_len={len(context_preview)}"
            )

            return is_relevant

        except Exception as e:
            # BUG-014: Fail-safe - if LLM check fails, use deterministic rules instead of blindly allowing
            # This prevents unrelated queries from being processed when the LLM is unavailable
            logger.error(f"[RELEVANCE_CHECK] LLM check failed: {e}, applying fail-safe deterministic rules")

            # Fail-safe deterministic rules:
            # 1. Very low similarity -> reject
            if similarity_score < 0.25:
                logger.warning(f"[RELEVANCE_FAILSAFE] Rejected due to low similarity {similarity_score:.3f}")
                return False

            # 2. High similarity (>0.50) -> likely relevant
            if similarity_score >= 0.50:
                logger.info(f"[RELEVANCE_FAILSAFE] Accepted due to high similarity {similarity_score:.3f}")
                return True

            # 3. Medium similarity (0.25-0.50) -> conservative: check for keyword overlap
            query_lower = query.lower()
            context_lower = context[:1000].lower()  # Check first 1000 chars for keywords

            # Extract meaningful words from query (remove short words and common stopwords)
            query_words = [w for w in query_lower.split() if len(w) > 3]
            meaningful_matches = sum(1 for word in query_words if word in context_lower)

            # Require at least 2 meaningful word matches for medium similarity
            is_relevant = meaningful_matches >= 2
            logger.info(
                f"[RELEVANCE_FAILSAFE] Keyword overlap check: "
                f"similarity={similarity_score:.3f}, matches={meaningful_matches}, result={is_relevant}"
            )
            return is_relevant

    def _get_no_context_response(self, language: str) -> str:
        """Get response when no context found."""
        if language == "tr":
            return "Bu soru hakkında makalede bilgi bulamadım."
        return "I couldn't find information about this in the article."

    def _get_out_of_scope_response(self, language: str) -> str:
        """Get response when question is outside article scope."""
        if language == "tr":
            return "Bu konu makalenin kapsamı dışındadır. Sadece makalede anlatılan konular hakkında yardımcı olabilirim."
        return "This topic is outside the article's scope. I can only help with topics covered in the article."

    def _is_greeting(self, message: str) -> bool:
        """Detect if message is a greeting."""
        message_lower = message.lower().strip()

        # Rule 1: Very short messages (likely greetings/typos)
        # Increased from 10 to 5 characters - less aggressive
        if len(message_lower) < 5:
            return True

        # Rule 2: Check against greeting patterns
        greetings = [
            "merhaba", "merhba", "meraba", "mrhaba",  # common typos
            "selam", "slm", "slem",
            "hey", "hi", "hello",
            "günaydın", "günaydin", "gunaydin", "good morning",
            "iyi akşamlar", "iyi aksamlar", "good evening",
            "iyi geceler", "good night",
            "nasılsın", "nasilsin", "naslSn", "how are you",
            "ne haber", "naber", "nbr", "what's up", "whatsup"
        ]

        # Direct greeting match
        for greeting in greetings:
            if greeting in message_lower:
                return True

        # Rule 3: Short messages with greeting words
        if len(message_lower) < 25:
            message_words = set(message_lower.split())
            greeting_words = {"merhaba", "selam", "hey", "hi", "naber", "nbr", "slm"}
            if message_words.intersection(greeting_words):
                return True

        return False

    def _get_greeting_response(self, language: str) -> str:
        """Get response for greetings."""
        if language == "tr":
            return "Merhaba! Bu blog makalesi hakkında sorularınızı yanıtlayabilirim. Makalede anlatılan konularla ilgili bir şey sorabilir misiniz?"
        return "Hello! I can answer questions about this blog article. Can you ask something related to the topics covered in the article?"
