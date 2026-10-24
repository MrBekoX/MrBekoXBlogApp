"""A7 programatik kontroller ve kanıt değerlendirme birim testleri.

Plan A7: "Programatik kontrol kaynak ID'sinin varlığını, URL eşleşmesini ve
metin aralığını doğrulasın." Bu dosya kontrollerin her bir reddetme nedenini
gerçek kayıtlarla sınar; ayrıca iddia çıkarma, destek sınıflaması (hatasız
doğruluk garantisi yok — tasarım notu) ve rapor kaynak ayıklaması denetlenir.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from agent_core.research.evaluation import (
    classify_support,
    evaluate_claims,
    locate_span,
    verify_claim_evidence,
)
from agent_core.research.models import (
    ClaimEvidenceRecord,
    ClaimRecord,
    ResearchFlowConfig,
    SourceLedgerEntry,
    SupportKind,
)
from agent_core.research.planning import build_sub_questions, extract_claims
from agent_core.research.report import SOURCE_ID_PATTERN, strip_fabricated_sources
from agent_core.state.artifacts import InMemoryArtifactStore

from .evidence_helpers import (
    CLAIM_1,
    CLAIM_2,
    CONFLICT_TEXT,
    GUIDE_TEXT,
    NOW,
    make_research_snapshot,
)

NOW_DT = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _claim_1() -> ClaimRecord:
    return ClaimRecord(
        claim_id="claim:post-queue:7:0",
        article_id="post-queue",
        article_revision=7,
        text=CLAIM_1,
        char_start=0,
        char_end=len(CLAIM_1),
    )


def _entry(text: str, *, source_id: str = "web:0123456789abcdef:20261012T120000Z") -> SourceLedgerEntry:
    return SourceLedgerEntry(
        source_id=source_id,
        url="https://example.com/guide",
        final_url="https://example.com/guide",
        title="Kılavuz",
        accessed_at=NOW,
        content_hash=_digest(text),
        extraction_status="ok",
        full_page_read=True,
        artifact_id=f"sha256:{_digest(text)[:32]}",
    )


# --- İddia çıkarma (plan adım 2) --------------------------------------------------


def test_claim_extraction_is_bounded_and_relevant() -> None:
    snapshot = make_research_snapshot()
    claims = extract_claims(snapshot, "asyncio kuyruk sınırı ve hata yönetimi için güncel öneriler nelerdir?")
    assert 1 <= len(claims) <= ResearchFlowConfig().max_claims
    texts = [claim.text for claim in claims]
    assert CLAIM_1 in texts
    assert CLAIM_2 in texts
    for claim in claims:
        # İddia aralığı makale içindedir ve metinle birebir eşleşir.
        assert 0 <= claim.char_start < claim.char_end <= len(snapshot.content)
        assert snapshot.content[claim.char_start : claim.char_end] == claim.text
        assert claim.claim_id.startswith("claim:post-queue:7:")


def test_sub_questions_are_bounded() -> None:
    claims = extract_claims(make_research_snapshot(), CLAIM_1)
    questions = build_sub_questions("soru?", claims, max_sub_questions=4, language="tr")
    assert questions[0] == "soru?"
    assert len(questions) <= 4
    assert all(q.strip() for q in questions)


# --- Destek sınıflaması (hatasız doğruluk garantisi yok) ---------------------------


def test_support_classification_supports_matching_text() -> None:
    span = locate_span(GUIDE_TEXT, CLAIM_1)
    assert span is not None
    start, end, overlap = span
    assert 0 <= start < end <= len(GUIDE_TEXT)
    support, rationale = classify_support(CLAIM_1, GUIDE_TEXT[start:end], overlap, min_overlap=2)
    assert support is SupportKind.SUPPORTS
    assert "sezgisel" in rationale  # garanti sınırı tasarımda bildirilir


def test_support_classification_flags_numeric_contradiction() -> None:
    span = locate_span(CONFLICT_TEXT, CLAIM_1)
    assert span is not None
    start, end, overlap = span
    span_text = CONFLICT_TEXT[start:end]
    assert "100'dür" in span_text  # iddiadaki 1000 ile çelişen aralık
    support, rationale = classify_support(CLAIM_1, span_text, overlap, min_overlap=2)
    assert support is SupportKind.CONTRADICTS
    assert "sayısal çelişki" in rationale


def test_support_classification_unclear_when_overlap_weak() -> None:
    support, rationale = classify_support(CLAIM_1, "ilgisiz bir cümle içeriği.", 0, min_overlap=2)
    assert support is SupportKind.UNCLEAR
    assert "belirsiz" in rationale


# --- Programatik doğrulama (plan adım 5 kontrolü) -----------------------------------


def _record(entry: SourceLedgerEntry, claim: ClaimRecord, *, text: str) -> ClaimEvidenceRecord:
    span = locate_span(text, claim.text)
    assert span is not None
    start, end, overlap = span
    support, rationale = classify_support(claim.text, text[start:end], overlap, min_overlap=2)
    return ClaimEvidenceRecord(
        evidence_id="ev:test00000000000000000000",
        claim_id=claim.claim_id,
        source_id=entry.source_id,
        url=entry.final_url,
        excerpt=text[start:end],
        char_start=start,
        char_end=end,
        source_content_hash=entry.content_hash,
        support=support,
        rationale=rationale,
    )


def test_verify_accepts_consistent_record() -> None:
    entry = _entry(GUIDE_TEXT)
    claim = _claim_1()
    record = _record(entry, claim, text=GUIDE_TEXT)
    assert verify_claim_evidence(record, {entry.source_id: entry}, GUIDE_TEXT) == []


def test_verify_rejects_fabricated_source_id() -> None:
    entry = _entry(GUIDE_TEXT)
    claim = _claim_1()
    record = _record(entry, claim, text=GUIDE_TEXT)
    fabricated = record.model_copy(update={"source_id": "web:ffffffffffffffff:20260101T000000Z"})
    errors = verify_claim_evidence(fabricated, {entry.source_id: entry}, GUIDE_TEXT)
    assert errors and "kayıt defterinde yok" in errors[0]


def test_verify_rejects_url_mismatch() -> None:
    entry = _entry(GUIDE_TEXT)
    claim = _claim_1()
    record = _record(entry, claim, text=GUIDE_TEXT)
    mismatched = record.model_copy(update={"url": "https://example.com/other"})
    errors = verify_claim_evidence(mismatched, {entry.source_id: entry}, GUIDE_TEXT)
    assert any("URL eşleşmiyor" in message for message in errors)


def test_verify_rejects_span_out_of_bounds() -> None:
    entry = _entry(GUIDE_TEXT)
    claim = _claim_1()
    record = _record(entry, claim, text=GUIDE_TEXT)
    out_of_bounds = record.model_copy(update={"char_end": len(GUIDE_TEXT) + 50})
    errors = verify_claim_evidence(out_of_bounds, {entry.source_id: entry}, GUIDE_TEXT)
    assert any("sınırların dışında" in message for message in errors)


def test_verify_rejects_excerpt_mismatch() -> None:
    entry = _entry(GUIDE_TEXT)
    claim = _claim_1()
    record = _record(entry, claim, text=GUIDE_TEXT)
    altered = record.model_copy(update={"excerpt": "metinde olmayan alıntı."})
    errors = verify_claim_evidence(altered, {entry.source_id: entry}, GUIDE_TEXT)
    assert any("birebir bulunamadı" in message for message in errors)


def test_verify_rejects_content_hash_mismatch() -> None:
    entry = _entry(GUIDE_TEXT)
    claim = _claim_1()
    record = _record(entry, claim, text=GUIDE_TEXT)
    other_entry = entry.model_copy(update={"content_hash": _digest(CONFLICT_TEXT)})
    errors = verify_claim_evidence(record, {entry.source_id: other_entry}, GUIDE_TEXT)
    assert any("hash" in message for message in errors)


def test_verify_reports_missing_source_text() -> None:
    entry = _entry(GUIDE_TEXT)
    claim = _claim_1()
    record = _record(entry, claim, text=GUIDE_TEXT)
    errors = verify_claim_evidence(record, {entry.source_id: entry}, None)
    assert any("erişilemedi" in message for message in errors)


# --- Değerlendirme döngüsü: uydurma kayıt kanıt havuzuna girmez ---------------------


def test_evaluate_claims_are_idempotent_on_rerun() -> None:
    """İçerik adresli kanıt kimliği: tekrar değerlendirme kopya üretmez (A2 sözleşmesi)."""
    artifacts = InMemoryArtifactStore()
    entry = _entry(GUIDE_TEXT)
    artifacts.put("run-1", "source_page", GUIDE_TEXT, created_at=NOW_DT)
    claim = _claim_1()

    evidence, drops = evaluate_claims(
        [claim], [entry], artifacts, "run-1", config=ResearchFlowConfig(), now=NOW_DT
    )
    again, drops_again = evaluate_claims(
        [claim], [entry], artifacts, "run-1", config=ResearchFlowConfig(), now=NOW_DT
    )
    assert evidence and not drops and not drops_again
    assert [record.evidence_id for record in evidence] == [
        record.evidence_id for record in again
    ]


def test_evaluate_claims_skips_unreadable_and_duplicate_sources() -> None:
    artifacts = InMemoryArtifactStore()
    entry = _entry(GUIDE_TEXT)
    artifacts.put("run-1", "source_page", GUIDE_TEXT, created_at=NOW_DT)
    snippet_only = entry.model_copy(
        update={
            "source_id": "web:1111111111111111:20261012T120000Z",
            "full_page_read": False,
        }
    )
    duplicate = entry.model_copy(
        update={
            "source_id": "web:2222222222222222:20261012T120000Z",
            "duplicate_of": entry.source_id,
        }
    )
    claim = _claim_1()

    evidence, _ = evaluate_claims(
        [claim], [entry, snippet_only, duplicate], artifacts, "run-1",
        config=ResearchFlowConfig(), now=NOW_DT,
    )
    assert evidence
    assert {record.source_id for record in evidence} == {entry.source_id}


# --- Rapor kaynak ayıklaması (plan kabul ölçütü) ------------------------------------


def test_strip_fabricated_sources_removes_unknown_ids() -> None:
    valid = {"web:0123456789abcdef:20261012T120000Z"}
    text = (
        "Kanıt [web:0123456789abcdef:20261012T120000Z] destekler; "
        "[web:ffffffffffffffff:20260101T000000Z] uydurma."
    )
    cleaned, removed = strip_fabricated_sources(text, valid)
    assert "web:0123456789abcdef:20261012T120000Z" in cleaned
    assert "web:ffffffffffffffff:20260101T000000Z" not in cleaned
    assert removed == ["web:ffffffffffffffff:20260101T000000Z"]


def test_source_id_pattern_matches_canonical_shape_only() -> None:
    text = "geçerli web:abcdef0123456789:20261012T120000Z ve tarih 2026-10-12 karışmaz."
    assert SOURCE_ID_PATTERN.findall(text) == ["web:abcdef0123456789:20261012T120000Z"]
