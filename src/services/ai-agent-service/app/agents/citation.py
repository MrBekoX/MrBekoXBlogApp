"""Citation system — deterministic term-overlap citation tracking."""

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 10]


def extract_terms(text: str) -> set[str]:
    """Extract normalized terms (4+ chars) from text."""
    return {t.lower() for t in re.findall(r'[a-zA-Z0-9_]{4,}', text)}


def compute_overlap(terms_a: set[str], terms_b: set[str]) -> float:
    """Compute Jaccard-like overlap between two term sets."""
    if not terms_a or not terms_b:
        return 0.0
    intersection = terms_a & terms_b
    return len(intersection) / max(len(terms_a), 1)


def build_citations(
    answer: str,
    retrieved_chunks: list[dict[str, Any]],
    min_overlap: float = 0.15,
) -> list[dict[str, Any]]:
    """Match answer sentences to retrieved chunks using term overlap.

    This is a deterministic, no-LLM-call citation system. Each answer sentence
    is compared to each retrieved chunk; if the term overlap exceeds
    ``min_overlap``, a citation link is created.

    Args:
        answer: The generated answer text.
        retrieved_chunks: List of dicts with at least ``content`` key,
            optionally ``source``, ``chunk_id``.
        min_overlap: Minimum overlap ratio to count as a citation.

    Returns:
        List of citation dicts with ``sentence_idx``, ``chunk_id``, ``overlap``.
    """
    sentences = extract_sentences(answer)
    citations: list[dict[str, Any]] = []

    for sent_idx, sentence in enumerate(sentences):
        sent_terms = extract_terms(sentence)
        if not sent_terms:
            continue

        best_overlap = 0.0
        best_chunk_id: str | None = None

        for chunk in retrieved_chunks:
            chunk_text = chunk.get("content", "")
            chunk_terms = extract_terms(chunk_text)
            overlap = compute_overlap(sent_terms, chunk_terms)

            if overlap > best_overlap:
                best_overlap = overlap
                best_chunk_id = chunk.get("chunk_id", chunk.get("source", f"chunk_{id(chunk)}"))

        if best_overlap >= min_overlap and best_chunk_id:
            citations.append({
                "sentence_idx": sent_idx,
                "sentence_preview": sentence[:80],
                "chunk_id": best_chunk_id,
                "overlap": round(best_overlap, 3),
            })

    return citations


def annotate_answer_with_citations(
    answer: str,
    citations: list[dict[str, Any]],
) -> str:
    """Append citation markers [1], [2], ... to the answer text.

    Non-destructive: only appends a citations section at the end.
    """
    if not citations:
        return answer

    # Group by chunk_id to assign unique citation numbers
    chunk_to_num: dict[str, int] = {}
    for c in citations:
        cid = c["chunk_id"]
        if cid not in chunk_to_num:
            chunk_to_num[cid] = len(chunk_to_num) + 1

    footer_lines = ["\n\n---\nSources:"]
    for cid, num in chunk_to_num.items():
        footer_lines.append(f"[{num}] {cid}")

    return answer + "\n".join(footer_lines)
