"""Checkpoint katmanı (plan A8).

Sorumluluk ayrımı [LG-PERSISTENCE#C1]:

- ``store.FileCheckpointStore``: ``CheckpointStore`` portunun dev-grade
  KALICI gerçekleştirimi (çalışma dizini altında atomik dosya yazımı);
  payload opak bayttır.
- ``models``: sürümlü checkpoint zarfı (``CHECKPOINT_SCHEMA_VERSION``),
  kararlı yürütme kimliği (``execution_id`` — dış adaptör atar/doğrular),
  resume kapsam değerlendirmesi (``ResumeScope``/``ResumeEvaluation``) ve
  yeniden kullanım ayrımı (``ResumePartition``).
- ``resume``: zarflı yazım/okuma, uyumsuz checkpoint'in anlaşılır reddi,
  revizyon kapsamı ve state'in "yeniden kullanılır / araç çağrısı gerekir /
  model çağrısı gerekir" ayrımı.

Eşzamanlılık sözleşmesi: run başına tek yazar; eşzamanlı yazım reddedilir
(``store`` modül docstring'i). Checkpoint saklamak durmuş süreci yeniden
başlatmaz; devamı dış çalışma adaptörü uygun checkpoint'le çağırarak yapar
(plan A8).
"""

from __future__ import annotations

from .models import (
    CHECKPOINT_SCHEMA_VERSION,
    EXECUTION_ID_PATTERN,
    CheckpointEnvelope,
    CheckpointKind,
    ExecutionId,
    ResumeEvaluation,
    ResumePartition,
    ResumeScope,
    new_execution_id,
    validate_execution_id,
)
from .resume import evaluate_resume, load_resume_payload, partition_for_resume, save_checkpoint
from .store import DEFAULT_CHECKPOINT_DIR, FileCheckpointStore

__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "DEFAULT_CHECKPOINT_DIR",
    "EXECUTION_ID_PATTERN",
    "CheckpointEnvelope",
    "CheckpointKind",
    "ExecutionId",
    "FileCheckpointStore",
    "ResumeEvaluation",
    "ResumePartition",
    "ResumeScope",
    "evaluate_resume",
    "load_resume_payload",
    "new_execution_id",
    "partition_for_resume",
    "save_checkpoint",
    "validate_execution_id",
]
