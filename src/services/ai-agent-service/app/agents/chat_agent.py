"""Chat agent " RAG-powered article Q&A with memory integration and ReAct reasoning.



Supports:

- Simple queries: Direct RAG response

- Medium complexity: ReAct reasoning loop

- Complex queries: Full autonomous agent with planning

"""



import logging

import re

from typing import Any



from langgraph.graph import StateGraph



from app.agents.base_agent import BaseSpecializedAgent

from app.services.chat_service import ChatService

from app.services.analysis_service import AnalysisService

from app.domain.entities.chat import ChatMessage

from app.memory.conversation_memory import ConversationMemoryService

from app.agents.react_chat_agent import ReActChatAgent

from app.core.config import settings
from app.security.backend_authorization_client import AuthorizationContext



logger = logging.getLogger(__name__)



WEB_SEARCH_INTENT_PATTERNS = [

    r"\bweb\s*'?de\b.*\b(ara|bul|arastir|search)\b",

    r"\binternet(te|ten)?\b.*\b(ara|bul|arastir|search)\b",

    r"\b(ara|bul|arastir|search|google|look up)\b.*\b(web|internet|online)\b",

    r"\b(search the web|web search|online search|look it up)\b",

    r"\b(guncel|latest|current)\b.*\b(ara|search|research)\b",

]





class ChatAgent(BaseSpecializedAgent):

    """Handles chat messages using ChatService + ConversationMemory.



    Execution modes (configurable via settings):

    - Simple queries: Direct RAG response

    - Medium complexity: ReAct reasoning loop

    - Complex queries: Full autonomous agent with planning (when enabled)

    """



    def __init__(

        self,

        chat_service: ChatService,

        analysis_service: AnalysisService,

        memory_service: ConversationMemoryService | None = None,

        react_agent: ReActChatAgent | None = None,

        autonomous_agent: Any | None = None,

    ):

        self._chat = chat_service

        self._analysis = analysis_service

        self._memory = memory_service

        self._react = react_agent

        self._autonomous = autonomous_agent



    @property

    def name(self) -> str:

        return "chat"



    def get_graph(self) -> StateGraph:

        return None  # type: ignore[return-value]



    async def execute(self, payload: dict[str, Any], language: str) -> dict[str, Any]:

        logger.info("[ChatAgent] execute() START")

        post_id = payload.get("postId", "")

        user_message = payload.get("userMessage", "")

        session_id = payload.get("sessionId", "")

        article_title = payload.get("articleTitle", "")

        article_content = payload.get("articleContent", "")
        operation_id = payload.get("_operationId") or payload.get("operationId")
        enable_web_search = payload.get("enableWebSearch", False)
        auth_context = AuthorizationContext.from_payload(payload.get("authContext") or payload.get("auth_context"))

        history_raw = payload.get("conversationHistory", [])



        #Jailbreak Detection 

        logger.info("[ChatAgent] Running jailbreak detection...")

        from app.security.jailbreak_detector import SemanticJailbreakDetector

        detector = SemanticJailbreakDetector(use_llm=False)  # Pattern-only for speed

        result = await detector.detect(user_message)

        logger.info(f"[ChatAgent] Jailbreak detection complete: is_jailbreak={result.is_jailbreak}")

        if result.is_jailbreak:

            logger.warning(f"[ChatAgent] Jailbreak blocked: {result.jailbreak_type}")

            return {

                "response": "GÃƒÆ’Ã‚Â¼venlik ihlali tespit edildi. LÃƒÆ’Ã‚Â¼tfen talebinizi farklÃƒâ€Ã‚Â± bir Ãƒâ€¦Ã…Â¸ekilde ifade edin.",

                "isWebSearchResult": False,

                "sources": None,

            }



        inferred_web_search = self._has_web_search_intent(user_message)

        if inferred_web_search and not enable_web_search:

            logger.info("[ChatAgent] Web-search intent detected from message, enabling hybrid path")

        enable_web_search = bool(enable_web_search) or inferred_web_search



        # ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ Memory: load conversation history ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢"ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬

        if self._memory:

            try:

                logger.info(f"[ChatAgent] Loading memory (session_id={session_id})...")
                mem_history = await self._memory.get_conversation_history(session_id, 10)
                logger.info(f"[ChatAgent] Memory loaded: {len(mem_history)} messages")

                history = [

                    ChatMessage(role=m["role"], content=m["content"]) for m in mem_history

                ]

            except Exception as e:

                logger.warning(f"[ChatAgent] Memory load failed, using raw history: {e}")

                history = [

                    ChatMessage(role=h.get("role", "user"), content=h.get("content", ""))

                    for h in history_raw

                ]

        else:

            history = [

                ChatMessage(role=h.get("role", "user"), content=h.get("content", ""))

                for h in history_raw

            ]



        # Summary shortcut

        normalized_message = self._normalize_intent_text(user_message)
        summary_patterns = [
            r"^(bu\s+)?makaleyi\s+ozetle",
            r"^makalenin\s+ozet",
            r"^bu\s+makalenin\s+ozeti",
            r"^summarize\s+(the\s+)?article",
            r"^article\s+summary",
        ]
        if any(re.search(pattern, normalized_message) for pattern in summary_patterns):

            logger.info("[ChatAgent] Summary trigger matched, calling summarize_article")

            summary = await self._analysis.summarize_article(

                content=article_content, max_sentences=5, language=language

            )

            await self._persist_exchange(session_id, user_message, summary, operation_id)

            return {"response": summary, "isWebSearchResult": False, "sources": None}



        # Web search path

        if enable_web_search:

            logger.info(f"[ChatAgent] Web search path enabled (payload={payload.get('enableWebSearch', False)}, inferred={inferred_web_search}), calling chat_with_web_search")

            resp = await self._chat.chat_with_web_search(

                post_id=post_id,

                user_message=user_message,

                article_title=article_title,

                article_content=article_content,

                language=language,
                auth_context=auth_context,
            )

            await self._persist_exchange(session_id, user_message, resp.response, operation_id)

            return {

                "response": resp.response,

                "isWebSearchResult": bool(resp.sources),

                "sources": resp.sources,

            }



        # ReAct / Autonomous for complex queries

        # Use pre-computed complexity from message_processor if available,

        # otherwise fall back to local heuristic.

        complexity_level = self._normalize_complexity_level(payload.get("complexityLevel", ""))
        autonomous_intent = self._is_autonomous_intent(user_message)

        if not complexity_level:
            if autonomous_intent or self._is_highly_complex(user_message):
                complexity_level = "highly_complex"
            elif self._is_complex_query(user_message):
                complexity_level = "complex"
            else:
                complexity_level = "simple"
        elif complexity_level == "simple" and (autonomous_intent or self._is_highly_complex(user_message)):
            complexity_level = "highly_complex"
        elif complexity_level == "complex" and autonomous_intent:
            complexity_level = "highly_complex"

        logger.info(f"[ChatAgent] Complexity routing: level={complexity_level}, autonomous_intent={autonomous_intent}")

        can_use_autonomous = bool(settings.agent_autonomous_enabled and self._autonomous)

        if can_use_autonomous and complexity_level == "highly_complex":
            logger.info(
                "[ChatAgent] Highly complex query, using Autonomous agent "
                f"(complexity={complexity_level}, autonomous_intent={autonomous_intent})"
            )
            answer = await self._run_autonomous(
                user_message=user_message,
                post_id=post_id,
                session_id=session_id,
                article_title=article_title,
                article_content=article_content,
                history=history,
                language=language,
                auth_context=auth_context,
            )
            await self._persist_exchange(session_id, user_message, answer, operation_id)
            return {"response": answer, "isWebSearchResult": False, "sources": None}

        if self._react and complexity_level == "complex":
            # Context check is kept for ReAct to avoid hallucination.
            context_sufficient = await self._check_context_relevance(
                post_id=post_id,
                user_message=user_message,
                article_content=article_content,
            )

            if context_sufficient:
                logger.info("[ChatAgent] Complex query detected, using ReAct agent")

                history_text = "\n".join(
                    f"{m.role}: {m.content}" for m in history[-4:]
                )

                answer = await self._react.run(
                    user_message=user_message,
                    post_id=post_id,
                    conversation_history=history_text,
                    language=language,
                    auth_context=auth_context,
                )

                await self._persist_exchange(session_id, user_message, answer, operation_id)
                return {"response": answer, "isWebSearchResult": False, "sources": None}

            if can_use_autonomous and autonomous_intent:
                logger.info(
                    "[ChatAgent] Insufficient context for ReAct; escalating to Autonomous agent "
                    f"(autonomous_intent={autonomous_intent})"
                )
                answer = await self._run_autonomous(
                    user_message=user_message,
                    post_id=post_id,
                    session_id=session_id,
                    article_title=article_title,
                    article_content=article_content,
                    history=history,
                    language=language,
                    auth_context=auth_context,
                )
                await self._persist_exchange(session_id, user_message, answer, operation_id)
                return {"response": answer, "isWebSearchResult": False, "sources": None}

            logger.warning("[ChatAgent] Insufficient context for ReAct, falling back to standard RAG")



        # Standard RAG chat

        # NOTE: Do not prepend memory blocks into user_message.

        # It contaminates intent/existence parsing and retrieval query quality.

        logger.info(f"[ChatAgent] Calling ChatService.chat (post_id={post_id})...")

        resp = await self._chat.chat(

            post_id=post_id,

            user_message=user_message,

            conversation_history=history,

            language=language,
            auth_context=auth_context,
        )

        logger.info(f"[ChatAgent] ChatService.chat completed, response_len={len(resp.response)}")

        await self._persist_exchange(session_id, user_message, resp.response, operation_id)

        # ChatService.chat() already ran retrieval internally — no second RAG call needed.
        # Verification for chat is skipped in _finalize_node, so retrieved_chunks is unused.
        return {"response": resp.response, "isWebSearchResult": False, "sources": None, "retrieved_chunks": []}



    @staticmethod

    def _is_complex_query(message: str) -> bool:

        """Heuristic: detect queries that benefit from multi-step reasoning."""

        lower = message.lower().strip()

        # Multi-part questions

        if lower.count("?") > 1:

            return True

        # Comparison / contrast signals

        complex_markers = [

            "karsilastir", "compare", "fark", "difference", "neden", "why",

            "nasil", "how does", "explain why", "acikla", "analiz",

            "analyze", "evaluate", "pros and cons", "avantaj",

        ]

        if any(m in lower for m in complex_markers):

            return True

        # Long questions likely need reasoning

        if len(lower.split()) > 20:

            return True

        return False



    @staticmethod

    def _is_highly_complex(message: str) -> bool:

        """Heuristic: detect queries requiring autonomous planning."""

        lower = message.lower().strip()



        # Multiple different tasks

        task_count = 0

        task_indicators = [

            "ve", "and", "sonra", "then", "ardindan", "after",

            "ayrica", "also", "hem de", "as well as", "plus",

        ]

        for indicator in task_indicators:

            if indicator in lower:

                task_count += 1



        if task_count >= 2:

            return True



        # Requires external research

        research_phrases = [

            "web'de ara", "search web", "araÃƒâ€¦Ã…Â¸tÃƒâ€Ã‚Â±r", "research",

            "gÃƒÆ’Ã‚Â¼ncel", "current", "latest",

        ]

        if any(m in lower for m in research_phrases):

            return True

        # Word-boundary check for short markers to avoid false positives

        # ("son" matching "sonuÃƒÆ’Ã‚Â§/sonra", "new" matching "news")

        if re.search(r"\bson\b", lower) or re.search(r"\bnew\b", lower):

            return True



        # Very long queries

        if len(lower.split()) > 30:

            return True



        return False



    async def _run_autonomous(
        self,
        user_message: str,
        post_id: str,
        session_id: str,
        article_title: str,
        article_content: str,
        history: list[ChatMessage],
        language: str,
        auth_context: AuthorizationContext,
    ) -> str:
        """Execute autonomous agent with normalized payload."""
        history_text = "\n".join(f"{m.role}: {m.content}" for m in history[-4:])
        payload_for_autonomous = {
            "userMessage": user_message,
            "postId": post_id,
            "sessionId": session_id,
            "conversationHistory": history_text,
            "context": {
                "articleTitle": article_title,
                "articleContent": article_content[:2000] if article_content else "",
                "auth_context": {
                    "subjectType": auth_context.subject_type,
                    "subjectId": auth_context.subject_id,
                    "roles": auth_context.roles,
                    "fingerprint": auth_context.fingerprint,
                },
            },
        }
        result = await self._autonomous.execute(payload_for_autonomous, language)
        return result.get("response", "Unable to process request.")

    @staticmethod
    def _normalize_complexity_level(raw_level: Any) -> str:
        """Normalize upstream complexity labels to expected values."""
        level = str(raw_level or "").strip().lower()
        aliases = {
            "low": "simple",
            "medium": "complex",
            "high": "highly_complex",
            "advanced": "highly_complex",
        }
        normalized = aliases.get(level, level)
        if normalized in {"simple", "complex", "highly_complex"}:
            return normalized
        return ""

    @classmethod
    def _is_autonomous_intent(cls, message: str) -> bool:
        """Detect intents that benefit from autonomous planning/tool orchestration."""
        normalized = cls._normalize_intent_text(message)
        if not normalized:
            return False

        hard_markers = [
            "geri bildirim",
            "feedback",
            "tercih",
            "preference",
            "hatirla",
            "remember",
        ]
        if any(marker in normalized for marker in hard_markers):
            return True

        action_markers = [
            "dogrula",
            "verify",
            "alinti",
            "citation",
            "kaynak",
            "oner",
            "recommend",
            "benzer",
            "related",
            "ozet",
            "summar",
            "sadelestir",
            "beginner",
            "stajyer",
        ]
        matched_actions = sum(1 for marker in action_markers if marker in normalized)

        if matched_actions >= 2:
            return True

        has_connector = bool(
            re.search(
                r"\b(once|sonra|ardindan|en sonda|ilk olarak|then|finally|after)\b",
                normalized,
            )
        )
        return bool(has_connector and matched_actions >= 1)

    async def _persist_exchange(

        self, session_id: str, user_msg: str, assistant_msg: str, operation_id: str | None = None

    ) -> None:

        """Persist both user and assistant messages to memory."""

        if not self._memory:

            return

        try:

            await self._memory.add_message(session_id, "user", user_msg, operation_id=operation_id)

            await self._memory.add_message(session_id, "assistant", assistant_msg, operation_id=operation_id)

        except Exception as e:

            logger.warning(f"[ChatAgent] Memory persist failed: {e}")



    @staticmethod

    def _normalize_intent_text(message: str) -> str:

        """Normalize text for lightweight intent matching."""

        normalized = (message or "").lower().strip()

        normalized = normalized.translate(
            str.maketrans(
                {
                    "\u0131": "i",
                    "\u011f": "g",
                    "\u00fc": "u",
                    "\u015f": "s",
                    "\u00f6": "o",
                    "\u00e7": "c",
                }
            )
        )

        replacements = {
            "Ãƒâ€Ã‚Â±": "i",
            "Ãƒâ€Ã…Â¸": "g",
            "ÃƒÆ’Ã‚Â¼": "u",
            "Ãƒâ€¦Ã…Â¸": "s",
            "ÃƒÆ’Ã‚Â¶": "o",
            "ÃƒÆ’Ã‚Â§": "c",
            "ÃƒÆ’Ã¢â‚¬ÂÃƒâ€šÃ‚Â±": "i",
            "ÃƒÆ’Ã¢â‚¬ÂÃƒâ€¦Ã‚Â¸": "g",
            "ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¼": "u",
            "ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€¦Ã‚Â¸": "s",
            "ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¶": "o",
            "ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â§": "c",
        }
        for bad, good in replacements.items():
            normalized = normalized.replace(bad, good)

        return re.sub(r"\s+", " ", normalized)
    def _has_web_search_intent(cls, message: str) -> bool:

        """Detect explicit web-search request from user text."""

        normalized = cls._normalize_intent_text(message)

        if not normalized:

            return False

        return any(re.search(pattern, normalized) for pattern in WEB_SEARCH_INTENT_PATTERNS)
    async def _check_context_relevance(

        self, post_id: str, user_message: str, article_content: str

    ) -> bool:

        """Check if there's sufficient relevant context before using ReAct.



        Prevents ReAct hallucination by ensuring the article contains

        information related to the user's question.



        Returns:

            True if context is sufficient for ReAct, False otherwise

        """

        # Quick check: if article content is too short, not enough context

        if not article_content or len(article_content.strip()) < 200:

            logger.info("[ChatAgent] Article content too short for ReAct")

            return False



        # Extract key terms from user message

        message_lower = user_message.lower()



        # Key terms that should exist in context for ReAct to be useful

        # Split by common separators and filter short words

        key_terms = []

        for word in re.split(r'[\s,?\.!]+', message_lower):

            # Skip very short words and common stopwords

            if len(word) >= 4 and word not in {

                "ile", "icin", "nasil", "nedir", "nedir", "bu", "bir",

                "what", "how", "why", "when", "which", "that", "this",

                "with", "from", "about", "does", "does", "the",

            }:

                key_terms.append(word)



        if not key_terms:

            # No meaningful terms to search for

            return True  # Allow ReAct for generic questions



        # Check if at least some key terms exist in article content

        article_lower = article_content.lower()

        matches = sum(1 for term in key_terms if term in article_lower)

        match_ratio = matches / len(key_terms) if key_terms else 0



        # Require at least 30% term overlap for ReAct to be useful

        is_sufficient = match_ratio >= 0.3



        logger.info(

            f"[ChatAgent] Context relevance check: {matches}/{len(key_terms)} terms matched "

            f"({match_ratio:.0%}), sufficient={is_sufficient}"

        )



        return is_sufficient












