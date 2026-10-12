"""Onaylı kayıtlardan deterministik tr/en rehberlik metinleri (plan A9).

Bu modülün tek sorumluluğu COMPOZE etmektir: verilen onaylı profil/proje
kayıtları ve makale kataloğundan insan-okur metin üretir. Hiçbir fonksiyon
kaynakta olmayan bilgi EKLEMEZ — eksik alanlar yalnız adıyla anılır ve
"bulunmuyor" olarak bildirilir (plan A9: "Eksik deneyim, ücret veya
müsaitlik bilgisini uydurma").

Dil sözleşmesi: ``language`` ``tr`` ile başlıyorsa Türkçe, aksi halde
İngilizce şablon; plan A9: "Türkçe ve İngilizce cevap üret".
"""

from __future__ import annotations

from ..content.retrieval import tokenize
from ..ports import ProfileSummary, ProjectRecord
from .models import ArticleCatalogEntry, ArticleSuggestion, MissingInfoField

__all__ = [
    "compose_profile_answer",
    "compose_projects_answer",
    "compose_suggestion_answer",
    "detect_missing_info_fields",
    "is_turkish",
    "missing_info_questions",
    "project_interest_tokens",
    "suggest_articles",
    "unavailable_note",
]

#: Uydurulması yasak alanların soru sinyalleri. Türkçe çekim ekleri nedeniyle
#: KÖK önekli eşleşme ("ucretiniz" → "ucret"); İngilizce tam belirteç eşleşme
#: ("generate" içindeki "rate" gibi yanlış pozitifleri engellemek için).
_MISSING_INFO_PREFIXES_TR: dict[MissingInfoField, tuple[str, ...]] = {
    MissingInfoField.EXPERIENCE: ("deneyim", "tecrube"),
    MissingInfoField.RATE: ("ucret", "fiyat"),
    MissingInfoField.AVAILABILITY: ("musait",),
}

_MISSING_INFO_TOKENS_EN: dict[MissingInfoField, frozenset[str]] = {
    MissingInfoField.EXPERIENCE: frozenset({"experience", "experienced"}),
    MissingInfoField.RATE: frozenset({"rate", "rates", "price", "pricing", "fee", "cost"}),
    MissingInfoField.AVAILABILITY: frozenset({"availability", "available", "freelance"}),
}


def is_turkish(language: str) -> bool:
    """Dil kodu Türkçe mi? (``tr`` / ``tr-TR`` biçimleri)."""
    return language.casefold().startswith("tr")


def detect_missing_info_fields(question: str) -> list[MissingInfoField]:
    """Soruda, onaylı kayıtlarda bulunmayan bilgi alanlarına talep var mı?

    Katlanmış belirteçler üzerinde: Türkçe kök önek eşleşmesi + İngilizce
    tam belirteç eşleşmesi (A3 ``tokenize`` katlaması).
    """
    tokens = set(tokenize(question))
    detected: list[MissingInfoField] = []
    for field in MissingInfoField:
        tr_hit = any(token.startswith(prefix) for token in tokens for prefix in _MISSING_INFO_PREFIXES_TR[field])
        en_hit = bool(tokens & _MISSING_INFO_TOKENS_EN[field])
        if tr_hit or en_hit:
            detected.append(field)
    return detected


def missing_info_questions(fields: list[MissingInfoField], language: str) -> list[str]:
    """Eksik bilgi alanları için kısa açık sorular (needs_input girdisi)."""
    if is_turkish(language):
        labels = ", ".join(f.label(language) for f in fields)
        return [
            f"{labels} onaylı profil kayıtlarında bulunmuyor; bu bilgiyi sahibiyle "
            "doğrudan iletişim bağlantılarından doğrulamak ister misiniz?"
        ]
    labels = ", ".join(f.label(language) for f in fields)
    return [
        f"{labels} are not part of the approved profile records; would you like to "
        "verify this directly through the contact links?"
    ]


def _links_block(links: dict[str, str], *, turkish: bool) -> str:
    header = "Bağlantılar:" if turkish else "Links:"
    lines = [f"- {key}: {url}" for key, url in links.items()]
    return "\n".join([header, *lines]) if lines else ""


def compose_profile_answer(
    profile: ProfileSummary,
    language: str,
    *,
    missing_fields: list[MissingInfoField] | None = None,
) -> str:
    """Onaylı profil kaydından tr/en tanıtım metni; yalnız kayıttaki alanlar."""
    turkish = is_turkish(language)
    parts: list[str] = []
    title = f"{profile.name} — {profile.job_title}" if profile.job_title else profile.name
    parts.append(title)
    if profile.description:
        parts.append(profile.description)
    if profile.skills:
        skills_header = "Yetkinlikler:" if turkish else "Skills:"
        parts.append("\n".join([skills_header, ", ".join(profile.skills)]))
    links = _links_block(profile.links, turkish=turkish)
    if links:
        parts.append(links)
    if missing_fields:
        unavailable = ", ".join(f.label(language) for f in missing_fields)
        if turkish:
            parts.append(
                f"Not: şu bilgiler onaylı kayıtlarda bulunmuyor ve tahminle doldurulmaz: {unavailable}."
            )
        else:
            parts.append(
                f"Note: the following are not part of the approved records and are never guessed: {unavailable}."
            )
    return "\n\n".join(part for part in parts if part)


def project_interest_tokens(question: str, *, min_length: int = 4) -> set[str]:
    """Proje/öneri eşleştirmesinde sorunun anlamlı terimleri (katlanmış)."""
    return {token for token in tokenize(question) if len(token) >= min_length}


def _project_tokens(project: ProjectRecord) -> set[str]:
    text = " ".join([project.name, project.description or "", *project.technologies])
    return {token for token in tokenize(text) if len(token) >= 3}


def compose_projects_answer(
    projects: list[ProjectRecord],
    language: str,
    *,
    interest_tokens: set[str] | None = None,
) -> str:
    """Onaylı proje kayıtlarından tr/en rehberlik: amaç, teknolojiler, bağlantılar.

    ``interest_tokens`` verildiyse eşleşen projeler önce sıralanır; hiçbir
    proje eşleşmezse tüm kayıtlar listelenir ve dürüst bir not eklenir.
    """
    turkish = is_turkish(language)
    if not projects:
        return (
            "Onaylı proje kaydı bağlı değil; proje rehberi şu anda sunulamıyor."
            if turkish
            else "No approved project records are connected; project guidance is unavailable right now."
        )

    ordered = list(projects)
    interest_note = ""
    if interest_tokens:
        matched = [p for p in ordered if _project_tokens(p) & interest_tokens]
        if matched:
            ordered = [*matched, *(p for p in ordered if p not in matched)]
        else:
            interest_note = (
                "\n\nNot: ilgi alanınızla doğrudan eşleşen proje ayrıştırılamadı; tüm onaylı projeler listeleniyor."
                if turkish
                else "\n\nNote: no project matched your interest directly; listing all approved projects."
            )

    header = "Projeler:" if turkish else "Projects:"
    blocks: list[str] = [header]
    for project in ordered:
        lines = [f"## {project.name}"]
        if project.description:
            lines.append(project.description)
        if project.technologies:
            tech_header = "Teknolojiler:" if turkish else "Technologies:"
            lines.append("\n".join([tech_header, ", ".join(project.technologies)]))
        links = _links_block(project.links, turkish=turkish)
        if links:
            lines.append(links)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + interest_note


def suggest_articles(
    question: str,
    catalog: list[ArticleCatalogEntry],
    language: str,
    *,
    limit: int = 3,
) -> list[ArticleSuggestion]:
    """İlgiye göre makale önerisi; gerekçe yalnız girdi konularından, link girdiden.

    Eşleşme eşiği: en az bir anlamlı terim örtüşmesi. Eşitlikte başlık
    sırası kararlıdır (determinizm).
    """
    interest = project_interest_tokens(question)
    scored: list[tuple[int, ArticleCatalogEntry, list[str]]] = []
    for entry in catalog:
        entry_tokens = {token for token in tokenize(" ".join([entry.title, *entry.topics])) if len(token) >= 3}
        matched = sorted(interest & entry_tokens)
        if matched:
            scored.append((len(matched), entry, matched))
    scored.sort(key=lambda item: (-item[0], item[1].title))

    suggestions: list[ArticleSuggestion] = []
    for _, entry, matched in scored[:limit]:
        topic_list = ", ".join(matched)
        reason = (
            f"İlgi alanlarınızla eşleşen konular: {topic_list}."
            if is_turkish(language)
            else f"Matches your stated interests: {topic_list}."
        )
        suggestions.append(
            ArticleSuggestion(
                article_id=entry.article_id,
                title=entry.title,
                url=entry.url,
                matched_topics=matched,
                relevance_reason=reason,
            )
        )
    return suggestions


def compose_suggestion_answer(
    suggestions: list[ArticleSuggestion],
    language: str,
) -> str:
    """Öneri listesini kısa uygunluk gerekçesi + kaynak bağlantısıyla yazdırır."""
    turkish = is_turkish(language)
    if not suggestions:
        return (
            "İlgi alanınıza eşleşen öneri üretilemedi."
            if turkish
            else "No suggestion matched your stated interests."
        )
    header = "İlginize göre makale önerileri:" if turkish else "Articles matched to your interests:"
    lines = [header]
    for index, suggestion in enumerate(suggestions, start=1):
        lines.append(f"{index}. {suggestion.title} — {suggestion.relevance_reason} {suggestion.url}")
    return "\n".join(lines)


def unavailable_note(capability: str, language: str) -> str:
    """Bağlı olmayan onaylı kaynak için dürüst kullanılamazlık notu (A5 deseni)."""
    if is_turkish(language):
        return f"Not: {capability} bu çalışmaya bağlı olmadığı için onaylı kayıt olmadan cevap üretilmez."
    return f"Note: {capability} is not connected to this run; no answer is produced without approved records."
