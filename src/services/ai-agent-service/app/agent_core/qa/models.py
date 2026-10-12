"""Makale soru-cevap akışının yerel iş modelleri (plan A4).

Plan A4'ün altı node sorumluluğunun ara değerleri: yeterlilik kararı
(``SufficiencyVerdict``), doğrulanmış bölüm referansı (``QaSectionRef``) ve
terminal sonucu sarmalayan ``QaRunResult``. Tümü seriye atılabilir
``BusinessModel``/dataclass'tır; ``src/contracts`` sözleşmelerine dokunmaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import Field, NonNegativeInt

from ..models import AgentOutcome, BusinessModel

if TYPE_CHECKING:  # döngüsel import yok: yalnız tip denetimi
    from ..state.state import AgentState  # noqa: F401

__all__ = ["QaFlowConfig", "QaRunResult", "QaSectionRef", "SufficiencyVerdict"]


class QaFlowConfig(BusinessModel):
    """QA akışının davranış sınırları; hepsi sınırlı ve denetlenebilirdir.

    ``max_retrieval_attempts=2`` plan A4 kuralının karşılığıdır: "Kaynak
    yetersizliğinde sınırlı bir sorgu düzenleme denemesi yap" — bir orijinal
    + bir düzenlenmiş arama; daha fazlası denenmez [LG-RAG#C1].
    """

    top_k: int = Field(default=4, gt=0)
    max_retrieval_attempts: int = Field(default=2, gt=0)
    #: Kaynak seçiminde cevap ile bölüm arasında beklenen en az ortak anlamlı terim.
    #: 3 eşiği, kod çiti gibi tesadüfi belirteçlerden gelen yanlış atıfları süzer.
    min_citation_overlap: int = Field(default=3, ge=1)
    #: Takip sorusunda konuşma geçmişinden sorguya karışan en fazla terim.
    max_history_query_tokens: int = Field(default=6, ge=0)


class SufficiencyVerdict(BusinessModel):
    """Yeterlilik değerlendirmesinin sonucu (plan A4 node sorumluluğu).

    ``retry_scheduled`` koşullu graph kenarının karar girdisidir: true ise
    akış düzenlenmiş sorguyla ``retrieve``'a döner, değilse ``finalize``
    yetersiz-bilgi yoluyla biter [LG-RAG#C1].
    """

    sufficient: bool
    reason: str = Field(max_length=500)
    #: Soru "makale hakkında genel" sınıfındaysa (ana fikir/özet) her bölüm kanıt sayılır.
    generic_question: bool = False
    matched_chunk_indexes: list[NonNegativeInt] = []
    retry_scheduled: bool = False


class QaSectionRef(BusinessModel):
    """Cevabın dayandığı doğrulanmış makale bölümü; bağlantı canonical URL'dendir.

    ``url`` indeksleme anında ``build_canonical_url`` ile doğrulanmış makale
    URL şablonundan üretilmiştir (plan A4: "Bölüm bağlantılarını doğrulanmış
    makale URL'sinden üret"); URL'siz indeks kaydında ``None`` kalır.
    """

    chunk_index: NonNegativeInt
    source_id: str = Field(max_length=512)
    heading_path: list[str] = []
    anchor: str | None = None
    url: str | None = Field(default=None, max_length=2048)


@dataclass
class QaRunResult:
    """Bir QA graph yürütmesinin çıktısı; A2 ``GraphRunResult`` ile aynı biçimdedir."""

    outcome: AgentOutcome
    state: dict
    sections: list[QaSectionRef] = field(default_factory=list)
