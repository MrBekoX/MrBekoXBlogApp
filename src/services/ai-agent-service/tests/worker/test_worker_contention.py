"""B6 eşzamanlılık testleri: iki worker yarışı, lease kaybı, ilerlemeye bağlı yenileme.

Kabul ölçütleri (plan B6:400): "lease kaybı" ve "iki worker yarışı"
senaryoları GERÇEK broker+DB'de doğrulanır. Eski worker canlıyken lease'i
kaybederse (iş yeniden sahiplenilirse) sonucu EZILEMEZ ve worker terminal
YAZMADAN yürütmesini bırakır.

Deterministiklik notu: "B işi devraldı" durumu, claim'in yaptığı geçişi aynı
kolonlarda atomik uygulayan SQL ile simüle edilir (fencing_token+1,
execution_attempt+1, lease_owner='w-b', lease ileri); böylece eski worker'ın
yenileme döngüsünün zamanlaması test sonucunu etkileyemez.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest

from agent_core.models import DomainProgress, ProgressKind
from messaging.worker import (
    WorkerSettings,
    _LeaseWatch,
    _WorkerCancel,
    _WorkerProgressSink,
)

from worker.helpers import (
    GateModel,
    expire_lease,
    job_row,
    make_worker,
    run,
    seed_execute_job,
    spawn,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("clean_environment")


async def _steal_job(pool, run_id: str, new_owner: str = "w-b") -> None:
    """Claim'in recovery geçişini atomik simüle eder: fencing artar, sahip değişir."""

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE agent.jobs SET fencing_token = fencing_token + 1, "
            "execution_attempt = execution_attempt + 1, lease_owner = $2, "
            "lease_until = now() + interval '60 seconds' WHERE run_id = $1",
            uuid.UUID(run_id),
            new_owner,
        )


async def _await_task(task: asyncio.Task) -> object:
    return await task


async def _sleep_seconds(seconds: float) -> None:
    await asyncio.sleep(seconds)


# ---------------------------------------------------------------------------
# İki worker yarışı: claim tekilliği — GERÇEK eşzamanlılıkla (SKIP LOCKED)
#
# Aşağıdaki iki test claim_next_job çağrılarını asyncio.gather ile AYNI anda
# başlatır: her çağrı kendi havuz bağlantısında kendi transaction'ını açar
# (db_pool max_size=6) ve FOR UPDATE SKIP LOCKED gerçek çekişim altında
# egzersiz edilir. Sıralı çağrıların doğruladığı ayrı şeydir: canlı lease'li
# işin WHERE filtresiyle seçilmemesi.
# ---------------------------------------------------------------------------


def test_concurrent_claims_race_single_job_exactly_one_wins(store, db_pool):
    run_id, *_ = run(seed_execute_job(db_pool))

    async def _race() -> list:
        return await asyncio.gather(
            store.claim_next_job("w-a", lease_seconds=60),
            store.claim_next_job("w-b", lease_seconds=60),
        )

    first, second = run(_race())
    winners = [c for c in (first, second) if c is not None]
    assert len(winners) == 1, (
        f"aynı iş için eşzamanlı iki claim'den yalnız BİRİ kazanmalı; kazanan sayısı: {len(winners)}"
    )
    assert winners[0].run_id == run_id
    assert winners[0].fencing_token >= 1

    loser = second if winners[0] is first else first
    assert loser is None, "kaybeden claim işi ALMAMALI (SKIP LOCKED satırı atladı)"


def test_concurrent_claims_on_multiple_jobs_get_distinct_jobs(store, db_pool):
    run_ids = []
    for _ in range(4):
        run_id, *_ = run(seed_execute_job(db_pool))
        run_ids.append(run_id)

    async def _race() -> list:
        return await asyncio.gather(
            *(store.claim_next_job(f"w-{i}", lease_seconds=60) for i in range(4))
        )

    claimed = [c for c in run(_race()) if c is not None]
    assert len(claimed) == 4, f"eşzamanlı 4 claim 4 iş almalı; alan: {len(claimed)}"
    assert {c.run_id for c in claimed} == set(run_ids), (
        "eşzamanlı claim'ler AYRI işleri almalı; aynı işi iki alan olmamalı (SKIP LOCKED)"
    )
    assert len({c.fencing_token for c in claimed}) == 4, "fencing token'lar benzersiz tahsis edilmeli"


def test_sequential_second_claim_gets_nothing_while_lease_active(store, db_pool):
    """Sıralı iddialar WHERE filtresini doğrular (SKIP LOCKED kanıtı gather'lı testlerdedir)."""
    run_ids = []
    for _ in range(3):
        run_id, *_ = run(seed_execute_job(db_pool))
        run_ids.append(run_id)

    claim_a = run(store.claim_next_job("w-a", lease_seconds=60))
    claim_b = run(store.claim_next_job("w-b", lease_seconds=60))
    assert claim_a is not None and claim_b is not None
    assert claim_a.run_id != claim_b.run_id, "iki worker aynı işi aynı anda alamaz"
    assert claim_a.fencing_token != claim_b.fencing_token

    remaining = (set(run_ids) - {claim_a.run_id, claim_b.run_id}).pop()
    claim_c = run(store.claim_next_job("w-c", lease_seconds=60))
    assert claim_c is not None and claim_c.run_id == remaining

    # Kuyruk boşalınca claim idle döner
    assert run(store.claim_next_job("w-a", lease_seconds=60)) is None


# ---------------------------------------------------------------------------
# Canlı eski worker'ın sonucu ezemez (fencing) — worker seviyesinde
# ---------------------------------------------------------------------------


def test_live_worker_with_lost_lease_cannot_overwrite_new_owner(
    store, db_pool, publisher, checkpoint_dir
):
    run_id, *_ = run(seed_execute_job(db_pool))

    # Worker A yürütmede: model kapıyı bekler (canlı ama yavaş).
    gate_a = GateModel(response_text="eski denemenin cevabı")
    worker_a = make_worker(
        store, db_pool, worker_id="w-a", model=gate_a,
        lease_seconds=30.0, renew_interval_seconds=30.0,  # ilk yenileme test boyu ateşlenmesin
        checkpoint_dir=checkpoint_dir, publisher=publisher,
    )
    task_a = spawn(worker_a.run_once())
    run(wait_until(gate_a.entered.is_set))

    # A canlıyken işi B yeniden sahiplenir (fencing 2).
    run(_steal_job(db_pool, run_id, "w-b"))

    # A'nın yürütmesi tamamlanır: terminal yazımı fencing guard'ında REDDEDİLİR.
    gate_a.release.set()
    result_a = run(_await_task(task_a))
    assert result_a.action == "aborted_lease_lost", f"çıkan: {result_a.action} {result_a.detail}"

    row = run(job_row(db_pool, run_id))
    assert row["status"] == "running", "eski deneme terminal yazmadı"
    assert row["lease_owner"] == "w-b"
    assert row["result_json"] is None, "eski denemenin sonucu yazılamadı"

    # Yeni sahiplik zinciri: B'nin lease'i bitince iş kurtarılır ve tamamlanır.
    run(expire_lease(db_pool, run_id))
    worker_b = make_worker(
        store, db_pool, worker_id="w-b2", checkpoint_dir=checkpoint_dir, publisher=publisher
    )
    result_b = run(worker_b.run_once())
    assert result_b.action == "completed"
    assert result_b.recovered is True
    row = run(job_row(db_pool, run_id))
    document = json.loads(row["result_json"])
    assert document["outcome"] == "completed"
    assert document["execution_attempt"] == 3


# ---------------------------------------------------------------------------
# Lease kaybı yürütmenin ORTASINDA: yenileme reddi iptal sinyali üretir
# ---------------------------------------------------------------------------


def test_lease_renewal_refusal_aborts_execution_midflight(store, db_pool, publisher, checkpoint_dir):
    run_id, *_ = run(seed_execute_job(db_pool))

    gate_a = GateModel(response_text="kaybeden yürütme")
    worker_a = make_worker(
        store, db_pool, worker_id="w-a", model=gate_a,
        lease_seconds=5.0, renew_interval_seconds=0.2,
        checkpoint_dir=checkpoint_dir, publisher=publisher,
    )
    task_a = spawn(worker_a.run_once())
    run(wait_until(gate_a.entered.is_set))

    # İş atomik olarak B'ye geçer (fencing artar): A'nın SONRAKİ yenilemesi
    # (≤0.2s) fencing eşleşmezliğiyle reddedilir → cancel token ateşlenir.
    run(_steal_job(db_pool, run_id, "w-b"))

    # İptal sinyalinin üretileceği yenileme penceresinin geçmesi beklenir
    # (deterministiklik: kapı, token ateşlendikten SONRA açılır).
    run(_sleep_seconds(0.5))

    # A uyanır: model iptal sinyalini görür, yürütme CANCELLED ile kesilir,
    # worker terminal YAZMADAN bırakır.
    gate_a.release.set()
    result_a = run(_await_task(task_a))
    assert result_a.action == "aborted_lease_lost", f"çıkan: {result_a.action} {result_a.detail}"
    assert gate_a.cancelled_while_waiting is True, "iptal sinyali model çağrısına taşınmalı"

    row = run(job_row(db_pool, run_id))
    assert row["status"] == "running"
    assert row["result_json"] is None, "lease kaybeden worker terminal yazamaz"


# ---------------------------------------------------------------------------
# Lease yenilemesi canlı yürütmeyi korur (graph yürütmesi boyunca)
# ---------------------------------------------------------------------------


def test_renew_loop_keeps_live_execution_recoverable_only_after_release(
    store, db_pool, publisher, checkpoint_dir
):
    """Canlı yürütmede lease döngüsü lease'i öne çeker; bırakılınca iş kurtarılabilir.

    Zamanlama gözlem gütmelidir (yük altında sabit uyku kırılganlığı yoktur):
    önce en az bir yenilemenin GERÇEKLEŞTİĞİ beklenir (lease_until claim'deki
    değerden ilerledi), sonraki iddialar o gözleme dayanır.
    """
    run_id, *_ = run(seed_execute_job(db_pool))

    gate = GateModel(response_text="uzun yürütme")
    worker = make_worker(
        store, db_pool, worker_id="w-a", model=gate,
        lease_seconds=2.0, renew_interval_seconds=0.3,
        checkpoint_dir=checkpoint_dir, publisher=publisher,
    )
    task = spawn(worker.run_once())
    run(wait_until(gate.entered.is_set))

    async def _lease_until() -> object:
        async with db_pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT lease_until FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id)
            )

    lease_at_claim = run(_lease_until())

    async def _renewal_observed() -> bool:
        current = await _lease_until()
        return current is not None and current > lease_at_claim

    # En az bir yenileme gerçekleşene kadar beklenir (yenileme aralığı 0.3s;
    # yük altında bile 20s gözlem penceresi yeterlidir).
    run(wait_until(_renewal_observed))

    row = run(job_row(db_pool, run_id))
    assert row["status"] == "running"
    assert row["lease_until"] is not None
    lease_alive = run(_lease_in_future(db_pool, run_id))
    assert lease_alive is True, "canlı yürütmede yenileme lease'i korumalı"
    assert run(store.claim_next_job("w-x", lease_seconds=60)) is None, "lease canlıyken devralınamaz"

    gate.release.set()
    result = run(_await_task(task))
    assert result.action == "completed"
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "completed"
    assert row["lease_until"] is None, "terminal yazımı lease'i temizledi"


async def _lease_in_future(pool, run_id: str) -> bool:
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT lease_until > now() FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id)
        )
    return bool(value)


# ---------------------------------------------------------------------------
# Lease yenilemesi graph İLERLEMESİNE bağlıdır — arka plan döngüsünden AYRI kanıt
# ---------------------------------------------------------------------------


def test_progress_event_itself_triggers_lease_renewal(store, db_pool):
    """İlerleme olayının TETİKLEDİĞİ heartbeat arka plan döngüsünden bağımsız kanıtlanır.

    Yöntem: ``_LeaseWatch``'ın arka plan döngü task'ı BASLANGICTA durdurulur
    (görev iptali — bundan sonra döngü yenileme üretemez); yalnız bir
    DomainProgress olayı sink üzerinden yayınlanır. ``lease_until`` yine de
    ilerliyorsa yenilemeyi progress→heartbeat yolu tetiklemiştir (plan B6:387
    "Lease yenilemesini graph ilerlemesine bağla"). Özel sınıflara dokunma,
    döngüyü izole etmenin tek yolu olarak bilinçli birim sondasıdır.
    """
    run_id, conversation_id = run(seed_execute_job(db_pool))[:2]
    claimed = run(store.claim_next_job("w-a", lease_seconds=30))
    assert claimed is not None

    async def _probe() -> tuple[object, object, bool]:
        watch = _LeaseWatch(
            store,
            run_id,
            claimed.fencing_token,
            WorkerSettings(worker_id="w-probe", lease_seconds=30.0, renew_interval_seconds=30.0),
        )
        cancel = _WorkerCancel()
        watch.start(cancel)
        await asyncio.sleep(0)  # döngü task'ı doğsun
        await watch.stop()  # arka plan döngüsü İPTAL: bundan sonra yenileyemez

        async def _lease_until() -> object:
            async with db_pool.acquire() as conn:
                return await conn.fetchval(
                    "SELECT lease_until FROM agent.jobs WHERE run_id = $1", uuid.UUID(run_id)
                )

        before = await _lease_until()
        sink = _WorkerProgressSink(
            run_id=run_id,
            conversation_id=conversation_id,
            correlation_id="corr-probe",
            causation_id="cause-probe",
            execution_attempt=1,
            publisher=None,  # olay yayınlanmaz; yalnız heartbeat gözlenir
            watch=watch,
        )
        await sink.publish(
            DomainProgress(
                run_id=run_id,
                kind=ProgressKind.GENERATION_STARTED,
                message="ilerleme sinyali: heartbeat tetikleyicisi",
                occurred_at=datetime.now(timezone.utc),
            )
        )
        after = await _lease_until()
        return before, after, watch.lost

    before, after, lost = run(_probe())
    assert lost is False, "progress heartbeat'i yenileme başarısız saymamalı (iş hâlâ bizim)"
    assert before is not None and after is not None
    assert after > before, "döngü kapalıyken yalnız progress olayı lease'i yenilemiş olmalı"
