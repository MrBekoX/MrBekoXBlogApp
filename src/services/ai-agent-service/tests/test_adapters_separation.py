"""Test double ↔ gerçek sağlayıcı ayrım testleri.

Kabul ölçütü: "Test double ile gerçek sağlayıcı arasındaki ayrım açıktır":
- test double'lar yalnız ``adapters.test_doubles`` alt paketinde yaşar;
- her biri ``is_test_double = True`` taşır;
- port Protocol'lerini yapısal olarak karşılar;
- üretim çözümleyicisi işaretli nesneyi test dışı ortamda reddeder
  (bkz. ``test_provider_config.py``).
"""

from __future__ import annotations

import agent_core.adapters as adapters_package
import agent_core.adapters.test_doubles as test_doubles
from agent_core.ports import (
    BudgetStore,
    CancellationToken,
    CheckpointStore,
    ContentRepository,
    EmbeddingProvider,
    ModelProvider,
    ProfileRepository,
    ProgressSink,
    ProjectRepository,
    SourceReader,
    WebSearchProvider,
)
from agent_core.adapters.test_doubles import (
    FakeBudgetStore,
    FakeCheckpointStore,
    FakeContentRepository,
    FakeEmbeddingProvider,
    FakeModelProvider,
    FakeProfileRepository,
    FakeProjectRepository,
    FakeSourceReader,
    FakeWebSearchProvider,
    PreCancelledToken,
    RecordingProgressSink,
)

PORT_AND_DOUBLE_CASES = [
    (FakeModelProvider(), ModelProvider),
    (FakeEmbeddingProvider(), EmbeddingProvider),
    (FakeWebSearchProvider(), WebSearchProvider),
    (FakeSourceReader(), SourceReader),
    (FakeContentRepository(), ContentRepository),
    (FakeProfileRepository(), ProfileRepository),
    (FakeProjectRepository(), ProjectRepository),
    (FakeCheckpointStore(), CheckpointStore),
    (FakeBudgetStore(), BudgetStore),
    (PreCancelledToken(), CancellationToken),
    (RecordingProgressSink(), ProgressSink),
]


def test_every_exported_test_double_is_marked() -> None:
    for name in test_doubles.__all__:
        obj = getattr(test_doubles, name)
        assert isinstance(obj, type), f"{name} bir sınıf olmalı"
        assert getattr(obj, "is_test_double", False) is True, f"{name} is_test_double işareti taşımıyor"


def test_all_eleven_ports_have_a_test_double() -> None:
    assert len(PORT_AND_DOUBLE_CASES) == 11


def test_test_doubles_satisfy_their_port_protocols() -> None:
    for double, port in PORT_AND_DOUBLE_CASES:
        assert isinstance(double, port), f"{type(double).__name__} {port.__name__} portunu karşılamıyor"


def test_adapters_root_namespace_contains_no_test_doubles() -> None:
    for name in adapters_package.__all__:
        obj = getattr(adapters_package, name)
        if isinstance(obj, type):
            assert getattr(obj, "is_test_double", False) is not True, (
                f"{name} test double işaretli ama üretim kökünde; yalnız test_doubles altında olabilir"
            )
