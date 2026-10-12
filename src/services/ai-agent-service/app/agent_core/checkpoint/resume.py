"""Checkpoint okuma, sürüm ve kapsam sözleşmeleri (A8 resume).

Bu modül resume'un KARAR katmanıdır; depolama ``store.py``'de, zarf
``models.py``'dedir. Sorumlulukları:

- **Zarflı yazım:** ``save_checkpoint`` payload'ı sürümlü zarfla, run ve
  kararlı yürütme kimliği bağlamasıyla yazar.
- **Uyumluluk:** ``load_resume_payload`` zarf şema sürümünü denetler; bilinmeyen
 /gelecek sürüm ANLAŞILIR ``validation_error`` ile reddedilir (plan A8:
  "uyumsuz eski checkpoint için anlaşılır sonuç"). Zarfsız (A1 dönemi ham
  ``PreparedRun`` JSON) payload'lar geriye dönük uyumluluk için aynen döner.
- **Kapsam:** ``evaluate_resume`` checkpoint bağlamı ile güncel bağlamın
  içerik revizyonunu karşılaştırır ve devamın hangi kapsamda olabileceğini
  söyler (``FULL_REUSE`` / ``EVIDENCE_STALE`` / ``NOT_RESUMABLE``) — revizyon
  anlamı D008/L004: backend'in atadığı monoton yayımlanmış içerik anı.
- **Ayrım:** ``partition_for_resume`` state'te tamamlanmış kaynak/araç
  sonuçlarını YENİDEN KULLANILACAKLARDAN, araç çağrısı gerektiren alt
  görevlerden ve YENİ model çağrısı gerektiren adımlardan ayırır (plan A8).
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..errors import AgentErrorCode, PortError
from ..models import ExecutionContext, Identifier
from ..ports import CheckpointStore
from ..state.state import STATE_SCHEMA_VERSION, AgentState
from .models import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointEnvelope,
    CheckpointKind,
    ResumeEvaluation,
    ResumePartition,
    ResumeScope,
    validate_execution_id,
)

__all__ = [
    "load_resume_payload",
    "partition_for_resume",
    "evaluate_resume",
    "save_checkpoint",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def save_checkpoint(
    store: CheckpointStore,
    *,
    run_id: str,
    execution_id: str,
    kind: CheckpointKind,
    payload: bytes,
    checkpoint_id: str | None = None,
    state_schema_version: int | None = None,
    context: ExecutionContext | None = None,
) -> CheckpointEnvelope:
    """Payload'ı sürümlü zarfla, kararlı yürütme kimliğine bağlayarak yazar.

    ``kind=state`` için ``state_schema_version`` zorunludur ve çekirdeğin
    desteklediği ``STATE_SCHEMA_VERSION`` olmak zorundadır; farklı sürüm
    yazılmaz (uyumsuz payload'ın doğması yazım anında engellenir).

    Returns:
        Yazılan zarf; ``checkpoint_id`` çağırana döner (resume bununla okur).
    """
    from .models import new_execution_id  # yerel import: models döngüsüz

    resolved_execution = validate_execution_id(execution_id) if execution_id else new_execution_id(run_id)
    if kind is CheckpointKind.STATE:
        if state_schema_version is None:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "state checkpoint'i state_schema_version olmadan yazılamaz",
                port="save_checkpoint",
            )
        if state_schema_version != STATE_SCHEMA_VERSION:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"state şema sürümü desteklenmiyor: istenen={state_schema_version}, "
                f"desteklenen={STATE_SCHEMA_VERSION}; uyumsuz payload yazılmaz",
                port="save_checkpoint",
            )
    resolved_id = checkpoint_id or f"{kind.value}:{resolved_execution}"
    envelope = CheckpointEnvelope.wrap(
        checkpoint_id=resolved_id,
        run_id=run_id,
        execution_id=resolved_execution,
        kind=kind,
        payload=payload,
        saved_at=_now(),
        state_schema_version=state_schema_version,
        context=context,
    )
    await store.save(run_id, resolved_id, envelope.model_dump_json().encode("utf-8"))
    return envelope


async def load_resume_payload(
    store: CheckpointStore,
    run_id: str,
    checkpoint_id: str | None = None,
    *,
    execution_id: str | None = None,
) -> tuple[CheckpointEnvelope | None, bytes]:
    """Checkpoint'i okur ve zarf sözleşmelerini denetler.

    - ``checkpoint_id`` verilmezse run'ın en son yazılanı okunur.
    - Zarf çözümlenirse: zarf şema sürümü, run bağı, yürütme kimliği bağlaması
      (istenen verilmişse) ve ``kind=state`` için state şema sürümü denetlenir.
    - Zarf çözümlenemezse payload A1 dönemi ham JSON kabul edilir ve
      ``(None, ham_baytlar)`` döner — geriye dönük uyumluluk.

    Raises:
        PortError: ``not_found`` — checkpoint yok; ``validation_error`` — zarf
            sürümü uyumsuz, payload başka run'a/yürütülmeye ait veya state şema
            sürümü desteklenmiyor.
    """
    if checkpoint_id is not None:
        raw = await store.load(run_id, checkpoint_id)
    else:
        _, raw = await store.load_latest(run_id)

    try:
        envelope = CheckpointEnvelope.model_validate_json(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, raw

    if envelope.schema_version != CHECKPOINT_SCHEMA_VERSION:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            f"checkpoint zarf şeması uyumsuz: payload=v{envelope.schema_version}, "
            f"desteklenen=v{CHECKPOINT_SCHEMA_VERSION}; bu checkpoint bu çekirdek "
            "sürümüyle okunamaz (yeni sürüm çekirdek gerekir)",
            port="resume",
        )
    if envelope.run_id != run_id:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            f"checkpoint payload'ı istenen run'a ait değil: zarf={envelope.run_id}, istenen={run_id}",
            port="resume",
        )
    if execution_id is not None and envelope.execution_id != execution_id:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            "yürütme kimliği bağlaması uyuşmuyor: "
            f"checkpoint={envelope.execution_id}, istenen={execution_id}; "
            "checkpoint başka bir yürütme zincirine bağlı",
            port="resume",
        )
    if (
        envelope.kind is CheckpointKind.STATE
        and envelope.state_schema_version is not None
        and envelope.state_schema_version != STATE_SCHEMA_VERSION
    ):
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            f"state şema sürümü uyumsuz: payload={envelope.state_schema_version}, "
            f"desteklenen={STATE_SCHEMA_VERSION}; eski state şemasından devam edilmez",
            port="resume",
        )
    return envelope, envelope.payload_bytes()


def evaluate_resume(
    *,
    checkpoint_context: ExecutionContext,
    current_context: ExecutionContext,
) -> ResumeEvaluation:
    """İçerik revizyonuna göre resume kapsamını değerlendirir (plan A8).

    Karşılaştırma checkpoint'teki bağlam ile resume talebinin GÜNCEL bağlamı
    arasındadır: aynı makale + aynı revizyon (+ hash) → ``FULL_REUSE``;
    revizyon ilerlemişse veya hash değişmişse → ``EVIDENCE_STALE`` (karar ve
    makaleden bağımsız sonuçlar sürdürülebilir, makale kanıtı/bulgu bayat);
    içerik kaldırılmışsa, revizyon gerilemişse veya makale değişmişse →
    ``NOT_RESUMABLE``.
    """
    cp_id = checkpoint_context.article_id
    cp_rev = checkpoint_context.article_revision
    cp_hash = checkpoint_context.article_content_hash
    cur_id = current_context.article_id
    cur_rev = current_context.article_revision
    cur_hash = current_context.article_content_hash

    def _result(scope: ResumeScope, reason: str) -> ResumeEvaluation:
        return ResumeEvaluation(
            scope=scope,
            reasons=[reason],
            checkpoint_article_revision=cp_rev,
            current_article_revision=cur_rev,
        )

    if cp_id is None and cur_id is None:
        return _result(ResumeScope.FULL_REUSE, "makalesiz çalışma: içerik revizyonu bağlamı yok")
    if cp_id is not None and cur_id is None:
        return _result(
            ResumeScope.NOT_RESUMABLE,
            f"içerik kaldırılmış veya bağlam artık makaleye bağlı değil (checkpoint makalesi: {cp_id}); "
            "makaleye bağlı sonuçlarla devam edilemez",
        )
    if cp_id is None and cur_id is not None:
        return _result(
            ResumeScope.NOT_RESUMABLE,
            f"checkpoint makalesiz çalışmaya ait; güncel bağlam makaleye bağlı ({cur_id}): "
            "farklı çalışmanın checkpoint'iyle devam edilmez",
        )
    # İki taraf da makaleye bağlı.
    if cp_id != cur_id:  # type: ignore[redundant-expr] - daralma pydantic tipinden geliyor
        return _result(
            ResumeScope.NOT_RESUMABLE,
            f"checkpoint başka makaleye bağlı: checkpoint={cp_id}, güncel={cur_id}",
        )
    if cur_rev is None or cp_rev is None:
        return _result(
            ResumeScope.NOT_RESUMABLE,
            "makaleye bağlı çalışmada revizyon bilgisi eksik; kapsam değerlendirilemez",
        )
    if cur_rev < cp_rev:
        return _result(
            ResumeScope.NOT_RESUMABLE,
            f"revizyon gerilemesi: checkpoint=r{cp_rev}, güncel=r{cur_rev} "
            "(revizyon monotondur — D008); checkpoint'ten devam edilmez",
        )
    if cur_rev > cp_rev:
        return _result(
            ResumeScope.EVIDENCE_STALE,
            f"içerik revizyonu değişti: checkpoint=r{cp_rev}, güncel=r{cur_rev}; "
            "tamamlanmış makale kanıtları ve bulguları BAYATTIR, yeniden toplanmalı; "
            "rota kararı ve makaleden bağımsız sonuçlar sürdürülebilir",
        )
    if cp_hash is not None and cur_hash is not None and cp_hash != cur_hash:
        return _result(
            ResumeScope.EVIDENCE_STALE,
            "aynı revizyon numarasında içerik hash'i değişti; kanıt güvenilirliği yok — "
            "makale kanıtları yeniden toplanmalı",
        )
    return _result(
        ResumeScope.FULL_REUSE,
        f"aynı makale ve revizyon (r{cp_rev}): tamamlanmış kaynak/araç sonuçları yeniden kullanılabilir",
    )


def partition_for_resume(
    state: AgentState,
    evaluation: ResumeEvaluation | None = None,
) -> ResumePartition:
    """State'i resume ayrımına ayırır: yeniden kullanım / bayat / yeni çağrı.

    Kural (plan A8):
    - Tamamlanmış bulgular ve kanıtlar yeniden KULLANILIR; araç/model çağrısı
      gerektirmez.
    - ``evaluation`` ``EVIDENCE_STALE`` ise makale kaynaklı kanıtlar ve
      onlara dayanan bulgular bayat sayılır; bayat bulgunun alt sorusu
      yeniden ``pending_subtasks`` kuyruğuna döner (plan varsa indis oradan).
    - Rapor/yanıt adımı her koşulda YENİ model çağrısı gerektirir; önceki
      sonuçlardan üretilir, checkpoint'ten taşınmaz.
    """
    scope = evaluation.scope if evaluation is not None else ResumeScope.FULL_REUSE

    evidence = list(state.get("evidence") or [])
    findings = list(state.get("findings") or [])

    stale_evidence: list[Identifier] = []
    reusable_evidence: list[Identifier] = []
    for item in evidence:
        article_bound = getattr(item.source, "kind", None) == "article"
        if scope is ResumeScope.FULL_REUSE or not article_bound:
            reusable_evidence.append(item.evidence_id)
        else:
            stale_evidence.append(item.evidence_id)

    stale_evidence_set = set(stale_evidence)
    reusable_findings: list[str] = []
    stale_findings: list[str] = []
    stale_questions: list[str] = []
    for finding in findings:
        if any(eid in stale_evidence_set for eid in (finding.evidence_ids or [])):
            stale_findings.append(finding.finding_id)
            stale_questions.append(finding.sub_question)
        else:
            reusable_findings.append(finding.finding_id)
    if scope is ResumeScope.NOT_RESUMABLE:
        # Savunmacı ayrım: devam reddedilmeden ayrım istenirse hiçbir sonuç
        # yeniden kullanılabilir sayılmaz.
        stale_findings = [f.finding_id for f in findings]
        reusable_findings = []
        stale_questions = [f.sub_question for f in findings]

    stale_finding_set = set(stale_findings)
    completed = {f.sub_question for f in findings if f.finding_id not in stale_finding_set}

    pending = [dict(task) for task in (state.get("pending_subtasks") or [])]
    plan = state.get("plan")
    sub_index_by_question: dict[str, int] = {}
    if plan is not None:
        for index, question in enumerate(plan.sub_questions):
            sub_index_by_question.setdefault(question, index)
    round_number = int(state.get("research_round") or 1)
    for question in stale_questions:
        if any(task.get("sub_question") == question for task in pending):
            continue
        pending.append(
            {
                "sub_question": question,
                "sub_index": sub_index_by_question.get(question, -1),
                "round": round_number,
            }
        )

    route = state.get("route")
    deep = route is not None and getattr(route, "selected_mode", None) is not None and (
        route.selected_mode.value == "deep_research"  # type: ignore[union-attr]
    )
    model_steps = ["finalize"] if deep else ["respond"]

    return ResumePartition(
        reusable_evidence_ids=reusable_evidence,
        stale_evidence_ids=stale_evidence,
        reusable_finding_ids=reusable_findings,
        stale_finding_ids=stale_findings,
        pending_subtasks=pending,  # type: ignore[arg-type]
        model_steps=model_steps,
        state_schema_version=int(state.get("schema_version") or STATE_SCHEMA_VERSION),
    )
