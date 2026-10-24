"""Request-local canonical owner signals, visitor identity, and question language.

Names and project aliases come from the pinned document. Generic owner/author
phrases remain language rules, and technical questions require profile context.
No mutable process-wide identity or personal-name defaults are used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..content.anchors import fold_text
from ..content.retrieval import tokenize
from ..models import RouteDecision, RunIntent

if TYPE_CHECKING:
    from .source import ProfileDocument

__all__ = [
    "OWNER_STRONG_ALIASES",
    "OWNER_WEAK_ALIASES",
    "ProfileIdentity",
    "VISITOR_IDENTITY_ROUTE_REASON",
    "detect_question_language",
    "is_visitor_identity_route",
    "has_profile_term",
    "is_owner_profile_question",
    "is_visitor_identity_question",
    "mentions_owner",
    "owner_name_tokens",
]

#: Generic strong owner phrases; personal aliases come from ProfileIdentity.
OWNER_STRONG_ALIASES = (
    "blog sahibi",
    "blogun sahibi",
    "site sahibi",
    "sitenin sahibi",
    "blog owner",
    "owner of this blog",
    "owner of the blog",
)

#: Zayıf sahip takma adları: makaleye bağlı bağlamda makalenin yazarını da gösterebilir.
OWNER_WEAK_ALIASES = (
    "blog yazari",
    "blogun yazari",
    "yazar",
    "the author",
    "author",
    "blog author",
)

#: Türkçe takma adlar ek alabilir; İngilizce takma adlar tam kelime eşleşir
#: ("author" ≠ "authorization").
_ENGLISH_ALIASES = frozenset(
    {"blog owner", "owner of this blog", "owner of the blog", "the author", "author", "blog author"}
)

@dataclass(frozen=True)
class ProfileIdentity:
    """Immutable identity derived from one request's approved canonical source."""

    display_name: str
    aliases: tuple[str, ...] = ()
    profile_aliases: tuple[str, ...] = ()

    @classmethod
    def from_document(cls, document: "ProfileDocument") -> "ProfileIdentity":
        aliases = tuple(dict.fromkeys(
            value.strip() for value in (document.owner.name, *document.owner.aliases)
            if value.strip() and fold_text(value.strip()) not in (*OWNER_STRONG_ALIASES, *OWNER_WEAK_ALIASES)
        ))
        project_aliases: list[str] = []
        for section in document.retrievable_sections():
            if section.section_id.startswith(("project-", "projects-", "ai-", "oss-")) or section.kind in {"project", "ai_work", "oss"}:
                title_words = [" ".join(tokenize(value)) for value in section.title.values()]
                for values in section.aliases.values():
                    for value in values:
                        candidate = " ".join(tokenize(value))
                        # Broad subject aliases (architecture, article, model,
                        # skills...) are retrieval cues, not unique project
                        # names. Only title-backed specific aliases stand alone.
                        generic = candidate in _PROFILE_TERMS_EN or candidate in _PROFILE_TERM_PREFIXES_TR
                        generic = generic or (
                            len(candidate.split()) == 1
                            and any(candidate.startswith(prefix) for prefix in _PROFILE_TERM_PREFIXES_TR)
                        )
                        generic = generic or candidate in {
                            "bu blog", "blogdaki ajan", "gunluk kullanim", "ai work", "open source", "acik kaynak",
                        }
                        if candidate and not generic and any(candidate in title for title in title_words):
                            project_aliases.append(value.strip())
                fence: str | None = None
                for line in section.body.splitlines():
                    marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
                    if marker:
                        character = marker.group(1)[0]
                        fence = None if fence == character else character if fence is None else fence
                        continue
                    if fence is not None:
                        continue
                    heading = re.match(r"^\s{0,3}#{3,6}\s+(.+?)\s*#*\s*$", line)
                    if heading:
                        title = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", heading.group(1)).strip(" *`_")
                        title = re.sub(r"^\d+(?:\.\d+)*[.)]?\s+", "", title)
                        if title:
                            project_aliases.append(title)
                            short_title = re.split(r"\s+[–—|]\s+|\s+-\s+|:\s+", title, maxsplit=1)[0].strip()
                            if short_title:
                                project_aliases.append(short_title)
        return cls(document.owner.name, aliases, tuple(dict.fromkeys(project_aliases)))

#: Biyografi/proje/bölüm terimleri — Türkçe kökler (ek toleranslı önek eşleşme).
_PROFILE_TERM_PREFIXES_TR = (
    "kim", "hakkinda", "tanit", "biyografi", "ozgecmis", "profil", "nereli", "yasiyor",
    "egitim", "universite", "okul", "okudu", "okumus", "mezun", "lisans", "bolum", "staj", "kariyer",
    "deneyim", "tecrube", "meslek", "calis", "egitmen", "ogretmen", "ders", "mentor",
    "yetenek", "yetkinlik", "beceri", "teknoloji", "programlama", "dil",
    "biliyor", "bilir", "kullan", "uzman", "proje", "uygulama", "ezan",
    "namaz", "sinav", "futbol", "oyun", "kentsel", "ajan", "agentic", "sdlc",
    "grok", "claude", "codex", "corpus", "katki", "mimari", "yaklasim", "onion", "cqrs",
    "mediatr", "repository", "blog", "yazi", "makale", "konu", "sertifika", "iletisim", "ulas",
    "hobi", "ilgi", "muzik", "takim", "matematik", "algoritma", "github",
    "linkedin", "twitter", "telefon", "numara", "yas", "dogum", "dogdu", "maas", "kazan", "evli",
    "bekar", "medeni", "ucret", "fiyat", "musait", "isveren", "sirket", "firma", "kurum", "musteri",
    "basvuru", "stack", "eposta",
)

#: Çok kelimeli Türkçe/İngilizce terimler (alt dizin).
_PROFILE_TERM_PHRASES = (
    "e-posta", "web sitesi", "acik kaynak", "clean architecture",
    "calisma tarzi", "tech stack", "open source", "root agent",
)

#: İngilizce terimler (tam kelime).
_PROFILE_TERMS_EN = frozenset(
    {
        "who", "about", "background", "bio", "biography", "profile", "resume", "cv", "lives", "live",
        "based", "from", "education", "university", "college", "school", "degree", "graduate",
        "graduated", "studied", "study", "internship", "internships", "intern", "career", "experience",
        "job", "jobs", "work", "works", "working", "worked", "employer", "company", "teaching", "teach",
        "teaches", "teacher", "instructor", "trainer", "mentor", "mentoring", "courses", "skills",
        "skill", "technologies", "technology", "tech", "stack", "languages", "language", "expertise",
        "expert", "knows", "know", "uses", "use", "project", "projects", "app", "apps", "built",
        "build", "building", "agent", "agents", "architecture", "approach", "cqrs", "onion", "blog",
        "posts", "writes", "write", "writing", "certificate", "certificates", "certification",
        "certifications", "certified", "hobby", "hobbies", "interests", "interest", "music", "contact",
        "reach", "email", "phone", "github", "linkedin", "twitter", "age", "old", "born", "birthday",
        "salary", "earn", "earns", "married", "rate", "rates", "pricing", "available", "availability",
        "hire", "freelance", "clients", "client",
    }
)

#: Ziyaretçinin KENDİ kimliğini soran kalıplar (katlanmış metin).
_VISITOR_IDENTITY_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bben kimim\b",
        r"\bkimim\b",
        r"\bbeni tan(?:iyor|ir|idin|iyormusun)",
        r"\bkim oldugumu\b",
        r"\bbenim kim oldugum",
        r"\bbenim adim ne\b",
        r"\badimi (?:biliyor|bilir)",
        r"\bwho am i\b",
        r"\bwho i am\b",
        r"\bdo you know me\b",
        r"\bdo you know who\b",
        r"\bwhat(?:'s| is) my name\b",
    )
)

#: Türkçe'ye özgü harfler (katlamadan önce) ve sık Türkçe belirteçler.
_TURKISH_CHARS = frozenset("çğıöşüÇĞİÖŞÜ")
_TURKISH_TOKENS = frozenset(
    {
        "ve", "ile", "bir", "bu", "ne", "mi", "mu", "nedir", "neler", "nasil", "hangi", "kimdir", "kim",
        "var", "mi", "icin", "gibi", "da", "de", "peki", "ben", "bana", "beni", "onun", "yapti",
        "yapiyor", "midir", "misin", "musun", "kac", "nerede", "neden", "hakkinda", "anlat", "acikla",
        "ozetle", "sertifikalari", "egitimi", "projeleri",
    }
)
_ENGLISH_TOKENS = frozenset(
    {
        "the", "is", "are", "what", "which", "who", "how", "does", "do", "did", "his", "he", "him", "of",
        "about", "tell", "me", "and", "where", "when", "has", "have", "can", "i", "a", "an", "in", "on",
        "with", "for", "explain", "describe", "summarize", "list",
    }
)


def _phrase_regex(phrase: str, *, english: bool) -> re.Pattern[str]:
    escaped = re.escape(phrase)
    if english:
        return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")
    # Türkçe: ifade kelime başında başlar; ekler (iyelik/hal) tolere edilir.
    return re.compile(rf"(?<![a-z0-9]){escaped}")


_STRONG_RES = tuple(_phrase_regex(alias, english=alias in _ENGLISH_ALIASES) for alias in OWNER_STRONG_ALIASES)
_WEAK_RES = tuple(_phrase_regex(alias, english=alias in _ENGLISH_ALIASES) for alias in OWNER_WEAK_ALIASES)


def mentions_owner(question: str, *, allow_weak: bool = True, identity: ProfileIdentity | None = None) -> bool:
    """Match generic owner references and this request's canonical owner aliases."""

    folded = fold_text(question)
    if any(pattern.search(folded) for pattern in _STRONG_RES):
        return True
    if identity is not None and any(
        _phrase_regex(fold_text(alias), english=False).search(folded) for alias in identity.aliases
    ):
        return True
    return allow_weak and any(pattern.search(folded) for pattern in _WEAK_RES)


def has_profile_term(question: str) -> bool:
    """Biyografi/proje/bölüm terimi var mı? (sahip göndermesiyle birleşir)."""

    folded = fold_text(question)
    tokens = tokenize(question)
    if any(token.startswith(prefix) for token in tokens for prefix in _PROFILE_TERM_PREFIXES_TR):
        return True
    if any(token in _PROFILE_TERMS_EN for token in tokens):
        return True
    return any(phrase in folded for phrase in _PROFILE_TERM_PHRASES)


def _mentions_standalone_profile_name(question: str, identity: ProfileIdentity | None) -> bool:
    folded = fold_text(question)
    return identity is not None and any(
        _phrase_regex(fold_text(alias), english=False).search(folded) for alias in identity.profile_aliases
    )


def is_visitor_identity_question(question: str) -> bool:
    """Ziyaretçi KENDİ kimliğini mi soruyor? ("Ben kimim?", "Who am I?")."""

    folded = fold_text(question)
    return any(pattern.search(folded) for pattern in _VISITOR_IDENTITY_PATTERNS)


def is_owner_profile_question(
    question: str, *, article_bound: bool = False, identity: ProfileIdentity | None = None
) -> bool:
    """Blog sahibi hakkında biyografik/proje sorusu mu?

    Güçlü sahip göndermesi + profil terimi, makalesiz bağlamda zayıf sahip
    göndermesi + profil terimi veya benzersiz proje adı profil sinyalidir.
    Ziyaretçi-kimliği soruları ayrı sınıftır (``is_visitor_identity_question``).
    """

    if is_visitor_identity_question(question):
        return False
    if _mentions_standalone_profile_name(question, identity):
        return True
    if not mentions_owner(question, allow_weak=not article_bound, identity=identity):
        return False
    return has_profile_term(question)


#: AUTO konuda ziyaretçi-kimliği belirsizliği kararının gerekçe öneki. Rota
#: ``intent=PROFILE`` + bu gerekçe → korpus gerektirmeyen kısa, tamamlanmış
#: netleştirme cevabı (``needs_input`` DEĞİL; collaboration resume akışı yok).
VISITOR_IDENTITY_ROUTE_REASON = "ziyaretçi kimliği belirsiz: kısa netleştirme cevabı"


def is_visitor_identity_route(route: RouteDecision) -> bool:
    """Rota, AUTO ziyaretçi-kimliği netleştirmesi mi? (routing işaretler, yürütme okur)."""

    return route.intent is RunIntent.GENERAL and route.brief_reason.startswith(VISITOR_IDENTITY_ROUTE_REASON)


def owner_name_tokens(identity: ProfileIdentity | None = None) -> frozenset[str]:
    """Retrieval'da düşük ağırlıkla sayılan sahip adı belirteçleri (katlanmış)."""

    return frozenset(token for alias in identity.aliases for token in tokenize(alias)) if identity else frozenset()


def detect_question_language(
    question: str, fallback: str, *, identity: ProfileIdentity | None = None
) -> str:
    """Sorunun dili: ``tr`` veya ``en``; ayırt edilemezse ``fallback``'in dili.

    Türkçe'ye özgü harf veya sık Türkçe belirteç → ``tr``; İngilizce işlev
    kelimeleri baskınsa → ``en``. Aksansız Türkçe ("egitimi nedir") Türkçe
    belirteçlerle yakalanır.
    """

    # A person's Turkish display name does not turn an English question into
    # Turkish. Remove only this request's canonical aliases before language cues.
    language_text = question
    if identity is not None:
        for alias in sorted(identity.aliases, key=len, reverse=True):
            language_text = re.sub(re.escape(alias), " ", language_text, flags=re.IGNORECASE)
    if any(char in _TURKISH_CHARS for char in language_text):
        return "tr"
    tokens = tokenize(language_text)
    turkish = sum(1 for token in tokens if token in _TURKISH_TOKENS)
    english = sum(1 for token in tokens if token in _ENGLISH_TOKENS)
    if turkish > english:
        return "tr"
    if english > turkish:
        return "en"
    return "tr" if fallback.casefold().startswith("tr") else "en"
