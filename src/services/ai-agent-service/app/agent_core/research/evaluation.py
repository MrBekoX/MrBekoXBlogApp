"""Kanıt eşleme, destek sınıflaması ve programatik doğrulama (plan A7 adım 5-6).

İki katman vardır:

1. **Sezgisel destek sınıflaması** — ``locate_span`` kaynak metninde iddiayla
   en çok terim paylaşan aralığı bulur; ``classify_support`` ortak terim
   sayısı, sayısal çelişki ve olumsuzlama işaretleriyle ``supports`` /
   ``contradicts`` / ``unclear`` kararı verir. Bu katman **hatasız doğruluk
   garantisi TAŞIMAZ** (plan A7: "Anlamsal destek değerlendirmesinin hatasız
   doğruluk garantisi vermediğini tasarımda belirt"); gerekçe metninde
   "sezgisel" etiketi taşır [AC-SELF-RAG#C2].
2. **Programatik doğrulama** — ``verify_claim_evidence`` kaynak ID varlığını,
   URL eşleşmesini, içerik hash'ini ve metin aralığını mekanik olarak
   denetler; hatalı kayıt kanıt havuzuna girmez (plan A7: "Programatik
   kontrol kaynak ID'sinin varlığını, URL eşleşmesini ve metin aralığını
   doğrulasın"). Bu katman deterministiktir.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from ..content.anchors import fold_text
from ..qa.text import salient_tokens
from ..state.artifacts import ArtifactStore
from ..state.events import NodeErrorRecord
from .models import (
    ClaimEvidenceRecord,
    ClaimRecord,
    ResearchFlowConfig,
    SourceLedgerEntry,
    SupportKind,
)
from .planning import iter_sentences

__all__ = [
    "assess_coverage",
    "build_claim_evidence",
    "classify_support",
    "evaluate_claims",
    "locate_span",
    "verify_claim_evidence",
]

#: Olumsuzlama işaretleri (katlanmış biçimde karşılaştırılır); kaba sezgisel küme.
_NEGATION_MARKERS = (
    "degil",
    "yanlis",
    "aksine",
    "tersine",
    "onerilmez",
    "tavsiye edilmez",
    "kacinmalisiniz",
    "kacinilmeli",
    "asla",
    "not ",
    "n't",
    "wrong",
    "incorrect",
    "contrary",
    "instead",
    "avoid",
    "never",
    "deprecated",
)

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _norm_number(value: str) -> str:
    """Tek sayıyı normalize eder: ondalık virgülü noktaya çevirir, gereksiz
    sıfırları kırpır ("1.0" → "1"). Tam sayı sonundaki sıfır KORUNUR (100 ≠ 1000)."""
    normalized = value.replace(",", ".")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _norm_numbers(text: str) -> set[str]:
    """Sayıları normalize edip küme olarak döndürür (sayısal çelişki denetimi)."""
    return {_norm_number(value) for value in _NUMBER_RE.findall(text)}


def _has_negation(text: str) -> bool:
    folded = fold_text(text)
    return any(marker in folded for marker in _NEGATION_MARKERS)


def locate_span(
    source_text: str,
    claim_text: str,
    *,
    min_overlap: int = 1,
) -> tuple[int, int, int] | None:
    """Kaynak metninde iddia terimleriyle en çok örtüşen cümle aralığını bulur.

    Dönen değer ``(char_start, char_end, overlap)``; eşiği geçen aralık yoksa
    ``None``. Aralık orijinal metin indekslerindedir ve programatik aralık
    denetiminin girdisidir.
    """
    claim_tokens = set(salient_tokens(fold_text(claim_text), min_length=3))
    if not claim_tokens:
        return None
    best: tuple[int, int, int] | None = None
    for char_start, char_end, segment in iter_sentences(source_text):
        tokens = set(salient_tokens(fold_text(segment), min_length=3))
        overlap = len(claim_tokens & tokens)
        if overlap < min_overlap:
            continue
        if best is None or overlap > best[2]:
            best = (char_start, char_end, overlap)
    return best


def classify_support(
    claim_text: str,
    span_text: str,
    overlap: int,
    *,
    min_overlap: int,
) -> tuple[SupportKind, str]:
    """Sezgisel destek sınıflaması; karar ve insan-okur gerekçe döndürür.

    GARANTİ YOKTUR: kural tabanlıdır ve yanlış pozitif/negatif üretebilir;
    gerekçedeki "sezgisel" etiketi bu sınırı taşır. ``unclear`` kanıt bulguya
    bağlanmaz, belirsizlik olarak raporlanır.
    """
    claim_numbers = _norm_numbers(claim_text)
    span_numbers = _norm_numbers(span_text)
    if claim_numbers and span_numbers and not (claim_numbers & span_numbers):
        return SupportKind.CONTRADICTS, (
            f"sayısal çelişki: iddia {sorted(claim_numbers)}, kaynak {sorted(span_numbers)} (sezgisel sınıflama)"
        )
    if _has_negation(span_text) and not _has_negation(claim_text):
        return SupportKind.CONTRADICTS, (
            "kaynak aralığı olumsuzlama taşıyor, iddia taşımıyor (sezgisel sınıflama)"
        )
    if overlap >= min_overlap:
        return SupportKind.SUPPORTS, (
            f"kaynak aralığı iddia terimleriyle {overlap} ortak anlamlı terim taşıyor (sezgisel sınıflama)"
        )
    return SupportKind.UNCLEAR, (
        f"kaynak aralığıyla yalnız {overlap} ortak terim; destek belirsiz (sezgisel sınıflama)"
    )


def build_claim_evidence(
    claim: ClaimRecord,
    entry: SourceLedgerEntry,
    *,
    char_start: int,
    char_end: int,
    excerpt: str,
    support: SupportKind,
    rationale: str,
) -> ClaimEvidenceRecord:
    """İçerik adresli kanıt kaydı üretir; tekrar değerlendirme aynı kimliği verir."""
    digest = hashlib.sha256(
        f"{claim.claim_id}|{entry.source_id}|{char_start}|{char_end}|{support.value}".encode("utf-8")
    ).hexdigest()
    return ClaimEvidenceRecord(
        evidence_id=f"ev:{digest[:24]}",
        claim_id=claim.claim_id,
        source_id=entry.source_id,
        url=entry.final_url,
        excerpt=excerpt[:2000],
        char_start=char_start,
        char_end=char_end,
        source_content_hash=entry.content_hash,
        support=support,
        rationale=rationale,
    )


def verify_claim_evidence(
    record: ClaimEvidenceRecord,
    entries_by_id: dict[str, SourceLedgerEntry],
    source_text: str | None,
) -> list[str]:
    """Programatik kontrol: boş liste = kayıt geçerli; dolu liste = düşme nedenleri.

    Denetlenen alanlar (plan A7): kaynak ID varlığı, URL eşleşmesi, içerik
    hash'i (source_revision yerine A6'da content_hash taşınır), metin aralığı
    sınırları ve aralığın kaynak metninde birebir varlığı.
    """
    errors: list[str] = []
    entry = entries_by_id.get(record.source_id)
    if entry is None:
        return [f"kaynak kimliği kayıt defterinde yok (uydurma olabilir): {record.source_id}"]
    if record.url != entry.final_url:
        errors.append(f"URL eşleşmiyor: kayıt {record.url!r}, kayıt defteri {entry.final_url!r}")
    if record.source_content_hash != entry.content_hash:
        errors.append("kaynak içerik hash'i kayıt defteriyle uyuşmuyor")
    if source_text is None:
        errors.append(f"kaynak metnine erişilemedi: artifact {entry.artifact_id}")
        return errors
    if not (0 <= record.char_start < record.char_end <= len(source_text)):
        errors.append(
            f"metin aralığı sınırların dışında: [{record.char_start},{record.char_end}) "
            f"kaynak uzunluğu {len(source_text)}"
        )
        return errors
    if source_text[record.char_start : record.char_end] != record.excerpt:
        errors.append("metin aralığı kaynak metinde birebir bulunamadı")
    return errors


def evaluate_claims(
    claims: list[ClaimRecord],
    entries: list[SourceLedgerEntry],
    artifacts: ArtifactStore,
    run_id: str,
    *,
    config: ResearchFlowConfig,
    now: datetime | None = None,
) -> tuple[list[ClaimEvidenceRecord], list[NodeErrorRecord]]:
    """Tüm iddia × kaynak matrisini değerlendirir; geçerli kanıtları döndürür.

    Yalnız tam sayfa okunmuş, içeriği çıkarılmış ve kopya olmayan kayıt
    girişleri değerlendirilir; içerik hash'i tekrarları ilk girişte düşer.
    Programatik doğrulamayı geçemeyen kayıtlar hata iziyle atılır — uydurma
    kaynak kimliğinin kanıt havuzuna girmesinin yapısal yolu yoktur.
    """
    collected_at = now or datetime.now(timezone.utc)
    usable: list[SourceLedgerEntry] = []
    seen_hashes: set[str] = set()
    for entry in entries:
        if not entry.full_page_read or entry.extraction_status != "ok":
            continue
        if entry.duplicate_of is not None or entry.content_hash in seen_hashes:
            continue
        seen_hashes.add(entry.content_hash)
        usable.append(entry)
    entries_by_id = {entry.source_id: entry for entry in usable}

    evidence: list[ClaimEvidenceRecord] = []
    drops: list[NodeErrorRecord] = []
    for claim in claims:
        for entry in usable:
            try:
                source_text = artifacts.get(run_id, entry.artifact_id)
            except KeyError:
                drops.append(
                    NodeErrorRecord(
                        error_id=f"drop:{claim.claim_id}:{entry.source_id}:artifact",
                        node="research.evaluate",
                        code="not_found",
                        message=f"kaynak metni depoda yok: {entry.artifact_id}",
                        occurred_at=collected_at,
                    )
                )
                continue
            span = locate_span(source_text, claim.text)
            if span is None:
                continue
            char_start, char_end, overlap = span
            excerpt = source_text[char_start:char_end]
            support, rationale = classify_support(
                claim.text, excerpt, overlap, min_overlap=config.min_claim_overlap
            )
            record = build_claim_evidence(
                claim,
                entry,
                char_start=char_start,
                char_end=char_end,
                excerpt=excerpt,
                support=support,
                rationale=rationale,
            )
            errors = verify_claim_evidence(record, entries_by_id, source_text)
            if errors:
                drops.append(
                    NodeErrorRecord(
                        error_id=f"drop:{record.evidence_id}",
                        node="research.evaluate",
                        code="validation_error",
                        message="; ".join(errors),
                        occurred_at=collected_at,
                    )
                )
                continue
            evidence.append(record)
    return evidence, drops


def assess_coverage(
    claims: list[ClaimRecord],
    evidence: list[ClaimEvidenceRecord],
    sub_questions: list[str],
    *,
    round_number: int,
) -> "tuple[set[str], set[str], list[str]]":
    """Kapsam boşluğu ve çelişki kümelerini hesaplar (plan A7 adım 6).

    Dönen değer: (karşılanmayan iddia kimlikleri, çelişkili iddia kimlikleri,
    karşılanmayan alt sorular). İlk alt soru kullanıcı sorusudur: hiçbir iddia
    destek kanıtı taşımıyorsa karşılanmamış sayılır; ``i > 0`` alt sorular
    ``claims[i-1]`` iddiasına bağlıdır.
    """
    supported = {record.claim_id for record in evidence if record.support is SupportKind.SUPPORTS}
    contradicted = {record.claim_id for record in evidence if record.support is SupportKind.CONTRADICTS}
    uncovered = {claim.claim_id for claim in claims} - supported
    unresolved: list[str] = []
    if not supported:
        unresolved.append(sub_questions[0])
    for index in range(1, len(sub_questions)):
        if index - 1 < len(claims) and claims[index - 1].claim_id in uncovered:
            unresolved.append(sub_questions[index])
    return uncovered, contradicted, unresolved
