"""Verification agent — self-critique with hallucination, citation, and consistency checks."""

import logging
import re
from typing import Any, TypedDict

from langgraph.graph import StateGraph, END

from app.agents.base_agent import BaseSpecializedAgent
from app.agents.citation import build_citations, extract_terms, compute_overlap
from app.domain.interfaces.i_llm_provider import ILLMProvider

logger = logging.getLogger(__name__)

HALLUCINATION_THRESHOLD = 0.5


class VerificationState(TypedDict, total=False):
    """State for verification sub-graph."""

    original_content: str
    generated_output: str
    retrieved_chunks: list[dict[str, Any]]
    language: str
    # Results
    verification_result: dict[str, Any] | None
    passed: bool
    corrections: str | None


class VerificationAgent(BaseSpecializedAgent):
    """Runs self-critique on generated outputs.

    Checks:
    1. Hallucination detection (LLM-based, temperature=0.1)
    2. Citation consistency (deterministic term overlap)
    3. Correction suggestion if checks fail
    """

    def __init__(self, llm_provider: ILLMProvider):
        self._llm = llm_provider
        self._graph_compiled = self._build_graph()

    @property
    def name(self) -> str:
        return "verifier"

    def get_graph(self) -> StateGraph:
        return self._graph_compiled

    def _build_graph(self) -> Any:
        builder = StateGraph(VerificationState)

        builder.add_node("verify", self._verify_node)
        builder.add_node("correct", self._correct_node)

        builder.set_entry_point("verify")
        builder.add_conditional_edges(
            "verify",
            self._should_correct,
            {"correct": "correct", "end": END},
        )
        builder.add_edge("correct", END)

        return builder.compile()

    def _should_correct(self, state: VerificationState) -> str:
        if state.get("passed", True):
            return "end"
        return "correct"

    async def _verify_node(self, state: VerificationState) -> dict:
        """Run hallucination + citation checks."""
        original = state.get("original_content", "")
        generated = state.get("generated_output", "")
        chunks = state.get("retrieved_chunks", [])
        language = state.get("language", "tr")

        # 1. Hallucination check (LLM-based)
        hallucination_score, hallucination_reason = await self._check_hallucination(
            original, generated, language
        )

        # 2. Citation / grounding check (deterministic)
        citation_ok, citation_detail = self._check_citations(generated, chunks)

        # 3. Consistency check
        consistency_ok = self._check_consistency(original, generated)

        passed = (
            hallucination_score < HALLUCINATION_THRESHOLD
            and citation_ok
            and consistency_ok
        )

        result = {
            "hallucination_score": hallucination_score,
            "hallucination_reason": hallucination_reason,
            "citation_ok": citation_ok,
            "citation_detail": citation_detail,
            "consistency_ok": consistency_ok,
            "passed": passed,
        }

        logger.info(
            f"[Verifier] passed={passed} hallucination={hallucination_score:.2f} "
            f"citation_ok={citation_ok} consistency_ok={consistency_ok}"
        )

        return {"verification_result": result, "passed": passed}

    async def _correct_node(self, state: VerificationState) -> dict:
        """Suggest corrections for failed verification."""
        original = state.get("original_content", "")
        generated = state.get("generated_output", "")
        language = state.get("language", "tr")
        result = state.get("verification_result", {})

        corrections = await self._suggest_corrections(
            original, generated, result, language
        )
        return {"corrections": corrections}

    # ── Hallucination check ─────────────────────────────────────────

    async def _check_hallucination(
        self, context: str, answer: str, language: str
    ) -> tuple[float, str]:
        """LLM-based hallucination score (0.0 = fully grounded, 1.0 = fabricated)."""
        if not answer.strip():
            return 0.0, "empty_answer"

        context_preview = context[:4000]

        if language == "tr":
            prompt = f"""Asagidaki cevap ile baglam arasindaki uyumu degerlendir.
0.0 = tamamen baglama dayali, 1.0 = tamamen uydurma.

BAGLAM:
{context_preview}

CEVAP:
{answer}

Sadece bir ondalik sayi yaz (ornek: 0.15):"""
        else:
            prompt = f"""Rate how well the answer is grounded in the context.
0.0 = fully grounded, 1.0 = fully fabricated.

CONTEXT:
{context_preview}

ANSWER:
{answer}

Return only a decimal number (e.g., 0.15):"""

        try:
            raw = await self._llm.generate_text(prompt)
            # Extract first float from response
            match = re.search(r'(\d+\.?\d*)', raw.strip())
            score = float(match.group(1)) if match else 0.5
            score = max(0.0, min(1.0, score))
            return score, "llm_scored"
        except Exception as e:
            logger.warning(f"[Verifier] Hallucination check failed: {e}")
            return 0.5, f"error:{e}"

    # ── Citation check ──────────────────────────────────────────────

    @staticmethod
    def _check_citations(
        answer: str, chunks: list[dict[str, Any]]
    ) -> tuple[bool, str]:
        """Deterministic citation consistency check using term overlap."""
        if not chunks:
            return True, "no_chunks_to_verify"

        answer_terms = extract_terms(answer)
        if not answer_terms:
            return True, "no_terms_in_answer"

        all_chunk_terms: set[str] = set()
        for chunk in chunks:
            all_chunk_terms |= extract_terms(chunk.get("content", ""))

        overlap = compute_overlap(answer_terms, all_chunk_terms)

        if overlap < 0.08:
            return False, f"low_chunk_overlap:{overlap:.3f}"

        return True, f"overlap_ok:{overlap:.3f}"

    # ── Consistency check ───────────────────────────────────────────

    @staticmethod
    def _check_consistency(original: str, generated: str) -> bool:
        """Basic consistency check — answer should not contradict obvious facts."""
        # Very lightweight: if answer contains URLs but context doesn't, flag it.
        if ("http://" in generated or "https://" in generated) and "http" not in original:
            return False
        return True

    # ── Correction suggestion ───────────────────────────────────────

    async def _suggest_corrections(
        self,
        context: str,
        answer: str,
        verification_result: dict,
        language: str,
    ) -> str:
        """Use LLM to suggest corrections for failed verification."""
        reasons = []
        if verification_result.get("hallucination_score", 0) >= HALLUCINATION_THRESHOLD:
            reasons.append("high hallucination score")
        if not verification_result.get("citation_ok", True):
            reasons.append(verification_result.get("citation_detail", "citation issue"))
        if not verification_result.get("consistency_ok", True):
            reasons.append("consistency issue")

        reason_text = ", ".join(reasons)

        if language == "tr":
            prompt = f"""Asagidaki cevap dogrulama kontrollerinden gecemedi.
Hatalar: {reason_text}

BAGLAM:
{context[:3000]}

HATAL CEVAP:
{answer}

Duzeltilmis cevap:"""
        else:
            prompt = f"""The answer below failed verification checks.
Issues: {reason_text}

CONTEXT:
{context[:3000]}

FAILED ANSWER:
{answer}

Corrected answer:"""

        try:
            return (await self._llm.generate_text(prompt)).strip()
        except Exception as e:
            logger.warning(f"[Verifier] Correction generation failed: {e}")
            return ""

    async def execute(self, payload: dict[str, Any], language: str) -> dict[str, Any]:
        """Execute verification pipeline."""
        initial: VerificationState = {
            "original_content": payload.get("original_content", ""),
            "generated_output": payload.get("generated_output", ""),
            "retrieved_chunks": payload.get("retrieved_chunks", []),
            "language": language,
        }
        final = await self._graph_compiled.ainvoke(initial)
        return {
            "passed": final.get("passed", False),
            "verification_result": final.get("verification_result"),
            "corrections": final.get("corrections"),
        }

    async def verify(
        self,
        original_content: str,
        generated_output: str,
        retrieved_chunks: list[dict[str, Any]] | None = None,
        language: str = "tr",
    ) -> dict[str, Any]:
        """Convenience method for direct verification calls."""
        return await self.execute(
            {
                "original_content": original_content,
                "generated_output": generated_output,
                "retrieved_chunks": retrieved_chunks or [],
            },
            language,
        )
