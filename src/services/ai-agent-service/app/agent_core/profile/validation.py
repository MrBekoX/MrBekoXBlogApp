"""Profil cevabının yapı/kaynak/politika denetimi (Who am I).

Model yalnız yapılandırılmış JSON döndürür::

    {"answer": str, "claims": [{"text": str, "sources": ["S1"], "quotes": [str]}]}

Denetimler (kaynak kimliği/alıntı eşleşmesi semantik doğruluğun kusursuz
kanıtı değildir; yapısal guard'dır):

- JSON ayrıştırma kod çiti toleranslıdır (``routing._parse_json_object``
  biçimi; döngüsel import olmaması için burada yeniden uygulanır).
- ``sources`` yalnız o isteğin allowlist etiketlerinden (S1..Sk).
- Her alıntı, atıf verilen parçalardan en az birinin kanıt metninde
  (``fold_text`` + boşluk normalizasyonu sonrası) alt dize olmalıdır.
- Her iddia ≥1 kaynak ve ≥1 alıntı taşır; cevap boş olamaz.
- Cevaptaki URL'ler yalnız yayımlanmış iletişim kanalları, kanıtta birebir
  geçen bağlantılar veya ``/about#<bilinen bölüm>`` olabilir.
- Yasak güçlendirmeler: türetilmiş toplam deneyim yılı, yaş, para tutarı,
  GDPR sertifikası, NestJS uzmanlığı.

İddiasız cevap (``claims == []``) modelin çekimser kalmasıdır: güvenli
yetersiz-bilgi cevabına çevrilir (model metni sunulmaz).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..content.anchors import fold_text
from .chunking import ProfileChunk

__all__ = [
    "EvidenceEntry",
    "ValidatedClaim",
    "ValidationResult",
    "parse_json_object",
    "validate_model_output",
]

_MAX_ANSWER_CHARS = 8000
_MAX_CLAIMS = 16
#: Kısa alıntı (ör. "bir") hemen her parçada geçer; anlamlı destek için en az
#: 12 karakter ve 2 sözcük.
_MIN_QUOTE_CHARS = 12
_MIN_QUOTE_TOKENS = 2
_MAX_QUOTE_CHARS = 600

#: Şemalı bağlantılar ve remark-gfm'in otomatik bağladığı ``www.`` biçimi.
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'`)\]]+", re.IGNORECASE)
#: Markdown bağlantı hedefleri: ``[metin](hedef)``.
_MD_LINK_RE = re.compile(r"\]\(\s*<?([^)\s>]+)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
#: Telefon benzeri rakam dizisi (ayraçlı olabilir); 9+ rakam ise denetlenir.
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
#: Kanıtta geçmesi gereken çok basamaklı sayılar (yıl, sürüm, adet).
_NUMBER_RE = re.compile(r"(?<![\w.])\d{2,}(?:[.,]\d+)*")
_ABOUT_RE = re.compile(r"(?<![\w/])/about#([A-Za-z0-9-]+)")
_LABEL_RE = re.compile(r"^\[?\s*(S\d{1,3})\s*\]?$", re.IGNORECASE)
_INLINE_LABEL_RE = re.compile(r"\s*[\[(]\s*S\d{1,3}(?:\s*[,;]\s*S\d{1,3})*\s*[\])]")
_QUOTE_TRIM = " \t\n\r\"'`“”‘’«».,;:!?…-*_"

#: Kaynakta bulunmayan alanların türetilmiş değerleri (katlanmış metinde).
_FORBIDDEN_AMPLIFICATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("toplam deneyim yılı türetilemez", re.compile(r"(?<!\d)\d{1,2}\s*\+?\s*(?:yil|sene)(?:lik)?\s+(?:\w+\s+)?(?:deneyim|tecrube)")),
    ("toplam deneyim yılı türetilemez", re.compile(r"(?:deneyim|tecrube)\w*\s+(?:\w+\s+)?(?<!\d)\d{1,2}\s*\+?\s*(?:yil|sene)")),
    ("years of experience cannot be derived", re.compile(r"(?<!\d)\d{1,2}\s*\+?\s*years?\s+of\s+(?:\w+\s+)?experience")),
    ("years of experience cannot be derived", re.compile(r"experience\s+of\s+\d{1,2}\s*\+?\s*years?")),
    ("toplam deneyim yılı türetilemez", re.compile(r"(?<!\d)\d{1,2}\s*\+?\s*(?:yildir|senedir)\b")),
    ("years of experience cannot be derived", re.compile(r"\bfor\s+(?:over\s+|about\s+|nearly\s+|almost\s+)?\d{1,2}\s*\+?\s*years?\b")),
    ("yaş türetilemez", re.compile(r"(?<!\d)\d{1,2}\s*yas(?:inda|indaki|indadir|i)\w*")),
    ("age cannot be derived", re.compile(r"(?<!\d)\d{1,2}\s*-?\s*years?\s*-?\s*old\b")),
    ("doğum yılı türetilemez", re.compile(r"(?:19|20)\d{2}\s*(?:dogumlu|yilinda dogdu)")),
    ("birth year cannot be derived", re.compile(r"\bborn\b[^.]{0,20}\b(?:19|20)\d{2}\b")),
    ("age cannot be derived", re.compile(r"\baged?\s+\d+")),
    ("para tutarı/ücret uydurulamaz", re.compile(r"\d[\d.,]*\s*(?:tl|try|usd|eur|euro|dolar|dollars?|lira)\b")),
    ("para tutarı/ücret uydurulamaz", re.compile(r"[₺$€£]\s*\d")),
    ("GDPR sertifikası/bağımsız uyum iddiası yok", re.compile(r"gdpr[\s-]*(?:sertifika|certified|certification|onayli)")),
    ("GDPR sertifikası/bağımsız uyum iddiası yok", re.compile(r"(?:sertifikali|certified)\s+(?:\w+\s+)?gdpr")),
    ("NestJS yalnız incelendi; uzmanlık değil", re.compile(r"nestjs\s+(?:uzmani|uzmanligi|expert|expertise)")),
    ("NestJS yalnız incelendi; uzmanlık değil", re.compile(r"(?:expert|uzman)\w*\s+(?:in\s+|on\s+)?nestjs")),
)


@dataclass(frozen=True)
class EvidenceEntry:
    """Modele etiketle gösterilen tek kanıt parçası."""

    label: str
    chunk: ProfileChunk


@dataclass(frozen=True)
class ValidatedClaim:
    text: str
    labels: tuple[str, ...]
    quotes: tuple[str, ...]


@dataclass
class ValidationResult:
    ok: bool
    abstained: bool = False
    answer: str = ""
    claims: list[ValidatedClaim] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def cited_labels(self) -> list[str]:
        ordered: list[str] = []
        for claim in self.claims:
            for label in claim.labels:
                if label not in ordered:
                    ordered.append(label)
        return ordered


def parse_json_object(text: str) -> dict | None:
    """Model metninden ilk JSON nesnesini çıkarır; kod çiti toleranslı."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
    return parsed if isinstance(parsed, dict) else None


def _normalize(text: str) -> str:
    cleaned = text.replace("**", "").replace("`", "")
    for source, target in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-")):
        cleaned = cleaned.replace(source, target)
    return " ".join(fold_text(cleaned).split())


def _normalize_url(url: str) -> str:
    """Şema ve biçim artıklarından bağımsız karşılaştırma anahtarı (``**url**`` dahil)."""

    cleaned = url.strip("*_").rstrip(".,;:!?*_").rstrip("/").casefold()
    return re.sub(r"^https?://", "", cleaned)


def _allowed_urls(evidence: list[EvidenceEntry], channel_urls: list[str]) -> set[str]:
    allowed = {_normalize_url(url) for url in channel_urls}
    for entry in evidence:
        for match in _URL_RE.finditer(entry.chunk.evidence_text):
            allowed.add(_normalize_url(match.group(0)))
    return allowed


def _check_amplifications(text: str) -> list[str]:
    folded = fold_text(text)
    errors: list[str] = []
    for message, pattern in _FORBIDDEN_AMPLIFICATIONS:
        if pattern.search(folded) and message not in errors:
            errors.append(message)
    return errors


def _check_contact_and_numbers(text: str, evidence: list[EvidenceEntry], channel_urls: list[str]) -> list[str]:
    """Kanıtta olmayan iletişim bilgisi ve sayı (yıl/sürüm/adet) üretilmesini reddeder.

    E-posta/telefon profilde paylaşılmaz; çok basamaklı her sayı verilen kanıtta
    (veya beyan tarihinde / kanal bağlantısında) geçmelidir. Dile bağımsız bir
    uydurma-olgu guard'ıdır: İngilizce cevap Türkçe kanıttaki sayıyı korur.
    """

    sources = [entry.chunk.evidence_text for entry in evidence]
    sources += [entry.chunk.as_of or "" for entry in evidence]
    sources += channel_urls
    haystack = " ".join(sources)
    haystack_digits = re.sub(r"\D", "", haystack)
    errors: list[str] = []
    for match in _EMAIL_RE.finditer(text):
        if match.group(0) not in haystack:
            errors.append("cevap kanıtta olmayan bir e-posta adresi içeriyor")
            break
    for match in _PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) >= 9 and digits not in haystack_digits:
            errors.append("cevap kanıtta olmayan bir telefon numarası içeriyor")
            break
    known_numbers = set(_NUMBER_RE.findall(haystack))
    for number in _NUMBER_RE.findall(text):
        if number not in known_numbers:
            errors.append(f"cevaptaki {number} sayısı kanıtta geçmiyor")
            break
    return errors


def clean_answer_labels(answer: str) -> str:
    """Cevap gövdesindeki ``[S1]`` biçimli etiketleri kaldırır (atıflar ayrı taşınır)."""

    return _INLINE_LABEL_RE.sub("", answer).strip()


def validate_model_output(
    text: str,
    evidence: list[EvidenceEntry],
    *,
    channel_urls: list[str],
    known_section_ids: frozenset[str],
) -> ValidationResult:
    """Model çıktısını yapı, kaynak, alıntı, URL ve politika açısından denetler."""

    payload = parse_json_object(text or "")
    if payload is None:
        return ValidationResult(ok=False, errors=["çıktı geçerli bir JSON nesnesi değil"])
    answer = payload.get("answer")
    claims_raw = payload.get("claims")
    if not isinstance(answer, str) or not answer.strip():
        return ValidationResult(ok=False, errors=["'answer' boş olmayan metin olmalı"])
    if not isinstance(claims_raw, list):
        return ValidationResult(ok=False, errors=["'claims' liste olmalı"])
    if not claims_raw:
        # İddiasız cevap: model çekimser kaldı; metni sunulmaz.
        return ValidationResult(ok=False, abstained=True, errors=["cevap iddia/kaynak taşımıyor (çekimser)"])
    if len(claims_raw) > _MAX_CLAIMS:
        return ValidationResult(ok=False, errors=[f"en fazla {_MAX_CLAIMS} iddia olabilir"])
    if len(answer) > _MAX_ANSWER_CHARS:
        return ValidationResult(ok=False, errors=["cevap çok uzun"])

    by_label = {entry.label: entry for entry in evidence}
    errors: list[str] = []
    claims: list[ValidatedClaim] = []
    for index, raw in enumerate(claims_raw, start=1):
        if not isinstance(raw, dict):
            errors.append(f"iddia {index}: nesne olmalı")
            continue
        claim_text = raw.get("text")
        sources = raw.get("sources")
        quotes = raw.get("quotes")
        if not isinstance(claim_text, str) or not claim_text.strip():
            errors.append(f"iddia {index}: 'text' boş olamaz")
            continue
        if not isinstance(sources, list) or not sources:
            errors.append(f"iddia {index}: en az bir kaynak etiketi gerekli")
            continue
        labels: list[str] = []
        for source in sources:
            match = _LABEL_RE.match(str(source).strip()) if isinstance(source, str) else None
            label = match.group(1).upper() if match else None
            if label is None or label not in by_label:
                errors.append(f"iddia {index}: izin verilmeyen kaynak etiketi {str(source)[:20]!r}")
                labels = []
                break
            if label not in labels:
                labels.append(label)
        if not labels:
            continue
        if not isinstance(quotes, list) or not quotes:
            errors.append(f"iddia {index}: en az bir birebir alıntı gerekli")
            continue
        evidence_norm = [_normalize(by_label[label].chunk.evidence_text) for label in labels]
        quote_ok = True
        kept_quotes: list[str] = []
        for quote in quotes:
            if not isinstance(quote, str):
                errors.append(f"iddia {index}: alıntı metin olmalı")
                quote_ok = False
                break
            norm = _normalize(quote).strip(_QUOTE_TRIM)
            if (
                len(norm) < _MIN_QUOTE_CHARS
                or len(norm) > _MAX_QUOTE_CHARS
                or len(norm.split()) < _MIN_QUOTE_TOKENS
            ):
                errors.append(f"iddia {index}: alıntı uzunluğu geçersiz")
                quote_ok = False
                break
            if not any(norm in text_norm for text_norm in evidence_norm):
                errors.append(f"iddia {index}: alıntı atıf verilen kaynak parçasında bulunamadı")
                quote_ok = False
                break
            kept_quotes.append(quote.strip())
        if not quote_ok:
            continue
        claims.append(ValidatedClaim(text=claim_text.strip(), labels=tuple(labels), quotes=tuple(kept_quotes)))

    combined = " ".join([answer, *(claim.text for claim in claims)])
    allowed = _allowed_urls(evidence, channel_urls)
    for match in _URL_RE.finditer(combined):
        if _normalize_url(match.group(0)) not in allowed:
            errors.append("cevap izin verilmeyen bir bağlantı içeriyor")
            break
    for match in _MD_LINK_RE.finditer(combined):
        target = match.group(1)
        if target.startswith("/about#"):
            continue
        if not _URL_RE.match(target) or _normalize_url(target) not in allowed:
            errors.append("cevap izin verilmeyen bir bağlantı hedefi içeriyor")
            break
    for match in _ABOUT_RE.finditer(combined):
        if match.group(1) not in known_section_ids:
            errors.append("cevap bilinmeyen bir /about bölümüne bağlantı veriyor")
            break
    errors.extend(_check_contact_and_numbers(combined, evidence, channel_urls))
    errors.extend(_check_amplifications(combined))

    if errors:
        return ValidationResult(ok=False, errors=errors[:10])
    return ValidationResult(ok=True, answer=clean_answer_labels(answer), claims=claims)
