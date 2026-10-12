"""Analysis alt akışının yerel modelleri (plan A5).

``AnalysisConfig`` analysis akışının davranış sınırlarıdır; ``AnalysisPlan``
sorunun ayrıştırdığı cevap başlıklarını, ``HeadingCoverage`` kanıt kontrolü
sonucunu taşır. ``AnalysisRunResult`` A4 ``QaRunResult`` ile aynı biçimdedir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import Field, NonNegativeInt, PositiveInt

from ..models import AgentOutcome, BusinessModel
from ..qa.models import QaSectionRef
from ..routing import QuestionPart

__all__ = ["AnalysisConfig", "AnalysisPlan", "AnalysisRunResult", "HeadingCoverage"]


class AnalysisConfig(BusinessModel):
    """Analysis akışının davranış sınırları; fast moddan farklı adım/bütçe şekli.

    ``top_k=6`` fast'ın 4'üne karşı analysis'in daha geniş retrieval kapsamını
    gösterir; ``max_headings`` başlık sayısını ve dolayısıyla araç çağrısı
    üst sınırını sınırlar (bütçe profili yine nihai üst sıradır).
    """

    top_k: PositiveInt = 6
    max_headings: PositiveInt = Field(default=4, gt=1)
    #: Kaynak seçiminde cevap ile bölüm arasında beklenen en az ortak anlamlı terim.
    min_citation_overlap: NonNegativeInt = Field(default=3, ge=1)
    #: Kapsam artırma turu sayısı (plan A5: "gerekirse retrieval kapsamını artır").
    max_expansion_rounds: PositiveInt = 1
    #: Takip sorusunda konuşma geçmişinden sorguya karışan en fazla terim.
    max_history_query_tokens: NonNegativeInt = Field(default=6, ge=0)


class AnalysisPlan(BusinessModel):
    """Sorunun ayrıştırılmasıyla üretilen cevap başlıkları (plan A5)."""

    headings: list[QuestionPart] = Field(min_length=1)


class HeadingCoverage(BusinessModel):
    """Kanıt kontrolünün sonucu: her başlık için destekleyen bölüm indeksleri.

    ``uncovered_indexes`` boş değilse o başlıklar makalede karşılıksızdır;
    cevaba deterministik kapsam notuyla yansıtılır, uydurma atıf üretilmez.
    """

    supported: dict[int, list[int]] = {}
    uncovered_indexes: list[int] = []


@dataclass
class AnalysisRunResult:
    """Bir analysis graph yürütmesinin çıktısı; A4 ``QaRunResult`` biçimi."""

    outcome: AgentOutcome
    state: dict
    sections: list[QaSectionRef] = field(default_factory=list)
