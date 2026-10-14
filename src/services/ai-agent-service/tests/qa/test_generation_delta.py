"""Streaming sözleşmesi: node'ların ``GENERATION_DELTA`` yayını (qa + analysis).

``make_generate`` artık ``stream_complete`` çağırır; scripted parçalar
``on_delta`` üzerinden ``GENERATION_DELTA`` progress'i olarak akar. Sink
arızası üretimi kesmez (port sözleşmesi); terminal yanıt akıştan bağımsız
kalır (qa/analysis'te kontrol aşaması taslağı işler).
"""

from __future__ import annotations

from helpers import (
    build_records,
    make_qa_context,
    make_qa_route,
    make_qa_snapshot,
    make_retriever,
    run,
)

from agent_core.adapters.test_doubles import FakeModelProvider, RecordingProgressSink
from agent_core.analysis import run_article_analysis
from agent_core.models import AgentMode, ProgressKind, RunStatus
from agent_core.qa import run_article_qa

FULL_ANSWER = "Makale kuyruk sınırını yapılandırmayla ayarlamayı anlatır."


def deltas_of(sink: RecordingProgressSink) -> list[str]:
    return [event.message for event in sink.events if event.kind is ProgressKind.GENERATION_DELTA]


def test_qa_generate_streams_scripted_deltas() -> None:
    sink = RecordingProgressSink()
    model = FakeModelProvider(FULL_ANSWER, stream_delta_chunks=["Makale ", "kuyruk ", "sınırını"])
    context = make_qa_context(make_qa_snapshot(), question="Kuyruk sınırı nasıl ayarlanır?")
    route = make_qa_route(run_id=context.run_id, selected_mode=AgentMode.FAST)

    result = run(
        run_article_qa(
            context,
            route,
            model=model,
            retriever=make_retriever(),
            config=None,
            progress=sink,
        )
    )

    # Parçalar SIRASIYLA akar; tek model çağrısıdır (stream_complete, tam yanıt
    # complete ile aynı kaynaktan: call_count 1).
    assert deltas_of(sink) == ["Makale", "kuyruk", "sınırını"]
    assert model.stream_call_count == 1
    assert model.call_count == 1
    # Terminal yanıt hâlâ tam metinden kurulur (akış yanıtı değiştirmez).
    assert result.outcome.status is RunStatus.COMPLETED
    assert result.outcome.answer is not None
    assert "kuyruk" in result.outcome.answer


def test_qa_delta_sink_failure_does_not_break_generation() -> None:
    from agent_core.errors import AgentErrorCode, PortError

    sink = RecordingProgressSink(
        fail_with=PortError(AgentErrorCode.PROVIDER_ERROR, "kanal kapalı", port="ProgressSink")
    )
    model = FakeModelProvider(FULL_ANSWER, stream_delta_chunks=["parça-1", "parça-2"])
    context = make_qa_context(make_qa_snapshot(), question="Kuyruk sınırı nasıl ayarlanır?")
    route = make_qa_route(run_id=context.run_id, selected_mode=AgentMode.FAST)

    result = run(
        run_article_qa(
            context,
            route,
            model=model,
            retriever=make_retriever(),
            progress=sink,
        )
    )
    assert result.outcome.status is RunStatus.COMPLETED  # sink arızası akışı kesmez


def test_analysis_generate_streams_scripted_deltas() -> None:
    sink = RecordingProgressSink()
    model = FakeModelProvider(FULL_ANSWER, stream_delta_chunks=["Makale", "kuyruk", "sınırını"])
    context = make_qa_context(
        make_qa_snapshot(),
        question="Kuyruk sınırı nasıl ayarlanır ve QueueFull hatası nasıl yönetilir?",
        mode_preference="analysis",
    )
    snapshot = make_qa_snapshot()
    retriever = make_retriever()

    result = run(
        run_article_analysis(
            context,
            make_qa_route(run_id=context.run_id, selected_mode=AgentMode.ANALYSIS),
            model=model,
            retriever=retriever,
            progress=sink,
        )
    )

    assert deltas_of(sink) == ["Makale", "kuyruk", "sınırını"]
    assert model.stream_call_count == 1
    assert result.outcome.status is RunStatus.COMPLETED
    assert result.outcome.selected_mode is AgentMode.ANALYSIS
    # Analysis kayıt kanıtı üretir: bölüm kayıtları retriever'dan gelir.
    assert build_records(snapshot)  # yardımcı canlılığı (kayıt üretimi sözleşmesi)


def test_qa_stream_chunks_over_carrier_limit_are_split() -> None:
    """Üst sınırı aşan tek chunk node yardımcısı tarafından bölünür (1500)."""

    from agent_core.models import MAX_GENERATION_DELTA_CHARS

    big_first = "a" * 1600
    sink = RecordingProgressSink()
    model = FakeModelProvider(f"{big_first}son", stream_delta_chunks=[big_first, "son"])
    context = make_qa_context(make_qa_snapshot(), question="Kuyruk sınırı nasıl ayarlanır?")
    route = make_qa_route(run_id=context.run_id, selected_mode=AgentMode.FAST)

    run(
        run_article_qa(
            context,
            route,
            model=model,
            retriever=make_retriever(),
            progress=sink,
        )
    )

    messages = deltas_of(sink)
    assert messages[0] == "a" * MAX_GENERATION_DELTA_CHARS
    assert messages[1] == "a" * (1600 - MAX_GENERATION_DELTA_CHARS)
    assert messages[2] == "son"
    assert all(len(m) <= MAX_GENERATION_DELTA_CHARS for m in messages)
