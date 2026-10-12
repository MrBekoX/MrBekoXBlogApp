"""``extract_text``: getirilen içeriğinden başlık/metadata/temiz metin çıkarma (plan A6).

Yalnız standart kütüphane ``html.parser`` kullanılır. Script/style/noscript/
template/svg/iframe içerikleri metne karışmaz; blok düzey etiketler satır
sınırı üretir. Metadata kaynakları: ``og:site_name`` (yayıncı),
``article:published_time`` / ``<meta name=date|pubdate>`` / ``<time datetime>``
(yayın tarihi). Güvenilir tarih yoksa ``published_at=None`` kalır — bulunmayan
tarih UYDURULMAZ (plan A6).

Kaynak içi talimatlar VERİDİR (plan A6; [LG-RAG#C2]): bu modül sayfa
metnindeki hiçbir ifadeyi komut olarak yorumlamaz; metin olduğu gibi
``text`` alanına taşınır ve içerideki talimatın çıkarma davranışını
değiştirmesi yapısal olarak imkânsızdır (kod akışı metne koşullu dallanmaz).

Erişim engeli / CAPTCHA şüphesi HTTP 200 dönen sayfalarda durum olarak
raporlanır (``blocked`` / ``captcha_suspected``); taşıma koşulları istisna
değildir.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from .models import ExtractedText, ExtractionStatus, FetchedContent
from .settings import WebToolSettings

__all__ = ["TextExtractor"]

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "canvas"})
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "section", "article", "header", "footer", "main", "aside", "nav",
        "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote", "pre", "table",
        "ul", "ol", "dl", "dd", "dt", "figure", "figcaption", "br", "hr",
    }
)

_PUBLISHED_META_KEYS = frozenset(
    {
        "article:published_time",
        "date",
        "pubdate",
        "dc.date",
        "dc.date.issued",
        "datepublished",
        "publish-date",
        "parsely-pub-date",
        "sailthru.date",
    }
)
_PUBLISHER_META_KEYS = ("og:site_name", "application-name", "publisher", "twitter:site")

_BLANK_LINE_RE = re.compile(r"\n{3,}")
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")

_CAPTCHA_MARKERS = (
    "captcha",
    "just a moment...",
    "attention required",
    "checking your browser",
    "cf-browser-verification",
    "cf_chl_opt",
    "enable javascript and cookies to continue",
    "ddos protection by",
    "unusual traffic",
    "verifying you are human",
)
_BLOCKED_MARKERS = (
    "access denied",
    "403 forbidden",
    "forbidden |",
    "you don't have permission to access",
    "error 403",
    "banned",
)


def _parse_datetime(raw: str) -> datetime | None:
    """ISO 8601 tarih/saat ayrıştırır; geçersizse ``None`` (uydurma yok)."""
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class _PageParser(HTMLParser):
    """Başlık, metadata ve görünür metni toplayan sınırlı ayrıştırıcı."""

    def __init__(self, *, max_text_chars: int) -> None:
        super().__init__(convert_charrefs=True)
        self._max_text_chars = max_text_chars
        self.title: str | None = None
        self.meta_published: datetime | None = None
        self.meta_publisher: str | None = None
        self.meta_charset_hint: str | None = None
        self.first_time_attr: datetime | None = None
        self._in_title = False
        self._title_parts: list[str] = []
        self._skip_depth = 0
        self._pieces: list[str] = []

    # -- etiketler --------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            self._absorb_meta(attr_map)
        elif tag == "time" and self.first_time_attr is None:
            raw = attr_map.get("datetime") or attr_map.get("date")
            if raw:
                self.first_time_attr = _parse_datetime(raw)
        elif tag == "title":
            self._in_title = True
        elif tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag in _BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in _BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._skip_depth > 0:
            return
        text = data.strip()
        if text:
            self._pieces.append(text + " ")
            self._guard_length()

    # -- yardımcılar ------------------------------------------------------

    def _absorb_meta(self, attr_map: dict[str, str]) -> None:
        name = (attr_map.get("name") or attr_map.get("property") or attr_map.get("itemprop") or "").lower()
        content = (attr_map.get("content") or "").strip()
        charset = attr_map.get("charset")
        if charset and self.meta_charset_hint is None:
            self.meta_charset_hint = charset
        if not name or not content:
            return
        if name in _PUBLISHED_META_KEYS and self.meta_published is None:
            self.meta_published = _parse_datetime(content)
        elif name in _PUBLISHER_META_KEYS and self.meta_publisher is None:
            cleaned = content.lstrip("@").strip()
            self.meta_publisher = cleaned or None

    def _guard_length(self) -> None:
        if sum(len(p) for p in self._pieces[-8:]) > self._max_text_chars * 1.2:
            # Uzun sayfalarda bellek büyümesini sınırla; nihai kesim extract'te.
            del self._pieces[:-400]

    # -- sonuç ------------------------------------------------------------

    def result_text(self) -> str:
        raw = "".join(self._pieces)
        lines = (_SPACE_RE.sub(" ", line).strip() for line in raw.split("\n"))
        collapsed = "\n".join(line for line in lines if line)
        return _BLANK_LINE_RE.sub("\n\n", collapsed).strip()

    def result_title(self) -> str | None:
        title = _SPACE_RE.sub(" ", "".join(self._title_parts)).strip()
        return title[:512] or None


class TextExtractor:
    """``FetchedContent`` → ``ExtractedText``; durumsal raporlama taşır."""

    def __init__(self, settings: WebToolSettings) -> None:
        self._settings = settings

    def extract(self, content: FetchedContent) -> ExtractedText:
        """Getirilen gövdeden temiz metin ve metadata çıkarır; asla Web'e gitmez.

        Raises:
            PortError: ``validation_error`` — içerik boş referanslı değilse bile
                çağrı sözleşmesi bozulursa (gövdesiz içerik hariç: durum ``empty``).
        """
        media = (content.content_type or "").split(";", 1)[0].strip().lower()
        if media and not self._is_supported(media):
            return self._result(content, status=ExtractionStatus.UNSUPPORTED_CONTENT_TYPE, text="")

        charset, body = self._resolve_charset(content)
        try:
            decoded = body.decode(charset, errors="strict")
        except (UnicodeDecodeError, LookupError):
            try:
                decoded = body.decode("utf-8", errors="replace")
            except Exception:  # pragma: no cover - replace her byte dizisini alır
                return self._result(content, status=ExtractionStatus.DECODE_ERROR, text="")

        is_html = media in ("text/html", "application/xhtml+xml") or (
            not media and re.search(r"<\s*(!doctype|html)", decoded[:512], re.IGNORECASE) is not None
        )
        if is_html:
            parser = _PageParser(max_text_chars=self._settings.max_text_chars)
            try:
                parser.feed(decoded)
                parser.close()
            except Exception:
                # Bozuk HTML: ayrıştırıcının çıkardığı kadarı kullanılır.
                pass
            text = parser.result_text()
            title = parser.result_title()
            publisher = parser.meta_publisher
            published = parser.meta_published or parser.first_time_attr
            status = self._page_status(text, title)
        else:
            text = _BLANK_LINE_RE.sub("\n\n", decoded.strip())
            if len(text) > self._settings.max_text_chars:
                text = text[: self._settings.max_text_chars]
            title = None
            publisher = None
            published = None
            status = ExtractionStatus.OK if text else ExtractionStatus.EMPTY

        return self._result(content, status=status, text=text, title=title, publisher=publisher, published=published)

    # -- yardımcılar ------------------------------------------------------

    def _result(
        self,
        content: FetchedContent,
        *,
        status: ExtractionStatus,
        text: str,
        title: str | None = None,
        publisher: str | None = None,
        published: datetime | None = None,
    ) -> ExtractedText:
        normalized = text.strip()
        return ExtractedText(
            url=content.requested_url,
            final_url=content.final_url,
            title=title,
            publisher=publisher,
            published_at=published,
            accessed_at=content.fetched_at,
            content_type=content.content_type,
            extraction_status=status,
            text=normalized[: self._settings.max_text_chars],
            content_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        )

    def _page_status(self, text: str, title: str | None) -> ExtractionStatus:
        """HTTP 200 sayfalarda engel/CAPTCHA/boş durum ayrımı (raporlama)."""
        if not text:
            return ExtractionStatus.EMPTY
        if len(text) > 4000:
            return ExtractionStatus.OK
        window = f"{title or ''}\n{text[:2000]}".lower()
        if any(marker in window for marker in _CAPTCHA_MARKERS):
            return ExtractionStatus.CAPTCHA_SUSPECTED
        if any(marker in window for marker in _BLOCKED_MARKERS):
            return ExtractionStatus.BLOCKED
        return ExtractionStatus.OK

    def _is_supported(self, media: str) -> bool:
        return any(media.startswith(prefix) for prefix in self._settings.allowed_content_types)

    def _resolve_charset(self, content: FetchedContent) -> tuple[str, bytes]:
        """Karakter setini Content-Type → BOM → meta charset sırasıyla çözer."""
        body = content.body
        declared = None
        if content.content_type and "charset=" in content.content_type.lower():
            declared = content.content_type.split("charset=", 1)[1].split(";", 1)[0].strip(' "\'')
        if body.startswith(b"\xef\xbb\xbf"):
            return ("utf-8", body[3:])
        if body.startswith(b"\xff\xfe") or body.startswith(b"\xfe\xff"):
            return ("utf-16", body)
        if declared:
            try:
                b"".decode(declared)  # codec var mı?
                return (declared, body)
            except (LookupError, UnicodeDecodeError):
                pass
        # meta charset için ilk 2 KB taranır (ASCII tabanlı kodlamalarda güvenli)
        head = body[:2048].decode("latin-1", errors="replace").lower()
        match = re.search(r'charset\s*=\s*["\']?([a-z0-9_\-]+)', head)
        if match:
            candidate = match.group(1)
            try:
                b"".decode(candidate)
                return (candidate, body)
            except (LookupError, UnicodeDecodeError):
                pass
        return ("utf-8", body)
