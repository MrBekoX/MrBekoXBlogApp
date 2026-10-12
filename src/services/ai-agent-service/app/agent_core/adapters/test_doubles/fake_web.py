"""Web arama ve kaynak okuma test double'ları."""

from __future__ import annotations

from ...errors import AgentErrorCode, PortError
from ...ports import CancellationToken, ReadSource, WebSearchResult

__all__ = ["FakeSourceReader", "FakeWebSearchProvider"]


class FakeWebSearchProvider:
    """Sabit sonuç kümesi döndüren, sorguları kaydeden test double."""

    is_test_double = True

    def __init__(self, results: list[WebSearchResult] | None = None) -> None:
        self.results = list(results or [])
        self.queries: list[str] = []
        self.call_count = 0

    async def search(
        self, query: str, *, max_results: int = 5, cancel: CancellationToken | None = None
    ) -> list[WebSearchResult]:
        if not query.strip():
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "arama sorgusu boş olamaz",
                port="WebSearchProvider",
            )
        if cancel is not None:
            cancel.raise_if_cancelled()
        self.queries.append(query)
        self.call_count += 1
        return self.results[:max_results]


class FakeSourceReader:
    """Sözlük temelli kaynak okuyucu; kayıtlı olmayan URL için ``not_found`` üretir."""

    is_test_double = True

    def __init__(self, sources: dict[str, ReadSource] | None = None) -> None:
        self.sources = dict(sources or {})

    async def read(self, url: str, *, cancel: CancellationToken | None = None) -> ReadSource:
        if url.startswith(("file:", "ftp:")):
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"desteklenmeyen adres şeması: {url}",
                port="SourceReader",
            )
        if cancel is not None:
            cancel.raise_if_cancelled()
        try:
            return self.sources[url]
        except KeyError:
            raise PortError(
                AgentErrorCode.NOT_FOUND,
                f"kaynak okunamadı veya bulunamadı: {url}",
                port="SourceReader",
            ) from None
