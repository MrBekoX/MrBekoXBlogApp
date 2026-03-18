"""Experience-oriented tools for autonomous chat workflows."""

import logging
import re
from collections import Counter
from typing import Any

from app.agents.citation import compute_overlap, extract_terms
from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.domain.interfaces.i_vector_store import IVectorStore
from app.memory.conversation_memory import ConversationMemoryService

logger = logging.getLogger(__name__)


def _clean_snippet(text: str, limit: int = 140) -> str:
    """Normalize and truncate snippet text for tool outputs."""
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


class CitationVerificationTool:
    """Compute grounding confidence and citation candidates from article chunks."""

    def __init__(
        self,
        embedding_provider: IEmbeddingProvider,
        vector_store: IVectorStore,
        max_chunks: int = 5,
    ):
        self._embedding = embedding_provider
        self._vector_store = vector_store
        self._max_chunks = max(1, max_chunks)

    async def __call__(self, query: str, post_id: str = "", **_: Any) -> str:
        if not post_id:
            return "verify_citation requires post_id."
        query = (query or "").strip()
        if not query:
            return "verify_citation requires a non-empty query."

        try:
            query_embedding = await self._embedding.embed(query)
            chunks = self._vector_store.search(
                query_embedding=query_embedding,
                post_id=post_id,
                k=self._max_chunks,
            )
            if not chunks:
                return "No supporting chunks found for citation verification."

            query_terms = extract_terms(query)
            scored: list[tuple[float, float, Any]] = []
            for chunk in chunks:
                overlap = compute_overlap(query_terms, extract_terms(chunk.content))
                confidence = (chunk.similarity_score + overlap) / 2.0
                scored.append((confidence, overlap, chunk))

            scored.sort(key=lambda item: item[0], reverse=True)
            top = scored[: self._max_chunks]
            overall_confidence = sum(item[0] for item in top) / len(top)

            lines = [
                f"confidence={overall_confidence:.2f}",
                f"sources={len(top)}",
            ]
            for idx, (confidence, overlap, chunk) in enumerate(top, start=1):
                lines.append(
                    f"[{idx}] chunk={chunk.id} score={confidence:.2f} "
                    f"(sim={chunk.similarity_score:.2f}, overlap={overlap:.2f}) "
                    f"snippet={_clean_snippet(chunk.content)}"
                )

            return "\n".join(lines)
        except Exception as exc:
            logger.warning(f"[CitationVerificationTool] Failed: {exc}")
            return f"Citation verification failed: {exc}"


class RelatedPostsTool:
    """Recommend related posts based on semantic chunk similarity."""

    def __init__(
        self,
        embedding_provider: IEmbeddingProvider,
        vector_store: IVectorStore,
        default_results: int = 4,
    ):
        self._embedding = embedding_provider
        self._vector_store = vector_store
        self._default_results = max(1, default_results)

    async def __call__(self, query: str, post_id: str = "", **kwargs: Any) -> str:
        query = (query or "").strip()
        if not query:
            return "related_posts requires a non-empty query."

        max_results = max(1, int(kwargs.get("max_results", self._default_results)))
        candidate_k = max(12, max_results * 8)

        try:
            query_embedding = await self._embedding.embed(query)
            chunks = self._vector_store.search(
                query_embedding=query_embedding,
                post_id=None,
                k=candidate_k,
            )
            if not chunks:
                return "No related posts found."

            by_post: dict[str, tuple[float, str]] = {}
            for chunk in chunks:
                if not chunk.post_id:
                    continue
                if post_id and chunk.post_id == post_id:
                    continue
                current = by_post.get(chunk.post_id)
                score = chunk.similarity_score
                snippet = _clean_snippet(chunk.content)
                if current is None or score > current[0]:
                    by_post[chunk.post_id] = (score, snippet)

            if not by_post:
                return "No related posts found."

            ranked = sorted(by_post.items(), key=lambda item: item[1][0], reverse=True)[
                :max_results
            ]
            lines = []
            for pid, (score, snippet) in ranked:
                lines.append(f"- post_id={pid} relevance={score:.2f} snippet={snippet}")
            return "\n".join(lines)
        except Exception as exc:
            logger.warning(f"[RelatedPostsTool] Failed: {exc}")
            return f"Related posts lookup failed: {exc}"


class PreferenceMemoryTool:
    """Store or recall user style/topic preferences from memory."""

    def __init__(self, memory_service: ConversationMemoryService):
        self._memory = memory_service

    async def __call__(self, query: str, **kwargs: Any) -> str:
        if not self._memory:
            return "Preference memory is not available."

        session_id = (
            kwargs.get("session_id")
            or kwargs.get("sessionId")
            or kwargs.get("conversation_id")
            or "global"
        )
        text = (query or "").strip()
        if not text:
            return "preference_memory requires input."

        if self._is_store_command(text):
            value = self._extract_preference_value(text)
            await self._memory.add_message(
                session_id=session_id,
                role="system",
                content=f"PREFERENCE: {value}",
                metadata={"memory_type": "preference"},
            )
            return f"Preference stored for session {session_id}."

        preferences: list[str] = []

        # First check short-term memory for explicit preference records.
        history = await self._memory.get_conversation_history(session_id=session_id, last_n=60)
        for item in history:
            content = (item.get("content") or "").strip()
            metadata = item.get("meta") or {}
            if metadata.get("memory_type") == "preference" or content.lower().startswith(
                "preference:"
            ):
                preferences.append(content.replace("PREFERENCE:", "").strip())

        # If no explicit STM preference entries, fall back to semantic LTM retrieval.
        if not preferences:
            memories = await self._memory.get_relevant_memories(
                session_id=session_id,
                query=f"user preference {text}",
                k=6,
            )
            for memory in memories:
                content = (memory.get("content") or "").strip()
                metadata = memory.get("metadata") or {}
                if metadata.get("memory_type") == "preference" or content.lower().startswith(
                    "preference:"
                ):
                    preferences.append(content.replace("PREFERENCE:", "").strip())

        unique_preferences = [p for p in dict.fromkeys(preferences) if p]
        if not unique_preferences:
            return "No stored preferences found for this session."

        lines = ["Stored preferences:"]
        lines.extend(f"- {pref}" for pref in unique_preferences[:5])
        return "\n".join(lines)

    @staticmethod
    def _is_store_command(text: str) -> bool:
        lower = text.lower()
        return lower.startswith(("set_pref:", "pref:", "remember preference:"))

    @staticmethod
    def _extract_preference_value(text: str) -> str:
        if ":" not in text:
            return text.strip()
        return text.split(":", 1)[1].strip() or text.strip()


class ReadabilityRewriterTool:
    """Rewrite content for a requested complexity level."""

    def __init__(self, llm_provider: ILLMProvider):
        self._llm = llm_provider

    async def __call__(self, query: str, **_: Any) -> str:
        raw = (query or "").strip()
        if not raw:
            return "readability_rewriter requires input text."

        style, text = self._parse_input(raw)
        prompt = (
            f"Rewrite the text for {style} readability.\n"
            "Keep facts unchanged. Keep the same language as source text.\n"
            "Text:\n"
            f"{text}\n\n"
            "Rewritten text:"
        )

        try:
            rewritten = await self._llm.generate_text(prompt)
            return rewritten.strip()
        except Exception as exc:
            logger.warning(f"[ReadabilityRewriterTool] Failed: {exc}")
            return f"Readability rewrite failed: {exc}"

    @staticmethod
    def _parse_input(raw: str) -> tuple[str, str]:
        # Format support: "style || text"
        if "||" in raw:
            left, right = raw.split("||", 1)
            style = ReadabilityRewriterTool._detect_style(left)
            return style, right.strip()

        style = ReadabilityRewriterTool._detect_style(raw)
        return style, raw

    @staticmethod
    def _detect_style(text: str) -> str:
        lower = text.lower()
        if any(token in lower for token in ("eli5", "beginner", "simple", "newbie")):
            return "beginner"
        if any(token in lower for token in ("expert", "advanced", "deep technical")):
            return "advanced"
        if any(token in lower for token in ("brief", "concise", "short")):
            return "concise"
        return "standard"


class FeedbackLearningTool:
    """Persist feedback signals for later personalization."""

    def __init__(self, memory_service: ConversationMemoryService):
        self._memory = memory_service

    async def __call__(self, query: str, **kwargs: Any) -> str:
        if not self._memory:
            return "feedback_learning is not available."

        session_id = (
            kwargs.get("session_id")
            or kwargs.get("sessionId")
            or kwargs.get("conversation_id")
            or "global"
        )
        text = (query or "").strip()
        if not text:
            return "feedback_learning requires input."

        if self._is_summary_request(text):
            return await self._summarize_feedback(session_id)

        sentiment = self._detect_sentiment(text)
        await self._memory.add_message(
            session_id=session_id,
            role="system",
            content=f"FEEDBACK: {text}",
            metadata={"memory_type": "feedback", "sentiment": sentiment},
        )
        return f"Feedback recorded ({sentiment}) for session {session_id}."

    async def _summarize_feedback(self, session_id: str) -> str:
        sentiments: list[str] = []

        # Read explicit feedback signals from short-term memory first.
        history = await self._memory.get_conversation_history(session_id=session_id, last_n=80)
        for item in history:
            metadata = item.get("meta") or {}
            if metadata.get("memory_type") == "feedback":
                sentiments.append(str(metadata.get("sentiment", "neutral")))

        # Fall back to semantic retrieval only if needed.
        if not sentiments:
            memories = await self._memory.get_relevant_memories(
                session_id=session_id,
                query="feedback sentiment rating",
                k=10,
            )
            for memory in memories:
                metadata = memory.get("metadata") or {}
                if metadata.get("memory_type") != "feedback":
                    continue
                sentiments.append(str(metadata.get("sentiment", "neutral")))

        if not sentiments:
            return "No feedback history found for this session."

        counts = Counter(sentiments)
        return (
            "Feedback summary: "
            f"positive={counts.get('positive', 0)}, "
            f"negative={counts.get('negative', 0)}, "
            f"neutral={counts.get('neutral', 0)}"
        )

    @staticmethod
    def _is_summary_request(text: str) -> bool:
        lower = text.lower()
        return any(token in lower for token in ("summary", "summarize", "ozet"))

    @staticmethod
    def _detect_sentiment(text: str) -> str:
        lower = text.lower()
        positive_tokens = ("like", "good", "great", "helpful", "begendim", "iyi")
        negative_tokens = ("dislike", "bad", "wrong", "poor", "begenmedim", "kotu")

        positive_score = sum(token in lower for token in positive_tokens)
        negative_score = sum(token in lower for token in negative_tokens)

        if positive_score > negative_score:
            return "positive"
        if negative_score > positive_score:
            return "negative"
        return "neutral"
