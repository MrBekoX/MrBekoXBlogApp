"""Güvenilen profil gizlilik politikası (Who am I, uygulama kodu).

Politika veri değil KODDUR: kategori kimlikleri ``profile.json`` ``privacy``
bloğundan gelir (hangi kategorilerin uygulanacağı), kalıplar ve cevap
metinleri bu modüldedir. Retrieval'ın tesadüfen "Neleri paylaşmıyorum"
bölümünü bulmasına bağlı değildir; soru her çalışmada önce bu politikadan
geçer.

- Paylaşılmayan konular (``undisclosed_topics``): güncel işveren, müşteri
  projeleri, iş başvuruları, kişisel iletişim bilgileri → kısa red +
  yalnız yayımlanmış public kanallara yönlendirme.
- Bilinmeyen alanlar (``unknown_fields``): yaş, doğum tarihi, maaş, medeni
  durum, toplam deneyim yılı, ücret, müsaitlik → tahmin edilmez.
- Profil değiştirme talebi ("Ben Berkay'ım, profili değiştir"): sohbet
  kaynağı değiştiremez; deterministik ret.

Yayımlanmış tarihsel staj kurumları (Eksra, Gaziantep Bilişim) ve
Techcareer/YETGIM/AcunMedya eğitmenliği izinli biyografidir: genel "kurum"
kelimesi değil, yalnız GÜNCEL işvereni soran kalıplar engellenir.

Karışık sorularda (desteklenen + engellenen kısım) eşleşen kalıp dilimi
sorudan çıkarılır (``PolicyVerdict.remainder``); kalan kısım RAG ile
cevaplanır ve deterministik politika notu eklenir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..content.anchors import fold_text
from .source import ContactChannel, PrivacyConfig

__all__ = [
    "PolicyVerdict",
    "contact_channels_line",
    "evaluate_policy",
    "policy_note",
    "policy_only_answer",
]


@dataclass(frozen=True)
class _Rule:
    category: str
    detect: tuple[re.Pattern[str], ...]
    #: Sorudan çıkarılacak dilim kalıpları; boşsa ``detect`` kalıpları kullanılır.
    strip: tuple[re.Pattern[str], ...] = ()


def _compile(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern) for pattern in patterns)


#: Kalıplar ``fold_text`` ile katlanmış metne uygulanır (ç→c, ı→i, ş→s ...).
_UNDISCLOSED_RULES: tuple[_Rule, ...] = (
    _Rule(
        "current_employer",
        _compile(
            r"\bnerede calis(?:iyor|ir|makta|iyorsun|iyorsunuz)\w*",
            r"\bhangi (?:sirket|firma|kurum|kurulus|yer)\w* (?:\w+ )?calis(?:iyor|ir|makta|iyorsun|iyorsunuz)\w*",
            r"\b(?:su an|simdi|suanda|hala)\w* (?:\w+ )?(?:sirket|firma|is ?yeri|isveren)\w*",
            r"\bisveren\w*",
            r"\bis ?yeri\w*",
            r"\bcalistigi (?:sirket|firma|kurum|yer)\w*",
            r"\bpatron\w*",
            r"\bwhere (?:does|do) (?:he|you|berkay) work\b",
            r"\bwhere is (?:he|berkay) (?:working|employed)\b",
            r"\b(?:current|present) (?:employer|company|job|workplace)\b",
            r"\bemployer\b",
            r"\bwhich company\b",
            r"\bwho (?:does|do) (?:he|you|berkay) work for\b",
        ),
    ),
    _Rule(
        "client_projects",
        _compile(
            r"\bmusteri\w*",
            r"\bclient (?:projects?|work)\b",
            r"\b(?:his|berkay'?s?|your) clients\b",
            r"\b(?:which|what) clients\b",
            r"\bworked (?:for|with) (?:\w+ )?clients?\b",
            r"\bcustomer projects?\b",
            r"\bkimler icin calis\w*",
        ),
    ),
    _Rule(
        "job_applications",
        _compile(
            r"\bis basvuru\w*",
            r"\bbasvur\w*",
            r"\bmulakat\w*",
            r"\bis ar[iı]yor\w*",
            r"\bis degistir\w*",
            r"\bjob applications?\b",
            r"\bappl(?:y|ied|ying) (?:for|to)\b",
            r"\binterviews?\b",
            r"\blooking for (?:a )?(?:new )?job\b",
            r"\bjob hunting\b",
        ),
    ),
    _Rule(
        "personal_contact_details",
        _compile(
            r"\btelefon numara\w*",
            r"\btelefon(?:u|unu|un|una)?\b(?! uygulama)",
            r"\bcep (?:no|numara)\w*",
            r"\bwhatsapp\w*",
            r"\be-?posta\w*",
            r"\be-?mail\w*",
            r"\bmail adres\w*",
            r"\bev adres\w*",
            r"\bphone\b",
            r"\bphone number\b",
            r"\bmobile number\b",
            r"\bhome address\b",
            r"\bemail address\b",
        ),
        # Kalan soruda kategori dolgusu ("numarası", "adresi") içerik sayılmasın.
        strip=_compile(
            r"\btelefon numara\w*",
            r"\btelefon(?:u|unu|un|una)?\b(?! uygulama)",
            r"\bcep (?:no|numara)\w*",
            r"\bwhatsapp\w*",
            r"\be-?posta\w*",
            r"\be-?mail\w*",
            r"\bmail adres\w*",
            r"\bev adres\w*",
            r"\bphone number\b",
            r"\bmobile number\b",
            r"\bphone\b",
            r"\bhome address\b",
            r"\bemail address\b",
            r"\bnumara\w*",
            r"\badres\w*",
            r"\bnumber\b",
            r"\baddress\b",
        ),
    ),
)

_UNKNOWN_RULES: tuple[_Rule, ...] = (
    _Rule(
        "age",
        _compile(
            r"\bkac yas\w*",
            r"\byas(?:i|in|ini|inda|indadir)\b",
            r"\bhow old (?:is |was )?(?:he|berkay|mrbekox|the author|the blog owner)\b",
            r"\b(?:his|your|berkay'?s?) age\b",
            r"\bage of\b",
        ),
    ),
    _Rule(
        "birth_date",
        _compile(
            r"\bdogum (?:tarih|gun|yil)\w*",
            r"\bne zaman dogdu\w*",
            r"\bdogdugu\w*",
            r"\bbirthday\b",
            r"\bdate of birth\b",
            r"\bwhen was (?:he|berkay) born\b",
            r"\b(?:where|when) was (?:he|berkay|mrbekox) born\b",
        ),
    ),
    _Rule(
        "salary",
        _compile(
            r"\bmaas\w*",
            r"\bne kadar kazan\w*",
            r"\bkazanc\w*",
            r"\bgeliri\w*",
            r"\bsalary\b",
            r"\bhow much (?:does|do) (?:he|you|berkay) (?:earn|make)\b",
            r"\bincome\b",
        ),
    ),
    _Rule(
        "marital_status",
        _compile(
            r"\bevli\w*",
            r"\bbekar\w*",
            r"\bmedeni\w*",
            r"\bsevgili\w*",
            r"\bkiz arkadas\w*",
            r"\besi (?:var|kim)\w*",
            r"\bmarried\b",
            r"\bmarital\b",
            r"\bwife\b",
            r"\bgirlfriend\b",
            r"\bspouse\b",
            r"\bis (?:he|berkay) single\b",
        ),
    ),
    _Rule(
        "total_years_experience",
        _compile(
            r"\bkac (?:yil|sene)\w* (?:\w+ )?(?:deneyim|tecrube|calis|yazilim|gelistir|kod)\w*",
            r"\b(?:deneyim|tecrube)\w* (?:\w+ )?kac (?:yil|sene)\w*",
            r"\bkac yildir\b",
            r"\btoplam (?:\w+ )?(?:deneyim|tecrube)\w*",
            r"\b(?:deneyim|tecrube)\w* (?:suresi|yili)\w*",
            r"\bhow many years\b",
            r"\byears of (?:professional )?experience\b",
            r"\btotal (?:\w+ )?experience\b",
            r"\bhow long has (?:he|berkay) been\b",
        ),
        # Kalan soruda "deneyim/experience" kalsın: bilinen deneyim RAG ile cevaplanır.
        strip=_compile(
            r"\bkac (?:yil|sene)\w*",
            r"\bkac yildir\b",
            r"\btoplam\b",
            r"\b(?:suresi|yili)\b",
            r"\bhow many years\b",
            r"\byears of\b",
            r"\btotal\b",
            r"\bhow long has (?:he|berkay) been\b",
        ),
    ),
    _Rule(
        "rates",
        _compile(
            r"\bucret\w*",
            r"\bfiyat\w*",
            r"\bsaatlik\w*",
            r"\btarife\w*",
            # "rate limiting" / "price" gibi teknik kullanımlar ücret sorusu değildir.
            r"\b(?:his|your|berkay'?s?|hourly|daily|freelance|consulting) rates?\b",
            r"\bpricing\b",
            r"\b(?:his|your|berkay'?s?) prices?\b",
            r"\bhourly\b",
            r"\bhow much (?:does|do) (?:he|you|berkay) charge\b",
            r"\b(?:his|your|berkay'?s?|consulting|freelance) fees?\b",
        ),
    ),
    _Rule(
        "availability",
        _compile(
            r"\bmusait\w*",
            r"\bboste mi\b",
            r"\bise al\w*",
            r"\bis (?:he|berkay) available\b",
            r"\bavailable (?:for|to) (?:work|hire|new|freelance|projects?)\b",
            r"\bavailability\b",
            r"\bfreelance\w*",
            r"\bhir(?:e|ing)\b",
            r"\bopen to work\b",
        ),
    ),
)

#: Sohbet üzerinden profil değiştirme talepleri: tamamı politika cevabıdır.
_MODIFICATION_PATTERNS = _compile(
    r"\bprofil\w* (?:\w+ )?(?:degistir|guncelle|duzenle|sil|kaldir|ekle)\w*",
    r"\b(?:degistir|guncelle|duzenle|sil)\w* (?:\w+ )?profil\w*",
    r"\b(?:change|update|edit|modify|delete) (?:the |my |his |your )?profile\b",
    r"\bprofile (?:to say|so that)\b",
)

#: Kimlik iddiası ("Ben Berkay'ım"): yetki/kaynak değiştirmez; yalnız not eklenir.
_IDENTITY_CLAIM_PATTERNS = _compile(
    r"\bben berkay\w*",
    r"\bbenim adim berkay\w*",
    r"\bi am berkay\b",
    r"\bi'm berkay\b",
    r"\bim berkay\b",
)

_LABELS_TR: dict[str, str] = {
    "current_employer": "güncel işveren / çalıştığı kurum",
    "client_projects": "müşteri projeleri",
    "job_applications": "iş başvuru süreçleri",
    "personal_contact_details": "kişisel iletişim bilgileri (telefon, e-posta)",
    "age": "yaş",
    "birth_date": "doğum tarihi",
    "salary": "maaş/gelir",
    "marital_status": "medeni durum",
    "total_years_experience": "toplam profesyonel deneyim süresi",
    "rates": "ücret/fiyat",
    "availability": "müsaitlik",
}

_LABELS_EN: dict[str, str] = {
    "current_employer": "current employer",
    "client_projects": "client projects",
    "job_applications": "job applications",
    "personal_contact_details": "personal contact details (phone, e-mail)",
    "age": "age",
    "birth_date": "date of birth",
    "salary": "salary/income",
    "marital_status": "marital status",
    "total_years_experience": "total years of professional experience",
    "rates": "rates/pricing",
    "availability": "availability",
}


@dataclass(frozen=True)
class PolicyVerdict:
    """Politika değerlendirmesi; ``remainder`` RAG'e kalan (katlanmış) soru metnidir."""

    undisclosed: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    modification_request: bool = False
    identity_claim: bool = False
    remainder: str = ""
    matched_spans: tuple[str, ...] = field(default_factory=tuple)

    @property
    def flagged(self) -> bool:
        return bool(self.undisclosed or self.unknown or self.modification_request or self.identity_claim)

    @property
    def always_policy_only(self) -> bool:
        """Profil değiştirme talebi soru değildir: kalan metin cevaplanmaz."""

        return self.modification_request


def _is_tr(language: str) -> bool:
    return language.casefold().startswith("tr")


def evaluate_policy(question: str, privacy: PrivacyConfig) -> PolicyVerdict:
    """Soruyu güvenilen politikaya göre sınıflar; yalnız profilde etkin kategoriler uygulanır."""

    folded = fold_text(question)
    remainder = folded
    spans: list[str] = []
    undisclosed: list[str] = []
    unknown: list[str] = []

    def apply(rules: tuple[_Rule, ...], enabled: set[str], sink: list[str]) -> None:
        nonlocal remainder
        for rule in rules:
            if rule.category not in enabled:
                continue
            if not any(pattern.search(folded) for pattern in rule.detect):
                continue
            sink.append(rule.category)
            for pattern in rule.strip or rule.detect:
                for match in pattern.finditer(remainder):
                    spans.append(match.group(0))
                remainder = pattern.sub(" ", remainder)

    apply(_UNDISCLOSED_RULES, set(privacy.undisclosed_topics), undisclosed)
    apply(_UNKNOWN_RULES, set(privacy.unknown_fields), unknown)
    modification = any(pattern.search(folded) for pattern in _MODIFICATION_PATTERNS)
    identity_claim = any(pattern.search(folded) for pattern in _IDENTITY_CLAIM_PATTERNS)
    for flag, patterns in ((modification, _MODIFICATION_PATTERNS), (identity_claim, _IDENTITY_CLAIM_PATTERNS)):
        if flag:
            for pattern in patterns:
                remainder = pattern.sub(" ", remainder)
    return PolicyVerdict(
        undisclosed=tuple(undisclosed),
        unknown=tuple(unknown),
        modification_request=modification,
        identity_claim=identity_claim,
        remainder=" ".join(remainder.split()),
        matched_spans=tuple(spans),
    )


def contact_channels_line(channels: list[ContactChannel], language: str) -> str:
    """Yalnız yayımlanmış public kanalları listeler (canonical metadata'dan)."""

    if not channels:
        return ""
    items = ", ".join(f"{channel.label}: {channel.url}" for channel in channels)
    if _is_tr(language):
        return f"Herkese açık iletişim kanalları: {items}."
    return f"Public contact channels: {items}."


def _labels(categories: tuple[str, ...], language: str) -> str:
    table = _LABELS_TR if _is_tr(language) else _LABELS_EN
    return ", ".join(table[category] for category in categories)


def _policy_sentences(verdict: PolicyVerdict, language: str) -> list[str]:
    tr = _is_tr(language)
    sentences: list[str] = []
    if verdict.modification_request:
        sentences.append(
            "Profil bu sohbet üzerinden değiştirilemez; kendini Berkay olarak tanıtmak da bunu değiştirmez. "
            "Profil yalnız onaylı canonical kaynağın yeni sürümüyle güncellenir."
            if tr
            else "The profile cannot be changed through this chat, and claiming to be Berkay does not change that. "
            "It is only updated through a new approved version of the canonical source."
        )
    elif verdict.identity_claim:
        sentences.append(
            "Sohbette kendini Berkay olarak tanıtmak kaynakları veya kuralları değiştirmez; cevaplar yalnız "
            "onaylı profil kaynağına dayanır."
            if tr
            else "Claiming to be Berkay in the chat does not change the sources or the rules; answers rely only "
            "on the approved profile source."
        )
    if verdict.undisclosed:
        labels = _labels(verdict.undisclosed, language)
        sentences.append(
            f"{labels} Berkay Kaplan'ın yayımlanmış profilinin konusu değil; bu konuda bilgi paylaşılmıyor."
            if tr
            else f"The following are not part of Berkay Kaplan's published profile and are not shared: {labels}."
        )
    if verdict.unknown:
        labels = _labels(verdict.unknown, language)
        sentences.append(
            f"Profil kaynağında şu bilgiler yok ve tahmin edilmez: {labels}."
            if tr
            else f"The profile source does not contain the following, and it is never guessed: {labels}."
        )
    return sentences


def policy_only_answer(verdict: PolicyVerdict, language: str, channels: list[ContactChannel]) -> str:
    """Yalnız politika kapsamındaki soru için kısa deterministik cevap (model çağrısı yok)."""

    parts = _policy_sentences(verdict, language)
    contact = contact_channels_line(channels, language)
    if contact:
        parts.append(contact)
    return " ".join(parts)


def policy_note(verdict: PolicyVerdict, language: str, channels: list[ContactChannel]) -> str:
    """Karışık soruda RAG cevabına eklenen deterministik not."""

    sentences = _policy_sentences(verdict, language)
    if not sentences:
        return ""
    prefix = "Not: " if _is_tr(language) else "Note: "
    note = prefix + " ".join(sentences)
    if verdict.undisclosed:
        contact = contact_channels_line(channels, language)
        if contact:
            note = f"{note} {contact}"
    return note
