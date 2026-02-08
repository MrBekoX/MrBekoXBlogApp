"""RAG-powered chat handler for article Q&A."""

import logging
from typing import Optional
from dataclasses import dataclass
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.core.config import settings
from app.rag.retriever import Retriever
from app.tools.web_search import WebSearchTool
from app.agent.simple_blog_agent import SimpleBlogAgent

logger = logging.getLogger(__name__)

# Chat prompts

# Chat prompts
RAG_SYSTEM_PROMPT_TR = """Sen bir blog makalesini cevaplamaya yardimsever bir asistansin.
Asagidaki makale bolumlerini kullanarak kullanicinin sorusunu cevapla.

ONEMLI KURALLAR:
1. SADECE verilen bolumlerden bilgi kullan. Eger cevap bolümlerde yoksa, bunu belirt.
2. Cevaplarin kisa ve oz olmali (2-4 cumle).
3. Cevabinizi Turkce olarak verin (aksi belirtilmedikce).
4. Kaynak olarak hangi bolumden bilgi aldiginizi belirtmeyin, sadece cevap verin.

MAKALE BOLUMLERI:
{context}

NOT: Eger soru makale ile ilgili degilse veya bolumlerden cevaplanamiyorsa,
kibarca bunu belirtin ve kullaniciya makale hakkinda soru sormalarini onerin."""

RAG_SYSTEM_PROMPT_EN = """You are a helpful assistant that answers questions about a blog article.
Use the article sections below to answer the user's question.

IMPORTANT RULES:
1. ONLY use information from the provided sections. If the answer is not in the sections, state this.
2. Keep answers concise (2-4 sentences).
3. Provide your answer in English (unless otherwise specified).
4. Don't mention which section the information comes from, just answer.

ARTICLE SECTIONS:
{context}

NOTE: If the question is not related to the article or cannot be answered from the sections,
politely state this and suggest the user ask questions about the article."""


@dataclass
class ChatMessage:
    """A chat message."""
    role: str  # 'user' or 'assistant'
    content: str


@dataclass
class ChatResponse:
    """Response from the chat handler."""
    response: str
    sources_used: int
    is_rag_response: bool
    context_preview: Optional[str] = None
    sources: Optional[list[dict]] = None


class RagChatHandler:
    """
    RAG-powered chat handler for answering questions about articles.

    Uses semantic search to find relevant article chunks,
    then generates a response using the LLM with the retrieved context.
    """

    def __init__(
        self,
        retriever_instance: Retriever,
        web_search: WebSearchTool,
        agent: SimpleBlogAgent
    ):
        self._retriever = retriever_instance
        self._web_search = web_search
        self._agent = agent
        self._llm: Optional[ChatOllama] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the chat handler."""
        if self._initialized:
            return

        await self._retriever.initialize()

        # Initialize LLM
        self._llm = ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0.3,  # Lower temperature for factual responses
            timeout=settings.ollama_timeout,
            num_ctx=settings.ollama_num_ctx,
        )

        self._initialized = True
        logger.info("RagChatHandler initialized")

    async def chat(
        self,
        post_id: str,
        user_message: str,
        conversation_history: Optional[list[ChatMessage]] = None,
        language: str = "tr",
        k: int = 5
    ) -> ChatResponse:
        """
        Process a chat message using RAG.

        Args:
            post_id: Article ID to search within
            user_message: User's question
            conversation_history: Previous messages in the conversation
            language: Response language ('tr' or 'en')
            k: Number of chunks to retrieve

        Returns:
            ChatResponse with the generated answer
        """
        if not self._initialized:
            await self.initialize()

        if not self._llm:
            raise RuntimeError("LLM not initialized")

        logger.info(f"Processing chat for post {post_id}: {user_message[:50]}...")

        # Retrieve relevant chunks
        retrieval_result = await self._retriever.retrieve_with_context(
            query=user_message,
            post_id=post_id,
            k=k
        )

        # Check if we have any relevant context
        if not retrieval_result.has_results:
            logger.info(f"No relevant chunks found for post {post_id}")
            return ChatResponse(
                response=self._get_no_context_response(language),
                sources_used=0,
                is_rag_response=False
            )

        # Build context from retrieved chunks
        context = retrieval_result.context

        # Select appropriate system prompt
        system_prompt = (
            RAG_SYSTEM_PROMPT_TR if language == "tr"
            else RAG_SYSTEM_PROMPT_EN
        )

        # Build message history for the LLM
        messages = []

        # Add conversation history if provided
        if conversation_history:
            for msg in conversation_history[-4:]:  # Last 4 messages for context
                messages.append((msg.role, msg.content))

        # Add current user message
        messages.append(("user", user_message))

        # Create prompt with system context
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            *messages
        ])

        # Generate response
        chain = prompt | self._llm | StrOutputParser()

        response = await chain.ainvoke({
            "context": context
        })

        logger.info(f"Generated response for post {post_id}: {response[:100]}...")

        return ChatResponse(
            response=response.strip(),
            sources_used=len(retrieval_result.chunks),
            is_rag_response=True,
            context_preview=context[:200] + "..." if len(context) > 200 else context
        )

    async def generate_search_query(
        self,
        article_title: str,
        user_question: str,
        article_content: str = "",
        language: str = "tr"
    ) -> str:
        """
        Generate an optimized search query using LLM-extracted keywords.

        Strategy:
        1. Use SimpleBlogAgent to extract keywords from article content (software/tech context)
        2. Add domain context (programming, backend, development) to avoid browser cache results
        3. Combine title keywords for specificity
        4. For verification: keywords + programming context

        Args:
            article_title: Title of the article
            user_question: User's question
            article_content: Article content for keyword extraction
            language: Language code

        Returns:
            Optimized search query string
        """
        import re

        # Extract keywords from article content using LLM with tech context
        keywords_list = []
        if article_content:
            try:
                keywords_list = await self._agent.extract_keywords(
                    content=article_content,
                    count=5,
                    language=language
                )
                logger.info(f"Extracted keywords: {keywords_list}")
            except Exception as e:
                logger.warning(f"Failed to extract keywords: {e}")

        # Always extract title keywords as well (they contain specific terms like "Redis", "Architecture")
        clean_title = re.sub(r'[^\w\s]', '', article_title)
        title_keywords = [w for w in clean_title.split() if len(w) > 3][:5]

        # Combine content keywords + title keywords for better coverage
        # Remove duplicates while preserving order
        seen = set()
        combined_keywords = []
        for kw_list in [keywords_list, title_keywords]:
            for kw in kw_list:
                kw_lower = kw.lower()
                if kw_lower not in seen:
                    seen.add(kw_lower)
                    combined_keywords.append(kw)

        # Filter out generic terms that cause wrong results
        generic_terms = {
            "cache", "performance", "speed", "fast", "hız", "performans",
            "clean", "development", "software", "programming", "yazılım"
        }
        
        # Keep "cache" if it is accompanied by specific technologies (e.g. Redis Cache is fine, but just Cache is bad)
        # Actually, let's just trust the LLM extracted keywords more but filter strictly generic adjectives.
        
        filtered_keywords = []
        for k in combined_keywords:
            if k.lower() not in generic_terms:
                filtered_keywords.append(k)
        
        # If we filtered everything (e.g. only had "Cache"), put back original
        if not filtered_keywords:
            filtered_keywords = combined_keywords

        # Use filtered keywords
        final_keywords = filtered_keywords[:4]

        # Check if this is a verification/fact-check request
        is_verification = any(x in user_question.lower() for x in [
            "doğrula", "verify", "fact check", "gerçek", "doğru", "bilgi", "anlatılan"
        ])

        # Base query from keywords
        keywords_query = " ".join(final_keywords)

        if is_verification:
            # Add programming/tech domain context to avoid browser cache results
            query = f"{keywords_query} technical documentation"
        else:
            # For general questions, extract meaningful keywords from question
            minimal_stopwords_tr = ["nedir", "nasil", "niye", "nicin", "mi", "mu", "ile", "ve", "ne", "zaman"]
            minimal_stopwords_en = ["what", "how", "why", "is", "are", "do", "does", "with", "and", "when"]
            
            minimal_stopwords = minimal_stopwords_tr if language == "tr" else minimal_stopwords_en

            question_normalized = user_question.lower().replace("İ", "i").replace("ı", "i") if user_question else ""
            words = question_normalized.split()

            question_keywords = []
            for w in words:
                w_norm = w.replace("İ", "i").replace("ı", "i")
                # Remove punctuation
                w_norm = "".join(c for c in w_norm if c.isalnum())
                
                if not w_norm:
                    continue
                    
                is_stop = False
                for s in minimal_stopwords:
                    if w_norm == s:
                        is_stop = True
                        break
                
                if not is_stop and len(w_norm) > 2:
                    question_keywords.append(w_norm)

            cleaned_question = " ".join(question_keywords[:3]) # Limit question keywords

            # Build query
            # Don't add "programming" if we already have specific tech keywords
            has_tech_context = any(kw.lower() in ["redis", "python", "docker", "api", "database", "sql", "react", "nextjs"] for kw in final_keywords)
            
            if cleaned_question:
                query = f"{keywords_query} {cleaned_question}"
            else:
                query = keywords_query

            if not has_tech_context:
                query += " software"

        logger.info(f"Generated deterministic query: '{query}'")
        return query

    async def chat_with_web_search(
        self,
        post_id: str,
        user_message: str,
        article_title: str,
        web_search_results: list[dict],
        rag_context: str = "",
        language: str = "tr"
    ) -> ChatResponse:
        """
        Process a chat message combining RAG and web search results (Hybrid).

        Args:
            post_id: Article ID
            user_message: User's question
            article_title: Title of the article
            web_search_results: Results from web search
            rag_context: Context retrieved from the article (RAG)
            language: Response language

        Returns:
            ChatResponse with the combined answer
        """
        if not self._initialized:
            await self.initialize()

        if not self._llm:
            raise RuntimeError("LLM not initialized")

        # Format web search results
        web_context = "\n\n".join([
            f"**{result.get('title', 'Untitled')}**\n{result.get('snippet', '')}\nKaynak: {result.get('url', '')}"
            for result in web_search_results
        ])

        # Build prompt for web search response
        if language == "tr":
            prompt_template = """Sen bir arastirma asistanisin. "{article_title}" baslıklı makale hakkında kullanicinin sorusunu cevapla.

ASLA YAPMA:
- Cevabın sonuna "Kaynaklar", "Referanslar" veya "Linkler" gibi bir liste EKLEME.
- Metin içinde URL veya link PAYLAŞMA.
- "... sitesine göre" gibi ifadeler KULLANMA.

YAPMAN GEREKEN:
- Sadece bilgiyi sentezle ve cevabı ver.
- Kaynaklar zaten ayrı bir UI elementinde gösterilecek, senin metninde olmasına gerek yok.
- Cevabın temiz bir paragraf olmalı.

MAKALE BAGLAMI (RAG):
{rag_context}

WEB ARAMA SONUCLARI:
{web_context}

KULLANICI SORUSU: {question}

TEMİZ CEVAP:"""
        else:
            prompt_template = """You are a research assistant. Answer the user's question about the article "{article_title}".

NEVER DO THIS:
- Do NOT add a "Sources", "References", or "Links" list at the end.
- Do NOT include URLs or links in the text.
- Do NOT use phrases like "according to...".

WHAT YOU SHOULD DO:
- Synthesize the information and provide the answer.
- Sources are displayed in a separate UI element, they are NOT needed in your text.
- Your answer should be a clean paragraph.

ARTICLE CONTEXT (RAG):
{rag_context}

WEB SEARCH RESULTS:
{web_context}

USER QUESTION: {question}

CLEAN ANSWER:"""

        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | self._llm | StrOutputParser()

        response = await chain.ainvoke({
            "article_title": article_title,
            "rag_context": rag_context,
            "web_context": web_context,
            "question": user_message
        })

        return ChatResponse(
            response=response.strip(),
            sources_used=len(web_search_results),
            is_rag_response=False,
            context_preview=web_context[:200] + "...",
            sources=web_search_results
        )

    async def collect_sources(
        self,
        post_id: str,
        articletitle: str,
        articlecontent: str,
        user_question: str,
        language: str = "tr",
        max_results: int = 10,
    ) -> list[dict]:
        """
        Collect trusted web sources based on article content and user question.
        
        Args:
            post_id: Article ID
            articletitle: Article title
            articlecontent: Article content
            user_question: User's question
            language: Language code
            max_results: Max results to return
            
        Returns:
            List of source dictionaries (title, url, snippet)
        """
        if not self._initialized:
            await self.initialize()

        # Generate optimized search query
        query = await self.generate_search_query(
            article_title=articletitle,
            user_question=user_question,
            article_content=articlecontent,
            language=language
        )

        # Determine region
        region = "tr-tr" if language.lower() == "tr" else "wt-wt"
        if language.lower() == "en":
            region = "us-en"

        # Perform search using WebSearchTool
        # filter_results is already applied inside search()
        response = await self._web_search.search(
            query=query,
            max_results=max_results,
            region=region
        )

        # Return just the list of sources
        return [r.to_dict() for r in response.results]

    def _get_no_context_response(self, language: str) -> str:
        """Get response when no relevant context is found."""
        if language == "tr":
            return (
                "Uzgunum, bu soru hakkinda makalede ilgili bilgi bulamadim. "
                "Lutfen makale icerigiyle ilgili bir soru sormay, deneyin."
            )
        return (
            "I'm sorry, I couldn't find relevant information about this question in the article. "
            "Please try asking a question related to the article content."
        )



