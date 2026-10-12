"""A6 web arama ve kaynak değerlendirme araç katmanı (plan A6).

Sorumluluklar AYRI adaptörlerde:
- ``search_web``    → ``search.HttpWebSearchProvider`` (+ ``tools.SearchWebTool`` bütçe sarmalayıcı)
- ``read_source``   → ``fetch.HttpFetcher`` + ``tools.ReadSourceTool`` (+ ``tools.HttpSourceReader`` port uyumu)
- ``extract_text``  → ``extract.TextExtractor`` (+ ``tools.ExtractTextTool``)
- ``assess_source`` → ``assess.SourceAssessor`` (+ ``tools.AssessSourceTool``)

Ağ korumaları ``ssrf.UrlGuard``'ta yoğunlaşmıştır: DNS çözümleme ve
yönlendirmeler dahil özel/loopback/link-local/metadata adres engeli; süre,
yönlendirme, boyut ve içerik türü sınırları ``settings.WebToolSettings``'te.
Bu katman agent'ın dış araştırma araçlarıdır; backend haberleşmesi değildir.
"""

from .assess import SourceAssessor, publisher_group_of
from .extract import TextExtractor
from .fetch import HttpFetcher
from .models import (
    DuplicateKind,
    EvidenceKind,
    ExtractionStatus,
    ExtractedText,
    FetchedContent,
    SourceAssessment,
    SourceEvidence,
    SourceType,
    WebSourceRecord,
)
from .search import HttpWebSearchProvider
from .settings import WebToolSettings
from .ssrf import ParsedTarget, UrlGuard
from .tools import (
    AssessSourceTool,
    ExtractTextTool,
    HttpSourceReader,
    ReadSourceTool,
    SearchWebTool,
    build_web_tools,
    record_to_evidence,
)

__all__ = [
    "AssessSourceTool",
    "DuplicateKind",
    "EvidenceKind",
    "ExtractionStatus",
    "ExtractedText",
    "FetchedContent",
    "HttpFetcher",
    "HttpSourceReader",
    "HttpWebSearchProvider",
    "ParsedTarget",
    "ReadSourceTool",
    "SearchWebTool",
    "SourceAssessment",
    "SourceAssessor",
    "SourceEvidence",
    "SourceType",
    "TextExtractor",
    "UrlGuard",
    "WebSourceRecord",
    "WebToolSettings",
    "build_web_tools",
    "publisher_group_of",
    "record_to_evidence",
]
