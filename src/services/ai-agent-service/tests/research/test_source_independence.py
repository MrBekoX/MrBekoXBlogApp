"""Page and claim multiplicity must not inflate independent publisher counts."""

from datetime import datetime, timezone

from agent_core.research.models import ClaimEvidenceRecord, ClaimRecord, ResearchFlowConfig, SourceLedgerEntry, SupportKind
from agent_core.research.report import build_findings

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def claim(index):
    return ClaimRecord(claim_id=f"claim-{index}", article_id="article", article_revision=1,
                       text=f"Source-grounded claim {index}", char_start=0, char_end=20)


def entry(index, url):
    return SourceLedgerEntry(source_id=f"source-{index}", url=url, final_url=url,
                             accessed_at=NOW, content_hash="a" * 64, artifact_id=f"artifact-{index}")


def evidence(index, claim_id, source, support=SupportKind.SUPPORTS):
    return ClaimEvidenceRecord(evidence_id=f"evidence-{index}", claim_id=claim_id, source_id=source.source_id,
                               url=source.final_url, excerpt="Source-grounded supporting passage.",
                               char_start=0, char_end=35, source_content_hash=source.content_hash,
                               support=support, rationale="Verified relation")


def findings(claims, records, entries, language="en"):
    return build_findings(run_id="run", sub_questions=["General evidence assessment"], claims=claims,
                          evidence=records, entries_by_id={source.source_id: source for source in entries},
                          language=language, config=ResearchFlowConfig(), now=NOW)[0]


def test_multiple_pages_of_one_publisher_are_not_independent_publishers():
    first, second = entry(1, "https://docs.python.org/guide"), entry(2, "https://www.python.org/notes")
    result = findings([claim(1)], [evidence(1, "claim-1", first), evidence(2, "claim-1", second)], [first, second])
    assert "1 independent publisher group(s) (2 source page(s))" in result.summary
    assert result.confidence == "medium"
    assert result.evidence_ids == ["evidence-1", "evidence-2"]


def test_one_page_supporting_multiple_claims_is_counted_once():
    source = entry(1, "https://docs.python.org/guide")
    result = findings([claim(1), claim(2)], [evidence(1, "claim-1", source), evidence(2, "claim-2", source)], [source])
    assert "1 independent publisher group(s) (1 source page(s))" in result.summary
    assert result.confidence == "medium"
    # Claim-level evidence identity is retained despite page-level counting.
    assert len(result.evidence_ids) == 2


def test_refetching_one_final_page_with_another_source_id_does_not_add_a_page():
    first = entry(1, "https://docs.python.org/guide#first")
    second = entry(2, "https://docs.python.org/guide#second")
    result = findings([claim(1)], [evidence(1, "claim-1", first), evidence(2, "claim-1", second)], [first, second])
    assert "1 independent publisher group(s) (1 source page(s))" in result.summary
    assert result.confidence == "medium"


def test_distinct_publishers_preserve_high_confidence_and_turkish_wording():
    first, second = entry(1, "https://docs.python.org/guide"), entry(2, "https://learn.microsoft.com/guide")
    result = findings([claim(1)], [evidence(1, "claim-1", first), evidence(2, "claim-1", second)], [first, second], "tr")
    assert "2 bağımsız yayıncı grubu (2 kaynak sayfası)" in result.summary
    assert result.confidence == "high"


def test_repeated_contradictions_from_one_page_do_not_inflate_page_count():
    source = entry(1, "https://docs.python.org/guide")
    result = findings([claim(1), claim(2)], [evidence(1, "claim-1", source, SupportKind.CONTRADICTS),
                      evidence(2, "claim-2", source, SupportKind.CONTRADICTS)], [source])
    assert "0 independent publisher group(s) (0 source page(s))" in result.summary
    assert "; 1 source page(s) contradict" in result.summary
    assert result.confidence == "low"


def test_unclear_only_records_do_not_produce_a_finding_without_evidence_ids():
    source = entry(1, "https://docs.python.org/guide")
    result = build_findings(run_id="run", sub_questions=["Unresolved question"], claims=[claim(1)],
                            evidence=[evidence(1, "claim-1", source, SupportKind.UNCLEAR)],
                            entries_by_id={source.source_id: source}, language="en", config=ResearchFlowConfig(), now=NOW)
    assert result == []
