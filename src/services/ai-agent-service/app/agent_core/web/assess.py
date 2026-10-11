"""``assess_source``: kaynak türü, öncelik, kopya ve bağımsızlık değerlendirmesi (plan A6).

Plan kuralları:
- "Teknik konularda resmî belgeleri, özgün araştırmaları ve proje
  kaynaklarını önceliklendir" → ``priority_rank`` 0 (resmî/araştırma),
  1 (proje), 2 (blog/haber/mühendislik yazısı), 3 (forum), 2 (bilinmeyen —
  varsayım yerine muhafazakâr orta öncelik).
- "Benzer ve kopya kaynakları ayır" → içerik hash'i eşitliği tam kopya;
  kelime 5-gram Jaccard benzerliği ≥ 0.8 yakın kopya.
- "Bağımsız kaynak çeşitliliğini dikkate al" → kayıtlı adresler eTLD+1
  yayıncı gruplarına indirgenir; grup sayısı bağımsızlık göstergesidir.
- "Arama snippet'ini tam sayfa okunmuş gibi değerlendirme" →
  ``full_page_read=False`` kayıtlar işaretlenir ve notlandırılır.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import urlparse

from .models import DuplicateKind, ExtractionStatus, SourceAssessment, SourceType, WebSourceRecord

__all__ = ["SourceAssessor", "publisher_group_of"]

#: Çok parçalı genel son ekler; eTLD+1 hesabı için küçük sabit küme.
#: (Kapsamlı PublicSuffix listesi bilinçli dışarıda: bağımlılıksız çalışma.)
_MULTI_PART_SUFFIXES = frozenset(
    {
        "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk",
        "com.tr", "org.tr", "net.tr", "edu.tr", "gov.tr",
        "co.jp", "ne.jp", "or.jp", "ac.jp",
        "com.au", "net.au", "org.au", "edu.au",
        "com.br", "org.br", "gov.br",
        "co.in", "net.in", "org.in",
        "com.mx", "com.ar", "co.za", "com.cn", "co.kr", "co.nz",
    }
)

#: Özgün araştırma barındıran bilinen anahtar adları.
_RESEARCH_HOSTS = ("arxiv.org", "semanticscholar.org", "doi.org", "dl.acm.org", "ieeexplore.ieee.org", "jstor.org")

_PROJECT_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "sourceforge.net")

_FORUM_MARKERS = ("stackoverflow.com", "stackexchange.com", "reddit.com", "superuser.com", "serverfault.com")

_NEWS_PATHS = ("/news", "/press", "/press-release")

_WORD_RE = re.compile(r"[a-z0-9çğıöşü]+", re.IGNORECASE)
_SIMILAR_GRAM = 5
_SIMILAR_THRESHOLD = 0.8
_MAX_SIMILARITY_CHARS = 50_000


def publisher_group_of(url: str) -> str:
    """URL'nin eTLD+1 yayıncı grubunu döndürür; çözülemezse anahtar adının kendisi."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if not host:
        return "unknown"
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _MULTI_PART_SUFFIXES:
        return ".".join(labels[-3:])
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return host


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _gram_set(text: str) -> frozenset[tuple[str, ...]]:
    words = _words(text[:_MAX_SIMILARITY_CHARS])
    if len(words) < _SIMILAR_GRAM:
        return frozenset({tuple(words)}) if words else frozenset()
    return frozenset(tuple(words[i : i + _SIMILAR_GRAM]) for i in range(len(words) - _SIMILAR_GRAM + 1))


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    if intersection == 0:
        return 0.0
    return intersection / len(a | b)


class SourceAssessor:
    """Tek kaynağı tür/öncelik/kopya/bağımsızlık açısından değerlendirir."""

    def classify_source_type(self, record: WebSourceRecord) -> SourceType:
        """Kural tabanlı tür sınıflaması; eşleşmezse ``unknown`` (uydurma yok)."""
        host = (urlparse(record.final_url).hostname or "").lower().rstrip(".")
        path = urlparse(record.final_url).path.lower()
        if any(host == h or host.endswith("." + h) for h in _RESEARCH_HOSTS):
            return SourceType.ORIGINAL_RESEARCH
        if host.startswith(("docs.", "developer.", "developers.")) or "/docs" in path or path.startswith(("/documentation", "/doc/", "/manual", "/reference")):
            return SourceType.OFFICIAL_DOCS
        if any(host == h or host.endswith("." + h) for h in _PROJECT_HOSTS):
            return SourceType.PROJECT_SOURCE
        if any(marker in host for marker in _FORUM_MARKERS):
            return SourceType.FORUM
        if any(path.startswith(p) for p in _NEWS_PATHS) or host.startswith(("news.", "press.")):
            return SourceType.NEWS
        if host.startswith(("blog.", "blogs.")) or path.startswith("/blog"):
            return SourceType.BLOG
        return SourceType.UNKNOWN

    def _priority_rank(self, source_type: SourceType) -> int:
        return {
            SourceType.OFFICIAL_DOCS: 0,
            SourceType.ORIGINAL_RESEARCH: 0,
            SourceType.PROJECT_SOURCE: 1,
            SourceType.ENGINEERING_ARTICLE: 2,
            SourceType.NEWS: 2,
            SourceType.BLOG: 2,
            SourceType.UNKNOWN: 2,
            SourceType.FORUM: 3,
        }[source_type]

    def _duplicate(self, record: WebSourceRecord, others: Sequence[WebSourceRecord]) -> tuple[str | None, DuplicateKind, float | None]:
        best: tuple[str | None, DuplicateKind, float | None] = (None, DuplicateKind.NONE, None)
        record_grams = None
        for other in others:
            if other.content_hash == record.content_hash and record.text:
                return (self._source_id(other), DuplicateKind.EXACT, 1.0)
            if not record.text or not other.text:
                continue
            if record_grams is None:
                record_grams = _gram_set(record.text)
            similarity = _jaccard(record_grams, _gram_set(other.text))
            if similarity >= _SIMILAR_THRESHOLD and (best[2] is None or similarity > best[2]):
                best = (self._source_id(other), DuplicateKind.NEAR, round(similarity, 4))
        return best

    @staticmethod
    def _source_id(record: WebSourceRecord) -> str:
        # DONMUŞ A1 sözleşmesindeki web kaynak kimliği (url+erişim damgası) ile uyumlu.
        return record.to_source_reference().source_id or f"web:{record.final_url}"

    def assess(
        self,
        record: WebSourceRecord,
        *,
        others: Sequence[WebSourceRecord] = (),
    ) -> SourceAssessment:
        """Kaynağı değerlendirir; ``others`` kopya/bağımsızlık karşılaştırma kümesidir.

        Yerel işlemdir: ağ erişimi ve bütçe olayı üretmez.
        """
        source_type = record.source_type or self.classify_source_type(record)
        rank = self._priority_rank(source_type)
        group = publisher_group_of(record.final_url)
        duplicate_of, duplicate_kind, similarity = self._duplicate(record, others)
        groups = {group}
        for other in others:
            groups.add(publisher_group_of(other.final_url))

        notes: list[str] = []
        if not record.full_page_read:
            notes.append("arama snippet'i tam sayfa sayılmaz; tam sayfa okunmalı")
        if record.published_at is None:
            notes.append("yayın tarihi bulunamadı; uydurulmadı")
        if record.extraction_status == ExtractionStatus.EMPTY:
            notes.append("içerik çıkarılamadı; kanıt olarak kullanılmamalı")
        if duplicate_kind is not DuplicateKind.NONE:
            notes.append(f"kaynak {duplicate_kind.value} kopya: {duplicate_of}")
        if record.extraction_status == ExtractionStatus.OK and source_type in (
            SourceType.OFFICIAL_DOCS,
            SourceType.ORIGINAL_RESEARCH,
            SourceType.PROJECT_SOURCE,
        ):
            notes.append("öncelikli kaynak türü: resmî belge/özgün araştırma/proje kaynağı")

        return SourceAssessment(
            url=record.final_url,
            source_id=self._source_id(record),
            source_type=source_type,
            priority_rank=rank,
            preferred=rank <= 1 and record.full_page_read,
            publisher_group=group,
            duplicate_of=duplicate_of,
            duplicate_kind=duplicate_kind,
            duplicate_similarity=similarity,
            full_page_read=record.full_page_read,
            distinct_publisher_groups=len(groups),
            notes=notes,
        )
