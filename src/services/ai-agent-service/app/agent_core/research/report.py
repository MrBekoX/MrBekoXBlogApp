"""Araştırma raporu üretimi ve iddia–kaynak eşleşme kontrolü (plan A7 adım 8-9).

Rapor bölüm kümesi plan A7'nin listesidir: kısa sonuç, kapsam, tarih,
makaleyle ilişki, karşılaştırma, bulgular, belirsizlikler, kaynaklar ve
tamamlanma durumu. ``strip_fabricated_sources`` model çıktısındaki kaynak
kimliği etiketlerini kayıt defteriyle karşılaştırır: kimliği olmayan etiket
metinden çıkarılır — **raporda uydurma kaynak kimliği bulunmasının yapısal
yolu yoktur** (plan kabul ölçütü).

Bulgular yalnız kanıt taşıyan alt sorulardan üretilir; kanıtsız iddia bulgu
olmaz, belirsizlik olarak bildirilir (plan A7: "desteklenmeyen iddiayı çıkar
veya belirsizleştir").
"""

from __future__ import annotations

import re
from datetime import datetime

from ..models import ResearchFinding
from ..web.assess import publisher_group_of
from .models import (
    ClaimEvidenceRecord,
    ClaimRecord,
    ComparisonNote,
    ResearchFlowConfig,
    ResearchReport,
    SourceLedgerEntry,
    SupportKind,
)

__all__ = [
    "SOURCE_ID_PATTERN",
    "assemble_report",
    "build_comparison_notes",
    "build_findings",
    "strip_fabricated_sources",
]

#: A1 kanonik web kaynak kimliği biçimi: ``web:<sha256[:16]>:<YYYYMMDDTHHMMSSZ>``.
SOURCE_ID_PATTERN = re.compile(r"web:[0-9a-f]{16}:\d{8}T\d{6}Z")

_COMPLETION_TAIL = (
    "Kanıt destek sınıflaması sezgiseldir; hatasız doğruluk garantisi yoktur."
)


def strip_fabricated_sources(
    text: str, valid_ids: set[str]
) -> tuple[str, list[str]]:
    """Metindeki kaynak kimliği etiketlerini kayıt defteriyle eşler.

    Kayıt defterinde olmayan kimlik etiketi metinden çıkarılır ve çıkarılan
    kimlik listesi döner (kontrol düğümü bunu hata izine yazar).
    """
    removed: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        marker = match.group()
        if marker in valid_ids:
            return marker
        removed.append(marker)
        return ""

    cleaned = SOURCE_ID_PATTERN.sub(_replace, text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned, removed


def build_findings(
    *,
    run_id: str,
    sub_questions: list[str],
    claims: list[ClaimRecord],
    evidence: list[ClaimEvidenceRecord],
    entries_by_id: dict[str, SourceLedgerEntry],
    language: str,
    config: ResearchFlowConfig,
    now: datetime,
) -> list[ResearchFinding]:
    """Kanıt taşıyan alt sorular için ara bulgu üretir (plan A7 adım 8).

    Güven düzeyi: iki veya daha fazla bağımsız yayıncı grubundan ``supports``
    kanıtı → ``high``; tek grup → ``medium``; yalnız belirsiz/çelişki kanıtı
    → ``low``. Kanıtsız alt soru bulgu üretmez (belirsizliğe düşer).
    """
    is_tr = language.casefold().startswith("tr")
    findings: list[ResearchFinding] = []

    def evidence_for(sub_index: int) -> list[ClaimEvidenceRecord]:
        if sub_index == 0:
            claim_ids = {claim.claim_id for claim in claims}
        else:
            if sub_index - 1 >= len(claims):
                return []
            claim_ids = {claims[sub_index - 1].claim_id}
        return [record for record in evidence if record.claim_id in claim_ids]

    for index, question in enumerate(sub_questions):
        related = evidence_for(index)
        supporting = [r for r in related if r.support is SupportKind.SUPPORTS]
        contradicting = [r for r in related if r.support is SupportKind.CONTRADICTS]
        if not related:
            continue  # kanıtsız alt soru bulgu üretmez; belirsizlik bölümüne düşer
        groups = {publisher_group_of(entries_by_id[r.source_id].final_url) for r in supporting}
        if len(groups) >= 2:
            confidence = "high"
        elif len(supporting) >= 1:
            confidence = "medium"
        else:
            confidence = "low"
        if is_tr:
            summary = f"{len(supporting)} bağımsız kaynak iddiayı destekliyor"
            if contradicting:
                summary += f"; {len(contradicting)} kaynak çelişiyor"
            summary += "."
        else:
            summary = f"{len(supporting)} independent source(s) support the claim"
            if contradicting:
                summary += f"; {len(contradicting)} contradict it"
            summary += "."
        ordered = supporting + contradicting
        findings.append(
            ResearchFinding(
                finding_id=f"find:{run_id}:{index}",
                run_id=run_id,
                sub_question=question[:20000],
                summary=summary,
                confidence=confidence,  # type: ignore[arg-type]
                evidence_ids=[r.evidence_id for r in ordered[: config.max_evidence_per_finding]],
                created_at=now,
            )
        )
    return findings


def build_comparison_notes(
    claims: list[ClaimRecord],
    evidence: list[ClaimEvidenceRecord],
    *,
    language: str,
) -> list[ComparisonNote]:
    """Bulgunun makale iddialarıyla ve alternatiflerle karşılaştırmasını üretir."""
    is_tr = language.casefold().startswith("tr")
    notes: list[ComparisonNote] = []
    for claim in claims:
        related = [record for record in evidence if record.claim_id == claim.claim_id]
        supporting = sum(1 for r in related if r.support is SupportKind.SUPPORTS)
        contradicting = sum(1 for r in related if r.support is SupportKind.CONTRADICTS)
        unclear = sum(1 for r in related if r.support is SupportKind.UNCLEAR)
        if contradicting and supporting:
            relation = "contradicts"
            detail = (
                f"karışık kanıt: {supporting} destek, {contradicting} çelişki"
                if is_tr
                else f"mixed evidence: {supporting} support, {contradicting} contradict"
            )
        elif contradicting:
            relation = "contradicts"
            detail = (
                f"{contradicting} kaynak makale iddiasıyla çelişiyor"
                if is_tr
                else f"{contradicting} source(s) contradict the article claim"
            )
        elif supporting:
            relation = "agrees"
            detail = (
                f"{supporting} kaynak makale iddiasıyla uyumlu"
                if is_tr
                else f"{supporting} source(s) agree with the article claim"
            )
        else:
            relation = "unclear"
            detail = (
                f"kanıt belirsiz ({unclear} belirsiz kayıt)"
                if is_tr
                else f"evidence unclear ({unclear} unclear record)"
            )
        notes.append(
            ComparisonNote(
                claim_id=claim.claim_id,
                relation=relation,  # type: ignore[arg-type]
                detail=detail,
            )
        )
    return notes


def assemble_report(
    *,
    report_id: str,
    run_id: str,
    question: str,
    summary: str,
    sub_questions: list[str],
    claims: list[ClaimRecord],
    snapshot_title: str | None,
    article_revision: int | None,
    comparison: list[ComparisonNote],
    findings: list[ResearchFinding],
    uncovered_claim_texts: list[str],
    unresolved_sub_questions: list[str],
    cited_entries: list[SourceLedgerEntry],
    completeness: str,
    completeness_note: str,
    language: str,
    generated_at: datetime,
) -> tuple[ResearchReport, str]:
    """Yapılandırılmış raporu ve tam metnini üretir; bölüm kümesi plan A7'dendir."""
    is_tr = language.casefold().startswith("tr")

    def tr_or(tr: str, en: str) -> str:
        return tr if is_tr else en

    claim_count = len(claims)
    scope_lines = [
        tr_or(f"- Soru: {question}", f"- Question: {question}"),
        tr_or(
            f"- Alt sorular: {len(sub_questions)} (sınır: politika)",
            f"- Sub-questions: {len(sub_questions)} (bounded by policy)",
        ),
        tr_or(
            f"- Makale: {snapshot_title or '?'} (revizyon {article_revision}); "
            f"{claim_count} iddia çıkarıldı",
            f"- Article: {snapshot_title or '?'} (revision {article_revision}); "
            f"{claim_count} claims extracted",
        ),
    ]
    article_relation = tr_or(
        f"Rapor, {snapshot_title or 'makale'} makalesinin {claim_count} iddiasını dış "
        "kanıtla karşılaştırır; iddia başına sonuç Karşılaştırma bölümündedir.",
        f"This report compares {claim_count} claim(s) of '{snapshot_title or 'the article'} "
        "with external evidence; per-claim results are in the Comparison section.",
    )
    comparison_lines = [
        f"- {note.claim_id}: {note.relation} — {note.detail}" for note in comparison
    ]
    finding_lines: list[str] = []
    for finding in findings:
        finding_lines.append(
            tr_or(
                f"### {finding.sub_question}\n\n{finding.summary} (güven: {finding.confidence}; "
                f"kanıtlar: {', '.join(finding.evidence_ids) or '—'})",
                f"### {finding.sub_question}\n\n{finding.summary} (confidence: {finding.confidence}; "
                f"evidence: {', '.join(finding.evidence_ids) or '—'})",
            )
        )
    uncertainties: list[str] = [
        tr_or(
            f"Makale iddiası dış kanıtla desteklenemedi: {text}",
            f"Article claim not supported by external evidence: {text}",
        )
        for text in uncovered_claim_texts
    ] + [
        tr_or(f"Karşılanmayan alt soru: {q}", f"Unresolved sub-question: {q}")
        for q in unresolved_sub_questions
    ]
    uncertainties.append(_COMPLETION_TAIL)

    source_lines = [
        f"- [{entry.source_id}] {entry.title or tr_or('başlıksız', 'untitled')} — {entry.final_url}"
        + (
            f" ({tr_or('erişim', 'accessed')}: {entry.accessed_at.strftime('%Y-%m-%d %H:%M UTC')})"
        )
        + (
            f" [{tr_or('tür', 'type')}: {entry.source_type}]"
            if entry.source_type
            else ""
        )
        for entry in cited_entries
    ]

    completeness_label = (
        tr_or("tam", "complete") if completeness == "complete" else tr_or("kısmi", "partial")
    )

    sections = [
        f"# {tr_or('Derin Araştırma Raporu', 'Deep Research Report')}",
        tr_or("## Kısa sonuç", "## Summary") + f"\n\n{summary.strip()}",
        tr_or("## Kapsam", "## Scope") + "\n\n" + "\n".join(scope_lines),
        tr_or("## Tarih", "## Date") + f"\n\n{generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        tr_or("## Makaleyle ilişki", "## Relation to the article") + f"\n\n{article_relation}",
        tr_or("## Karşılaştırma", "## Comparison")
        + "\n\n"
        + ("\n".join(comparison_lines) if comparison_lines else tr_or("- (iddia yok)", "- (no claims)")),
        tr_or("## Bulgular", "## Findings")
        + "\n\n"
        + ("\n\n".join(finding_lines) if finding_lines else tr_or(
            "- Kanıt taşıyan alt soru yok; bulgu üretilmedi.",
            "- No sub-question carried evidence; no findings produced.",
        )),
        tr_or("## Belirsizlikler", "## Uncertainties") + "\n\n" + "\n".join(f"- {u}" for u in uncertainties),
        tr_or("## Kaynaklar", "## Sources")
        + "\n\n"
        + ("\n".join(source_lines) if source_lines else tr_or(
            "- Okunabilen kaynak yok; dış kanıt toplanamadı.",
            "- No readable source; no external evidence collected.",
        )),
        tr_or("## Tamamlanma durumu", "## Completion")
        + f"\n\n{completeness_label} — {completeness_note}",
    ]
    text = "\n\n".join(sections)
    report = ResearchReport(
        report_id=report_id,
        run_id=run_id,
        question=question[:20000],
        summary=summary.strip()[:20000] or tr_or("(kısa sonuç üretilemedi)", "(no summary produced)"),
        scope="\n".join(scope_lines),
        article_relation=article_relation,
        generated_at=generated_at,
        comparison=comparison,
        findings=findings,
        uncertainties=uncertainties,
        sources=[entry.to_source_reference() for entry in cited_entries],
        completeness=completeness,  # type: ignore[arg-type]
        completeness_note=completeness_note[:20000],
        text=text[:200000],
    )
    return report, text
