"""A6 dış araştırma araçları: search_web, read_source, extract_text, assess_source.

Plan: "search_web, read_source, extract_text ve assess_source sorumluluklarını
ayrı adaptörlerde uygula. Bunlar agent'ın dış araştırma araçlarıdır; backend
haberleşmesi değildir."

Bütçe kuralı (plan A6): "Her dış araç denemesi bütçe kaydına yansır."
``SearchWebTool`` ve ``ReadSourceTool`` her denemeyi (retry dahil) ``BudgetGuard.
guarded`` üzerinden yürütür: rezervasyon reddi çağrı öncesi ``budget_exhausted``,
başarısız deneme ``outcome="failed"``, kesinti ``uncertain`` olayı üretir
(A2 semantiği). ``extract_text`` ve ``assess_source`` YERELDİR — ağa gitmez,
bütçe olayı üretmez; bu ayrım bilinçli ve raporlanmıştır.

İptal semantiği [PY-ASYNCIO#C2]: ``CancelledError`` hiçbir araçta
bastırılmaz; kapatma ``finally``'de yapılır.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from ..budget.guard import BudgetGuard, CallResult
from ..budget.policy import Deadline
from ..errors import AgentErrorCode, PortError
from ..models.sources import EvidenceItem, SourceReference
from ..ports import (
    BudgetKind,
    CancellationToken,
    ReadSource,
    WebSearchProvider,
    WebSearchResult,
)
from .assess import SourceAssessor
from .extract import TextExtractor
from .fetch import HttpFetcher
from .models import (
    EvidenceKind,
    ExtractionStatus,
    ExtractedText,
    FetchedContent,
    SourceAssessment,
    SourceEvidence,
    WebSourceRecord,
)
from .settings import WebToolSettings
from .ssrf import UrlGuard

if TYPE_CHECKING:
    from ..state.events import UsageEvent

# A factory avoids sharing reservations and action counters between runs. Tests
# and embedded callers can still supply an explicitly constructed tool mapping.
WebTools = dict[str, object] | Callable[[BudgetGuard], dict[str, object]]

__all__ = [
    "AssessSourceTool",
    "ExtractTextTool",
    "HttpSourceReader",
    "ReadSourceTool",
    "SearchWebTool",
    "build_web_tools",
    "record_to_evidence",
]

_EVIDENCE_EXCERPT_CHARS = 400


def _others_except_self(record: WebSourceRecord, records: Sequence[WebSourceRecord]) -> list[WebSourceRecord]:
    """Kopya karşılaştırma kümesi: kaydın KENDİSİ çıkarılır, diğer kayıtlar kalır.

    "Kendisi": nesne kimliği veya DONMUŞ A1 web kaynak kimliği (url+erişim
    damgası — ``SourceAssessor._source_id``) eşitliği. Yalnız içerik hash'i
    eşit olan FARKLI kayıtlar kümede kalır; böylece gerçek kopya tespiti
    bozulmaz (A7-rapor.md F1: ``assess_many`` kaydı kendi kopyası olarak
    işaretlememeli).
    """
    self_id = SourceAssessor._source_id(record)
    return [other for other in records if other is not record and SourceAssessor._source_id(other) != self_id]


class _ExternalWebTool:
    """Bütçe kayıtlı dış araçların ortak çekirdeği: eylem kimliği + geri çekilme."""

    def __init__(self, guard: BudgetGuard, *, action_prefix: str, settings: WebToolSettings) -> None:
        self._guard = guard
        self._action_prefix = action_prefix
        self._settings = settings
        self._seq = 0

    def _next_action_id(self) -> str:
        self._seq += 1
        return f"{self._action_prefix}:{self._seq}"

    async def _backoff(self, attempt: int, cancel: CancellationToken | None) -> None:
        """Retryden önce sınırlı üstel geri çekilme; iptal beklemede kesilir."""
        if attempt <= 1:
            return
        delay = min(
            self._settings.retry_backoff_cap_s,
            self._settings.retry_backoff_base_s * (2 ** (attempt - 2)),
        )
        if delay <= 0:
            return
        if cancel is not None:
            cancel.raise_if_cancelled()
        await asyncio.sleep(delay)


class SearchWebTool(_ExternalWebTool):
    """``search_web`` aracı: sağlayıcı çağrısını ``WEB_SEARCH_CALL`` bütçesine yazar."""

    def __init__(
        self,
        guard: BudgetGuard,
        provider: WebSearchProvider,
        *,
        settings: WebToolSettings,
        action_prefix: str = "web_search",
    ) -> None:
        super().__init__(guard, action_prefix=action_prefix, settings=settings)
        self._provider = provider

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        cancel: CancellationToken | None = None,
        deadline: Deadline | None = None,
        events_sink: list["UsageEvent"] | None = None,
    ) -> list[WebSearchResult]:
        """Sorguyu sağlayıcı üzerinden yürütür; her deneme bütçe olayı üretir.

        Boş sorgu rezervasyondan ÖNCE reddedilir — çağrı başlamadığı için
        bütçe olayı üretilmez (A2 semantiği).

        Raises:
            PortError: sağlayıcı/bütçe/iptal hataları; ``budget_exhausted``,
                ``validation_error``, ``config_error``, ``provider_error``,
                ``timeout``, ``cancelled``.
        """
        if not isinstance(query, str) or not query.strip():
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "arama sorgusu boş olamaz",
                port="SearchWebTool",
            )
        action_id = self._next_action_id()

        async def call(attempt: int) -> CallResult:
            await self._backoff(attempt, cancel)
            return CallResult(value=await self._provider.search(query, max_results=max_results, cancel=cancel))

        outcome = await self._guard.guarded(
            action_id=action_id,
            kind=BudgetKind.WEB_SEARCH_CALL,
            call=call,
            cancel=cancel,
            deadline=deadline,
            events_sink=events_sink,
        )
        results: list[WebSearchResult] = outcome.value
        return results


class ReadSourceTool(_ExternalWebTool):
    """``read_source`` aracı: getirme+çıkarmayı ``SOURCE_PAGE_READ`` bütçesine yazar.

    Taşıma düzeyi arızalar (HTTP 403/404, DNS, timeout) PortError olarak
    yükselir; HTTP 200 dönen engel/CAPTCHA/boş sayfalar kayıt durumlarıyla
    raporlanır (plan A6: "erişim engeli, CAPTCHA ve çıkarılamayan içeriği
    raporla").
    """

    def __init__(
        self,
        guard: BudgetGuard,
        fetcher: HttpFetcher,
        extractor: TextExtractor,
        *,
        settings: WebToolSettings,
        action_prefix: str = "read_source",
    ) -> None:
        super().__init__(guard, action_prefix=action_prefix, settings=settings)
        self._fetcher = fetcher
        self._extractor = extractor

    async def read(
        self,
        url: str,
        *,
        cancel: CancellationToken | None = None,
        deadline: Deadline | None = None,
        events_sink: list["UsageEvent"] | None = None,
    ) -> WebSourceRecord:
        """Kaynağı okur; plan A6 kaynak modelini (WebSourceRecord) döndürür.

        Raises:
            PortError: getirme/içerik türü/engel/bütçe/iptal hataları.
        """
        if not isinstance(url, str) or not url.strip():
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "kaynak adresi boş olamaz",
                port="ReadSourceTool",
            )
        self._fetcher.parse_url(url)  # şema/port reddi: çağrı başlamadan, bütçesiz
        action_id = self._next_action_id()

        async def call(attempt: int) -> CallResult:
            await self._backoff(attempt, cancel)
            content = await self._fetcher.fetch(url, cancel=cancel, deadline=deadline)
            extracted = self._extractor.extract(content)
            return CallResult(value=(content, extracted))

        outcome = await self._guard.guarded(
            action_id=action_id,
            kind=BudgetKind.SOURCE_PAGE_READ,
            call=call,
            cancel=cancel,
            deadline=deadline,
            events_sink=events_sink,
        )
        content: FetchedContent
        extracted: ExtractedText
        content, extracted = outcome.value
        return self._record(content, extracted)

    def _record(self, content: FetchedContent, extracted: ExtractedText) -> WebSourceRecord:
        """Getirme+çıkarma sonucunu plan alanlı kayda çevirir ve kanıtlar."""
        accessed = content.fetched_at
        evidences: list[SourceEvidence] = []
        if extracted.text:
            excerpt = extracted.text[:_EVIDENCE_EXCERPT_CHARS]
            evidences.append(
                SourceEvidence(
                    kind=EvidenceKind.FULL_PAGE,
                    excerpt=excerpt,
                    char_start=0,
                    char_end=len(excerpt),
                    collected_at=accessed,
                )
            )
        metadata_bits = []
        if extracted.title:
            metadata_bits.append(f"başlık: {extracted.title}")
        if extracted.publisher:
            metadata_bits.append(f"yayıncı: {extracted.publisher}")
        if extracted.published_at is not None:
            metadata_bits.append(f"yayın tarihi: {extracted.published_at.isoformat()}")
        else:
            metadata_bits.append("yayın tarihi: yok (uydurulmadı)")
        evidences.append(
            SourceEvidence(kind=EvidenceKind.PAGE_METADATA, excerpt="; ".join(metadata_bits), collected_at=accessed)
        )
        return WebSourceRecord(
            url=content.requested_url,
            final_url=content.final_url,
            title=extracted.title,
            publisher=extracted.publisher,
            published_at=extracted.published_at,
            accessed_at=accessed,
            content_hash=hashlib.sha256(extracted.text.encode("utf-8")).hexdigest(),
            extraction_status=extracted.extraction_status,
            source_type=None,  # tür ataması assess_source'un sorumluluğudur
            text=extracted.text,
            content_type=content.content_type,
            full_page_read=True,
            evidences=evidences,
        )


class ExtractTextTool:
    """``extract_text`` aracı: getirilmiş içerikten metin çıkaran YEREL adaptör.

    Ağa gitmez; dış araç denemesi olmadığından bütçe olayı üretmez (plan
    bütçe kuralı "dış araç denemesi" içindir). ``cancel`` arayüz simetrisi
    içindir ve çağrı öncesi denetlenir.
    """

    def __init__(self, extractor: TextExtractor) -> None:
        self._extractor = extractor

    async def extract(
        self,
        content: FetchedContent,
        *,
        cancel: CancellationToken | None = None,
    ) -> ExtractedText:
        if cancel is not None:
            cancel.raise_if_cancelled()
        return self._extractor.extract(content)


class AssessSourceTool:
    """``assess_source`` aracı: kaynak değerlendiren YEREL adaptör.

    Kopya ayrıştırma, öncelik sıralaması ve bağımsız yayıncı grubu sayısını
    ``SourceAssessment`` olarak döndürür; snippet-only kayıtları işaretler.
    """

    def __init__(self, assessor: SourceAssessor | None = None) -> None:
        self._assessor = assessor or SourceAssessor()

    async def assess(
        self,
        record: WebSourceRecord,
        *,
        others: Sequence[WebSourceRecord] = (),
        cancel: CancellationToken | None = None,
    ) -> SourceAssessment:
        if cancel is not None:
            cancel.raise_if_cancelled()
        return self._assessor.assess(record, others=others)

    async def assess_many(
        self,
        records: Sequence[WebSourceRecord],
        *,
        cancel: CancellationToken | None = None,
    ) -> list[SourceAssessment]:
        """Kayıt kümesini birlikte değerlendirir; her kayıt kendisi hariç.

        Kopya/bağımsızlık kümesi verilen tümü olsa da her kayıt kopya
        karşılaştırmasında kendisini ``others`` dışında tutar; farklı
        kayıtlar arasındaki gerçek kopya tespiti etkilenmez.
        """
        if cancel is not None:
            cancel.raise_if_cancelled()
        return [self._assessor.assess(record, others=_others_except_self(record, records)) for record in records]


class HttpSourceReader:
    """``SourceReader`` portu uyumlu ince sarmalayıcı (A1 sözleşmesi DONMUŞ).

    Port modeli ``ReadSource.text`` boş olamayacağından (``min_length=1``)
    çıkarılamayan/boş içerik ``not_found`` koduyla raporlanır; port dışı
    zengin kayıt için ``ReadSourceTool`` kullanılır.
    """

    def __init__(self, fetcher: HttpFetcher, extractor: TextExtractor) -> None:
        self._fetcher = fetcher
        self._extractor = extractor

    async def read(self, url: str, *, cancel: CancellationToken | None = None) -> ReadSource:
        """Port sözleşmesi: URL içeriğini okur, temizlenmiş metni döndürür.

        Raises:
            PortError: ``not_found`` — kaynak yok/kaldırılmış/içerik boş;
                ``validation_error`` — yasak şema/adres; ``provider_error`` /
                ``timeout`` / ``cancelled``.
        """
        if not isinstance(url, str) or not url.strip():
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "kaynak adresi boş olamaz",
                port="SourceReader",
            )
        content = await self._fetcher.fetch(url, cancel=cancel)
        extracted = self._extractor.extract(content)
        text = extracted.text.strip()
        if not text:
            raise PortError(
                AgentErrorCode.NOT_FOUND,
                f"kaynak boş veya çıkarılamayan içerik: {content.final_url} "
                f"(durum: {extracted.extraction_status.value})",
                port="SourceReader",
            )
        return ReadSource(
            url=content.final_url,
            title=extracted.title,
            text=text[:500_000],
            fetched_at=content.fetched_at,
            content_type=content.content_type,
        )


def build_web_tools(
    guard: BudgetGuard,
    settings: WebToolSettings,
    *,
    search_provider: WebSearchProvider | None = None,
) -> dict[str, object]:
    """A6 araç kümesini tek noktadan kurar (A7 graph katmanı bunu kullanır).

    ``search_provider`` verilmezse arama aracı kurulmaz (sağlayıcı kararı
    operatör yapılandırmasına bağlıdır). Dönen sözlük anahtarları:
    ``search_web`` (varsa), ``read_source``, ``extract_text``, ``assess_source``,
    ``source_reader``, ``fetcher``.
    """
    url_guard = UrlGuard.from_settings(settings)
    fetcher = HttpFetcher(settings, url_guard)
    extractor = TextExtractor(settings)
    assessor = SourceAssessor()

    tools: dict[str, object] = {
        "read_source": ReadSourceTool(guard, fetcher, extractor, settings=settings),
        "extract_text": ExtractTextTool(extractor),
        "assess_source": AssessSourceTool(assessor),
        "source_reader": HttpSourceReader(fetcher, extractor),
        "fetcher": fetcher,
    }
    if search_provider is not None:
        tools["search_web"] = SearchWebTool(guard, search_provider, settings=settings)
    return tools


# --- Kanıt köprüsü (A7'nin DONMUŞ sözleşmeyle çalışması için) ---------------


def record_to_evidence(record: WebSourceRecord, evidence_id: str, excerpt: str) -> EvidenceItem:
    """Zengin web kaydını DONMUŞ ``EvidenceItem`` sözleşmesine daraltır."""
    reference: SourceReference = record.to_source_reference()
    return EvidenceItem(
        evidence_id=evidence_id,
        source=reference,
        excerpt=excerpt[:20000],
        collected_at=record.accessed_at,
    )
