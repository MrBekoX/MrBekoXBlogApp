"""Profil sorusu sinyalleri: blog sahibi göndermesi, ziyaretçi kimliği, soru dili.

Routing (AUTO konu) ve profil runner'ı aynı deterministik sinyalleri kullanır.
Tüm eşleşmeler ``content.anchors.fold_text`` ile katlanmış metinde yapılır;
aksansız Türkçe ("egitimi", "universite") ve aksanlı yazım aynı sonucu verir.

Sahip göndermesi iki sınıftır:

- Güçlü: ``sample``, ``sample author``, ``mrbekox``, ``beko``, ``blog sahibi``
  ... (canonical ``owner.aliases`` ile aynı küme + Türkçe iyelik biçimleri).
- Zayıf: ``yazar``, ``the author``, ``blog yazarı`` — makaleye bağlı bağlamda
  makalenin yazarı anlamına gelebileceği için yalnız makalesiz bağlamda sayılır.

Sahip göndermesi tek başına profil niyeti DEĞİLDİR; biyografi/proje/bölüm
terimiyle birleşmelidir ("Sample'ın eğitimini açıkla"). Yalnız Sample'a ait
benzersiz proje adları (Vibeo, Emojify, XERJ ...) tek başına profil sinyalidir.
"CQRS nedir?" gibi teknik sorular sahip göndermesi taşımadığından profil
akışına zorlanmaz.
"""

from __future__ import annotations

import re

from ..content.anchors import fold_text
from ..content.retrieval import tokenize
from ..models import RouteDecision, RunIntent

__all__ = [
    "OWNER_STRONG_ALIASES",
    "OWNER_WEAK_ALIASES",
    "VISITOR_IDENTITY_ROUTE_REASON",
    "detect_question_language",
    "is_visitor_identity_route",
    "has_profile_term",
    "is_owner_profile_question",
    "is_visitor_identity_question",
    "mentions_owner",
    "owner_name_tokens",
]

#: Güçlü sahip takma adları (katlanmış). Türkçe ekler tolere edilir
#: ("sample'in", "samplein", "blog sahibinin").
OWNER_STRONG_ALIASES = (
    "sample author",
    "sample",
    "mrbekox",
    "beko",
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

#: Sahip adının belirteçleri; retrieval bunları düşük ağırlıkla sayar.
_OWNER_NAME_TOKENS = frozenset({"sample", "author", "mrbekox", "beko"})

#: Yalnız Sample'a ait benzersiz proje/çalışma adları (tek başına profil sinyali).
_STANDALONE_PROFILE_NAMES = (
    "vibeo",
    "emojify",
    "adhan time",
    "agentic-sdlc",
    "agentic sdlc",
    "root-agent-skill-framework",
    "xerj",
    "now-coffe",
    "now coffe",
    "sinav arkadasim",
    "mrbekox.dev",
    "auth token server",
)

#: Biyografi/proje/bölüm terimleri — Türkçe kökler (ek toleranslı önek eşleşme).
_PROFILE_TERM_PREFIXES_TR = (
    "kim", "hakkinda", "tanit", "biyografi", "ozgecmis", "profil", "nereli", "yasiyor", "orneksehir",
    "egitim", "universite", "okul", "okudu", "okumus", "mezun", "lisans", "bolum", "staj", "kariyer",
    "deneyim", "tecrube", "meslek", "calis", "egitmen", "ogretmen", "ders", "mentor", "sample academy",
    "sample center", "sample training", "yetenek", "yetkinlik", "beceri", "teknoloji", "programlama", "dil",
    "biliyor", "bilir", "kullan", "uzman", "proje", "uygulama", "vibeo", "emojify", "adhan", "ezan",
    "namaz", "sinav", "coffe", "futbol", "oyun", "kentsel", "urbansound", "ajan", "agentic", "sdlc",
    "grok", "claude", "codex", "xerj", "corpus", "katki", "mimari", "yaklasim", "onion", "cqrs",
    "mediatr", "repository", "blog", "yazi", "makale", "konu", "sertifika", "iletisim", "ulas",
    "hobi", "ilgi", "muzik", "suno", "sample sports club", "takim", "matematik", "algoritma", "github",
    "linkedin", "twitter", "telefon", "numara", "yas", "dogum", "dogdu", "maas", "kazan", "evli",
    "bekar", "medeni", "ucret", "fiyat", "musait", "isveren", "sirket", "firma", "kurum", "musteri",
    "basvuru", "stack", "eposta",
)

#: Çok kelimeli Türkçe/İngilizce terimler (alt dizin).
_PROFILE_TERM_PHRASES = (
    "e-posta", "web sitesi", "acik kaynak", "root agent", "clean architecture", "now-coffe",
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
_STANDALONE_RES = tuple(_phrase_regex(name, english=False) for name in _STANDALONE_PROFILE_NAMES)


def mentions_owner(question: str, *, allow_weak: bool = True) -> bool:
    """Soru blog sahibine (Sample Author / MrBekoX / blog sahibi) gönderme yapıyor mu?"""

    folded = fold_text(question)
    if any(pattern.search(folded) for pattern in _STRONG_RES):
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


def _mentions_standalone_profile_name(question: str) -> bool:
    folded = fold_text(question)
    return any(pattern.search(folded) for pattern in _STANDALONE_RES)


def is_visitor_identity_question(question: str) -> bool:
    """Ziyaretçi KENDİ kimliğini mi soruyor? ("Ben kimim?", "Who am I?")."""

    folded = fold_text(question)
    return any(pattern.search(folded) for pattern in _VISITOR_IDENTITY_PATTERNS)


def is_owner_profile_question(question: str, *, article_bound: bool = False) -> bool:
    """Blog sahibi hakkında biyografik/proje sorusu mu?

    Güçlü sahip göndermesi + profil terimi, makalesiz bağlamda zayıf sahip
    göndermesi + profil terimi veya benzersiz proje adı profil sinyalidir.
    Ziyaretçi-kimliği soruları ayrı sınıftır (``is_visitor_identity_question``).
    """

    if is_visitor_identity_question(question):
        return False
    if _mentions_standalone_profile_name(question):
        return True
    if not mentions_owner(question, allow_weak=not article_bound):
        return False
    return has_profile_term(question)


#: AUTO konuda ziyaretçi-kimliği belirsizliği kararının gerekçe öneki. Rota
#: ``intent=PROFILE`` + bu gerekçe → korpus gerektirmeyen kısa, tamamlanmış
#: netleştirme cevabı (``needs_input`` DEĞİL; collaboration resume akışı yok).
VISITOR_IDENTITY_ROUTE_REASON = "ziyaretçi kimliği belirsiz: kısa netleştirme cevabı"


def is_visitor_identity_route(route: RouteDecision) -> bool:
    """Rota, AUTO ziyaretçi-kimliği netleştirmesi mi? (routing işaretler, yürütme okur)."""

    return route.intent is RunIntent.GENERAL and route.brief_reason.startswith(VISITOR_IDENTITY_ROUTE_REASON)


def owner_name_tokens() -> frozenset[str]:
    """Retrieval'da düşük ağırlıkla sayılan sahip adı belirteçleri (katlanmış)."""

    return _OWNER_NAME_TOKENS


def detect_question_language(question: str, fallback: str) -> str:
    """Sorunun dili: ``tr`` veya ``en``; ayırt edilemezse ``fallback``'in dili.

    Türkçe'ye özgü harf veya sık Türkçe belirteç → ``tr``; İngilizce işlev
    kelimeleri baskınsa → ``en``. Aksansız Türkçe ("egitimi nedir") Türkçe
    belirteçlerle yakalanır.
    """

    if any(char in _TURKISH_CHARS for char in question):
        return "tr"
    tokens = tokenize(question)
    turkish = sum(1 for token in tokens if token in _TURKISH_TOKENS)
    english = sum(1 for token in tokens if token in _ENGLISH_TOKENS)
    if turkish > english:
        return "tr"
    if english > turkish:
        return "en"
    return "tr" if fallback.casefold().startswith("tr") else "en"
