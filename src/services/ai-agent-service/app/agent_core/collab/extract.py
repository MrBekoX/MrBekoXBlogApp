"""Soru metninden iş birliği detaylarının deterministik çıkarımı (plan A9).

Plan A9: "Amaç, kapsam, takvim, isteğe bağlı bütçe ve iletişim yöntemini
çıkar. Gerekli eksik alanları kısa sorularla tamamla."

Sözleşmeler:

- Çıkarım yalnız soruda GERÇEKTEN geçen ifadelerle yapılır; çıkarılamayan
  zorunlu alan ``None`` kalır ve kısa soru sorulur — tahmin yoktur.
- ``budget`` isteğe bağlıdır: soruda yoksa sorulmaz.
- Sinyal eşleşmesi A3 ``fold_text`` katlamasıyla yapılır; kapsam/takvim/
  bütçe/iletişim yakalaması okunabilirliği korumak için ``lower()`` metin
  üzerinden regex ile yapılır ve yalnız EŞLEŞEN alt dizi saklanır.
"""

from __future__ import annotations

import re

from ..content.anchors import fold_text
from ..models import ConversationTurn
from .models import CollabField, CollaborationDetails, PurposeKind

__all__ = [
    "extract_collaboration_details",
    "merge_answer",
    "questions_for_missing_fields",
]


# --- Amaç sinyalleri (katlanmış metinde alt dizin; ilk eşleşen kategori kazanır) ---
# fold_text boşlukları korur; sinyaller katlanmış (fold_text çıktısı) biçimde
# saklanır — routing.py sinyal kuralıyla aynıdır.

_PURPOSE_SIGNALS: tuple[tuple[PurposeKind, tuple[str, ...]], ...] = (
    (
        PurposeKind.GUEST_POST,
        ("guest post", "konuk yaz", "konuk makale", "blogunda yazmak", "siten icin yazmak"),
    ),
    (
        PurposeKind.TRANSLATION,
        ("ceviri", "cevirmek", "translation", "translate"),
    ),
    (
        PurposeKind.OPEN_SOURCE,
        ("acik kaynak", "open source", "contribute", "contribution", "katkida bulun", "pull request"),
    ),
    (
        PurposeKind.COLLABORATION,
        ("is birligi", "isbirligi", "collaborat", "partnership", "birlikte calis", "beraber calis"),
    ),
)

_SCOPE_QUOTE_RE = re.compile(r"[\"'«“]([^\"'»”]{3,300})[\"'»”]")
_ABOUT_RE = re.compile(r"(?:hakkında|hakkinda|about)\s+([^.;?!;\n]{3,300})", re.IGNORECASE)
_ARTICLE_REFERENCE_RE = re.compile(
    r"bu makale|bu yazı|makaleye|makalede|the article|this article|this post",
    re.IGNORECASE,
)

_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_IN_DURATION_RE = re.compile(
    r"\b(?:in\s+)?(\d{1,3})\s*(?:gün|gun|hafta|ay|day|days|week|weeks|month|months)\s*(?:içinde|icinde)?\b",
    re.IGNORECASE,
)
_NAMED_SPAN_RE = re.compile(
    r"\b(bu hafta|bu ay|bu yıl|önümüzdeki hafta|önümüzdeki ay|"
    r"next week|next month|this week|this month|this year)\b",
    re.IGNORECASE,
)

_BUDGET_RE = re.compile(
    r"(?:bütçe|butce|budget)\b\s*[:=]?\s*([^.;?!\n]{1,80})",
    re.IGNORECASE,
)
_BUDGET_ABSENT_RE = re.compile(r"^\s*(yok|yoktur|bulunmuyor|none|n/a|not specified)\s*$", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\b(\d[\d.,]*)\s*(?:tl|try|usd|eur|dolar|euro|₺|\$|€)\b", re.IGNORECASE)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CONTACT_PHRASE_RE = re.compile(
    r"site üzerinden|site uzerinden|siteden|iletişim formu|iletisim formu|contact form|"
    r"via the site|through the site|x üzerinden|x uzerinden|buradan yaz",
    re.IGNORECASE,
)


def _user_turn_text(context) -> str:
    """Soru + konuşma geçmişindeki kullanıcı turları; çıkarımın tek girdisi."""
    parts = [context.question]
    for turn in context.conversation_history or []:
        if isinstance(turn, ConversationTurn) and turn.role == "user":
            parts.append(turn.content)
    return "\n".join(parts)


def _detect_purpose(folded: str) -> PurposeKind | None:
    for kind, signals in _PURPOSE_SIGNALS:
        if any(signal in folded for signal in signals):
            return kind
    return None


def _extract_scope(lower: str, article_title: str | None) -> str | None:
    quote = _SCOPE_QUOTE_RE.search(lower)
    if quote:
        return quote.group(1).strip()
    about = _ABOUT_RE.search(lower)
    if about:
        return about.group(1).strip()
    if article_title and _ARTICLE_REFERENCE_RE.search(lower):
        # Soru makaleye açıkça gönderme yapıyorsa kapsam GERÇEK başlığa bağlanır.
        turkish_context = "hakkında" in lower or "makale" in lower
        return f"Makale: {article_title}" if turkish_context else f"Article: {article_title}"
    return None


def _extract_timeline(lower: str) -> str | None:
    iso = _ISO_DATE_RE.search(lower)
    if iso:
        return iso.group(1)
    duration = _IN_DURATION_RE.search(lower)
    if duration:
        return duration.group(0).strip()
    named = _NAMED_SPAN_RE.search(lower)
    if named:
        return named.group(1).strip()
    return None


def _extract_budget(lower: str) -> str | None:
    match = _BUDGET_RE.search(lower)
    if match:
        captured = match.group(1).strip()
        if captured and not _BUDGET_ABSENT_RE.match(captured):
            return captured
        return None
    amount = _AMOUNT_RE.search(lower)
    if amount:
        return amount.group(0).strip()
    return None


def _extract_contact(lower: str) -> str | None:
    email = _EMAIL_RE.search(lower)
    if email:
        return email.group(0)
    phrase = _CONTACT_PHRASE_RE.search(lower)
    if phrase:
        return phrase.group(0).strip()
    return None


def extract_collaboration_details(context, *, article_title: str | None = None) -> CollaborationDetails:
    """Soru (+ kullanıcı turları) amaç/kapsam/takvim/bütçe/iletişim çıkarımı.

    Args:
        context: ``ExecutionContext``.
        article_title: bağlam makalesinin başlığı; soru makaleye açıkça
            gönderme yapıyorsa kapsam bu GERÇEK başlığa bağlanır.

    Returns:
        Çıkarılabilen alanları dolu, kalanları ``None`` olan detay kaydı.
    """
    text = _user_turn_text(context)
    folded = fold_text(text)
    lower = text.lower()
    return CollaborationDetails(
        purpose=_detect_purpose(folded),
        scope=_extract_scope(lower, article_title),
        timeline=_extract_timeline(lower),
        budget=_extract_budget(lower),
        contact=_extract_contact(lower),
    )


def merge_answer(details: CollaborationDetails, field: str, value: str) -> CollaborationDetails:
    """Resume cevabını detaya işler; alan adı ``CollabField`` değeridir.

    ``purpose`` serbest metin cevabı ``OTHER`` + not olarak kaydedilir
    (kullanıcının kendi ifadesi aynen taşınır, kategori uydurulmaz).

    Raises:
        ValueError: bilinmeyen alan adı.
    """
    known = {f.value for f in CollabField}
    if field not in known:
        raise ValueError(f"bilinmeyen iş birliği alanı: {field}")
    update: dict[str, object] = {}
    if field == "purpose":
        update["purpose"] = PurposeKind.OTHER
        update["purpose_note"] = value
    else:
        update[field] = value
    return details.model_copy(update=update)


def questions_for_missing_fields(missing: list[CollabField], language: str) -> list[str]:
    """Eksik zorunlu alanlar için KISA sorular (plan A9); bütçe sorulmaz."""
    turkish = language.casefold().startswith("tr")
    questions: list[str] = []
    for missing_field in missing:
        if missing_field is CollabField.PURPOSE:
            questions.append(
                "Bu iş birliğinin amacı nedir (konuk yazı, çeviri, açık kaynak katkısı)?"
                if turkish
                else "What is the purpose of the collaboration (guest post, translation, open-source contribution)?"
            )
        elif missing_field is CollabField.SCOPE:
            questions.append(
                "Hangi konu veya içerik kapsamında?" if turkish else "Which topic or content does it cover?"
            )
        elif missing_field is CollabField.TIMELINE:
            questions.append(
                "Hangi takvimde planlıyorsunuz?" if turkish else "What is your timeline?"
            )
        elif missing_field is CollabField.CONTACT:
            questions.append(
                "İletişim yönteminiz nedir (e-posta veya site üzerinden)?"
                if turkish
                else "What is your preferred contact method (email or via the site)?"
            )
    return questions
