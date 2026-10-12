"""İş birliği hazırlığı (plan A9): çıkarım, sorular, ActionProposal, onay/resume.

Sorumluluk ayrımı:

- ``models``: detay/state/resume-girdisi iş modelleri + durum makinesi aşamaları.
- ``extract``: deterministik tr/en çıkarım; eksik zorunlu alan tahmin edilmez.
- ``proposal``: düzenlenebilir özet + içerik hash'li ``ActionProposal`` üretimi.
- ``runner``: durum makinesi; ``needs_input``'ta durur, onayı sürüm ve
  doğrulanmış ``ValidatedActionResult`` ile işler.

SINIR: bu paket backend'e talep kaydetmez ve e-posta göndermez; kayıt/onay
haberleşme planındadır (B9/B10).
"""

from .extract import extract_collaboration_details, merge_answer, questions_for_missing_fields
from .models import (
    COLLAB_STATE_SCHEMA_VERSION,
    CollabField,
    CollabResumeInput,
    CollabStage,
    CollaborationDetails,
    CollaborationState,
    PurposeKind,
    REQUIRED_COLLAB_FIELDS,
)
from .proposal import build_collab_proposal, purpose_label
from .runner import run_collaboration

__all__ = [
    "COLLAB_STATE_SCHEMA_VERSION",
    "CollabField",
    "CollabResumeInput",
    "CollabStage",
    "CollaborationDetails",
    "CollaborationState",
    "PurposeKind",
    "REQUIRED_COLLAB_FIELDS",
    "build_collab_proposal",
    "extract_collaboration_details",
    "merge_answer",
    "purpose_label",
    "questions_for_missing_fields",
    "run_collaboration",
]
