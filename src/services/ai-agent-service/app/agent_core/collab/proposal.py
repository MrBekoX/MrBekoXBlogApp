"""ActionProposal üretimi: düzenlenebilir özet + içerik hash'i (plan A9).

Plan A9: "Düzenlenebilir özet ve içerik hash'i olan ActionProposal oluştur."

SINIR (bu fazın sözleşmesi): burada yalnız ÖNERİ üretilir. Agent backend'e
talep KAYDEtmez, e-posta GÖNDERMEZ; kayıt/onay B9/B10'dadır. Önerinin
``base_content_hash`` alanı dayandığı makale revizyonunu sabitler; ek olarak
ONAY SÜRÜMÜ HASH'İ (dönüşteki ``proposal_content_hash``) B9 backend'in tek
tanımına bağlıdır: düzenlenebilir ÖZET metninin UTF-8 SHA-256 özeti (lowercase
hex) — backend karşılığı ``AgentCollaborationContentHash.Compute(summary)``.
Backend yalnız özet metnini kalıcılar ve onay isteğini bu hash'e karşı
doğrular; hash kavramının ikiye bölünmesi (özet vs. gövde) sürüm bağını
kırardı (W6 F5 bulgusu). Onay farklı bir sürüme işaret ederse red edilir
(B9: kayıt "belirli proposal sürümüne bağlıdır").
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ..errors import AgentErrorCode, PortError
from ..models import ActionProposal, ExecutionContext, compute_content_hash
from .models import CollaborationDetails, PurposeKind

__all__ = ["build_collab_proposal", "purpose_label", "new_proposal_id"]


def new_proposal_id() -> str:
    """Kanonik UUID (RFC 4122 ``D`` biçimi) proposal kimliği üretir.

    W6 bütünleştirme kuralı: sözleşmedeki ``identifier`` serbest string olsa da
    B9 backend hattı proposal kimliğini ``Guid`` olarak kalıcılar ve
    ``agent.action.proposed`` projection'ı kimliği ``Guid.Parse`` ile çözer
    (``AgentEventProjectionConsumer.BuildProposalUpsert``). ``prop-<hex>``
    biçimi tüketici tarafında ``FormatException`` → DLQ üretirdi; bu yüzden
    üretici KANONİK UUID taahhüdüne bağlıdır (test kanıtı:
    ``tests/guidance/test_collab_flow.py::test_generated_proposal_id_is_canonical_uuid``).
    """

    return str(uuid.uuid4())


def purpose_label(details: CollaborationDetails, language: str) -> str:
    """Amaç etiketi: kategori etiketi veya kullanıcının kendi notu."""
    if details.purpose is PurposeKind.OTHER and details.purpose_note:
        return details.purpose_note
    if details.purpose is not None:
        return details.purpose.label(language)
    return details.purpose_note or "?"


def _compose_summary(details: CollaborationDetails, language: str) -> str:
    turkish = language.casefold().startswith("tr")
    label = purpose_label(details, language)
    if turkish:
        return f"İş birliği önerisi — {label}. Kapsam: {details.scope}. Takvim: {details.timeline}."
    return (
        f"Collaboration proposal — {label}. Scope: {details.scope}. "
        f"Timeline: {details.timeline}."
    )


def _compose_content(details: CollaborationDetails, language: str) -> str:
    turkish = language.casefold().startswith("tr")
    label = purpose_label(details, language)
    lines: list[str]
    if turkish:
        lines = [
            "İş birliği talebi (öneri; gönderim açık onaydan sonra yapılır)",
            "",
            f"Amaç: {label}",
            f"Kapsam: {details.scope}",
            f"Takvim: {details.timeline}",
        ]
        if details.budget:
            lines.append(f"Bütçe: {details.budget}")
        lines.append(f"İletişim: {details.contact}")
    else:
        lines = [
            "Collaboration request (proposal; submitted only after explicit approval)",
            "",
            f"Purpose: {label}",
            f"Scope: {details.scope}",
            f"Timeline: {details.timeline}",
        ]
        if details.budget:
            lines.append(f"Budget: {details.budget}")
        lines.append(f"Contact: {details.contact}")
    return "\n".join(lines)


def build_collab_proposal(
    context: ExecutionContext,
    details: CollaborationDetails,
    language: str,
) -> tuple[ActionProposal, str]:
    """Detaylardan makaleye bağlı ``ActionProposal`` üretir.

    Returns:
        ``(proposal, proposal_content_hash)`` — hash B9 tek tanımıyla
        önerinin DÜZENLENEBİLİR ÖZET metninin UTF-8 SHA-256 özetidir ve onay
        sürüm denetiminde kullanılır (``AgentCollaborationContentHash`` ile
        aynı değer: aynı özet metni aynı hash'i üretir).

    Raises:
        PortError: ``validation_error`` — bağlam makaleye bağlı değil
            (sözleşme: ``ActionProposal`` makale üçlüsü zorunludur).
    """
    if (
        context.article_id is None
        or context.article_revision is None
        or context.article_content_hash is None
    ):
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            "iş birliği önerisi bir makale bağlamına bağlı olmalıdır "
            "(article_id/revision/content_hash eksik); hangi içerik için olduğunu belirtin",
            port="build_collab_proposal",
        )
    proposed_content = _compose_content(details, language)
    proposal = ActionProposal(
        proposal_id=new_proposal_id(),
        run_id=context.run_id,
        article_id=context.article_id,
        article_revision=context.article_revision,
        base_content_hash=context.article_content_hash,
        summary=_compose_summary(details, language),
        proposed_content=proposed_content,
        created_at=datetime.now(timezone.utc),
    )
    # Onay sürümü hash'i TEK TANIM: düzenlenebilir özet metninin SHA-256'sı
    # (backend B9 AgentCollaborationContentHash.Compute ile aynı değer).
    return proposal, compute_content_hash(proposal.summary)
