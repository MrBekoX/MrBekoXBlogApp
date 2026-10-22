"""Test double'lar — SADECE test ortamında kullanılır.

Kabul ölçütü: "Test double ile gerçek sağlayıcı arasındaki ayrım açıktır".
Bu paketteki her sınıf ``is_test_double = True`` sınıf işareti taşır; üretim
yapılandırma çözümleyicisi (``agent_core.adapters.config``) işaretli nesneyi
``environment != "test"`` iken reddeder. Test double sonucu gerçek model /
sağlayıcı / broker başarısı olarak raporlanmaz.

Kod incelemesi kuralı: bu paketten hiçbir isim üretim koduna import edilemez.
"""

from .fake_embedding import FakeEmbeddingProvider
from .fake_model import ExplodingModelProvider, FakeModelProvider
from .fake_repositories import (
    FakeContentRepository,
    FakeProfileKnowledgeRepository,
    FakeProfileRepository,
    FakeProjectRepository,
)
from .fake_signals import PreCancelledToken, RecordingProgressSink, StubCancellationToken
from .fake_state import FakeBudgetStore, FakeCheckpointStore
from .fake_web import FakeSourceReader, FakeWebSearchProvider

__all__ = [
    "ExplodingModelProvider",
    "FakeBudgetStore",
    "FakeCheckpointStore",
    "FakeContentRepository",
    "FakeEmbeddingProvider",
    "FakeModelProvider",
    "FakeProfileKnowledgeRepository",
    "FakeProfileRepository",
    "FakeProjectRepository",
    "FakeSourceReader",
    "FakeWebSearchProvider",
    "PreCancelledToken",
    "RecordingProgressSink",
    "StubCancellationToken",
]
