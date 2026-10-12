"""Kaynak toplama sonrası kesinti → checkpoint'ten devam senaryosu (A8 kabul).

Plan A8 kabul ölçütü: "kaynak toplama sonrasında kesinti → checkpoint'ten
devam". Bu test gerçek langgraph kurulumuyla kesinti üretir ve şunları kanıtlar:

1. Kesinti (iptal) sonrası graph runner, TOPLANMIŞ kaynak sonuçlarını
   (bulgu/kanıt/kullanım olayı) ``CheckpointStore`` portu üzerinden KALICI
   depoya yazar (``graph/runner.py`` terminal yollarının hepsinde save).
2. YENİ depo örneği (süreç restart benzetimi) aynı state'i okur.
3. ``partition_for_resume`` devam malzemesini ayırır: tamamlanmış bulgular
   yeniden kullanılır; rapor adımı YENİ model çağrısı gerektiren adım olarak
   önceki sonuçlardan AYRILIR.
4. Kullanım olayları checkpoint sınırının ötesinde birleşse bile çift
   sayılmaz (eylem kimliği idempotentliği).

Sınır: checkpoint saklamak durmuş süreci YENİDEN BAŞLATMAZ (plan A8); devam
yürütmeyi dış çalışma adaptörü (B6 worker) başlatır. Bu test devam MALZEMESİNİN
ve sözleşmelerinin doğruluğunu kanıtlar; worker bağlantısı bu fazın kapsamı
değildir.

``tests/state/effects.py`` yardımcı modülü TÜKETİLİR, değiştirilmez (L005:
``effects`` conftest adı taşımaz; sys.path eki yalnız test kökünü gösterir).
"""

from __future__ import annotations

import sys
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from agent_core.checkpoint import FileCheckpointStore, partition_for_resume
from agent_core.models import RunStatus
from agent_core.state import (
    InMemoryArtifactStore,
    deserialize_state,
    merge_usage_events,
    usage_record_from_events,
)

_STATE_HELPERS = Path(__file__).resolve().parents[1] / "state"
if str(_STATE_HELPERS) not in sys.path:
    sys.path.insert(0, str(_STATE_HELPERS))

from effects import ScriptedEffects, make_route, make_run_context, run_graph  # noqa: E402


class CancelBeforeReport(ScriptedEffects):
    """Kaynak toplama (alt görevler) TAMAMLANDIKTAN sonra rapor öncesinde keser."""

    def __init__(self, *, token, **kwargs) -> None:
        super().__init__(**kwargs)
        self._token = token

    async def report(self, question, findings, tasks):  # noqa: ANN001
        self._token.cancel("rapor öncesi kesinti: kaynak toplama tamamlandı")
        return await super().report(question, findings, tasks)


def test_interrupted_after_collection_persists_reusable_results(tmp_path) -> None:
    """Kesinti → kalıcı checkpoint → yeniden açma → devam ayrımı ve idempotent kullanım."""
    from effects import MutableToken

    store = FileCheckpointStore(tmp_path)
    token = MutableToken()
    effects = CancelBeforeReport(token=token, sub_questions=("S1", "S2"))
    context = make_run_context()

    result = run_graph(
        context,
        make_route(context),
        effects,
        artifacts=InMemoryArtifactStore(),
        checkpoint=store,
        cancel=token,
        langgraph_checkpointer=MemorySaver(),
    )

    assert result.outcome.status is RunStatus.CANCELLED
    assert len(effects.completed_calls) > 0  # toplama çağrıları gerçekleşti

    # Süreç restart benzetimi: YENİ depo örneği checkpoint'i okur.
    reopened = FileCheckpointStore(tmp_path)
    import asyncio

    checkpoint_id, payload = asyncio.run(reopened.load_latest(context.run_id))
    assert checkpoint_id == "a2-state"

    restored = deserialize_state(payload, expected_run_id=context.run_id)
    # Kesinti TOPLAMA SONRASINDA olduğu için tamamlanmış kaynak sonuçları checkpoint'te.
    assert len(restored["findings"]) == 2
    assert len(restored["evidence"]) == 2
    assert restored["outcome"] is not None
    assert restored["outcome"].status is RunStatus.CANCELLED

    # Devam ayrımı: tamamlananlar yeniden kullanılır; rapor yeni model adımıdır.
    partition = partition_for_resume(restored)
    assert len(partition.reusable_finding_ids) == 2
    assert partition.stale_finding_ids == []
    assert partition.model_steps == ["finalize"]

    # Kullanım kayıtları resume sınırında birleşse bile çift sayılmaz.
    assert "final:report" not in effects.started_calls  # rapor çağrısı başlamadı
    merged = merge_usage_events(
        [], list(restored["usage_events"]) + list(restored["usage_events"])
    )
    usage = usage_record_from_events(context.run_id, merged)
    # 2 alt görev cevabı model çağrısıdır; arama/okuma ayrı türlerdedir.
    assert usage.model_calls == 2
    assert usage.web_search_calls == 2
