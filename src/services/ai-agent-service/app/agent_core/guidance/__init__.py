"""Site rehberliği (plan A9): profil tanıtımı, proje rehberi, makale önerisi.

Sorumluluk ayrımı:

- ``models``: yerel iş modelleri (katalog girdisi, öneri, eksik bilgi alanları).
- ``compose``: onaylı kayıtlardan deterministik tr/en metin kompozisyonu;
  kaynakta olmayan bilgi eklenmez.
- ``runner``: port çağrıları + terminal ``AgentOutcome`` üretimi; model
  çağrısı yoktur.

Bu paket donmuş ``web/research/qa/analysis`` modüllerinden bağımsızdır ve
``src/contracts`` sözleşmelerine dokunmaz.
"""

from .compose import (
    compose_profile_answer,
    compose_projects_answer,
    compose_suggestion_answer,
    detect_missing_info_fields,
    missing_info_questions,
    project_interest_tokens,
    suggest_articles,
    unavailable_note,
)
from .models import ArticleCatalogEntry, ArticleSuggestion, GuidanceRunResult, MissingInfoField
from .runner import run_guidance

__all__ = [
    "ArticleCatalogEntry",
    "ArticleSuggestion",
    "GuidanceRunResult",
    "MissingInfoField",
    "compose_profile_answer",
    "compose_projects_answer",
    "compose_suggestion_answer",
    "detect_missing_info_fields",
    "missing_info_questions",
    "project_interest_tokens",
    "run_guidance",
    "suggest_articles",
    "unavailable_note",
]
