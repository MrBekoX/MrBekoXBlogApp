"""B6 kapasite ayrımı testleri: araştırma yükü altında hızlı soru.

Kabul ölçütü (plan B6:400): "araştırma yükü altında hızlı soru" senaryosu —
derin araştırma AYRI yürütme kapasitesine (``queue_class='research'``)
ertelenir; hızlı worker'ın kuyruğu uzun araştırma işiyle TIKANMAZ.
Router kararı agent çekirdeğinde üretilir (backend sınıflandırmaz): worker,
rota ``deep_research`` çıkınca işi research kuyruğuna geri koyar.
"""

from __future__ import annotations

import json

import pytest

from worker.helpers import (
    GateModel,
    job_row,
    make_execution_payload,
    make_worker,
    run,
    seed_execute_job,
    spawn,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("clean_environment")


# ---------------------------------------------------------------------------
# Rota deep_research çıkınca fast worker işi research kuyruğuna erteler
# ---------------------------------------------------------------------------


def test_deep_research_route_defers_job_to_research_queue(store, db_pool, publisher):
    payload = make_execution_payload(
        "Bu konuda kapsamlı bir araştırma raporu hazırla", mode_preference="deep_research"
    )
    run_id, *_ = run(seed_execute_job(db_pool, payload=payload, queue_class="fast"))

    worker = make_worker(store, db_pool, worker_id="w-fast", publisher=publisher)
    result = run(worker.run_once())

    assert result.action == "deferred", f"çıkan: {result.action} {result.detail}"
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "accepted", "erteleme terminal değildir"
    assert row["queue_class"] == "research", "rota kararı kapasite sınıfını belirledi"
    assert row["execution_attempt"] == 0, "yürütme başlamadı; deneme sayacı resetlenir"

    # fast worker artık bu işi ALMAZ; research kapasitesi alır
    assert run(store.claim_next_job("w-fast", lease_seconds=60, queue_class=("fast",))) is None
    claimed = run(store.claim_next_job("w-res", lease_seconds=60, queue_class=("research",)))
    assert claimed is not None and claimed.run_id == run_id


def test_research_capacity_worker_executes_deferred_job(store, db_pool, publisher):
    payload = make_execution_payload(
        "Bu konuda kapsamlı bir araştırma raporu hazırla", mode_preference="deep_research"
    )
    run_id, *_ = run(seed_execute_job(db_pool, payload=payload, queue_class="research"))

    worker = make_worker(
        store, db_pool, worker_id="w-res", queue_classes=("research",), publisher=publisher
    )
    result = run(worker.run_once())
    assert result.action == "completed", f"çıkan: {result.action} {result.detail}"
    row = run(job_row(db_pool, run_id))
    assert row["status"] == "completed"
    document = json.loads(row["result_json"])
    assert document["selected_mode"] == "deep_research"


# ---------------------------------------------------------------------------
# Araştırma yükü altında hızlı soru: fast kuyruk tıkanmaz
# ---------------------------------------------------------------------------


def test_fast_question_completes_while_research_job_still_running(store, db_pool, publisher):
    # 1) Uzun araştırma işi research kapasitesinde ÇALIŞIYOR (model kapıda bekliyor).
    research_payload = make_execution_payload(
        "Bu konuda kapsamlı bir araştırma raporu hazırla", mode_preference="deep_research"
    )
    research_run, *_ = run(
        seed_execute_job(db_pool, payload=research_payload, queue_class="research")
    )
    slow_model = GateModel(response_text="araştırma sürüyor")
    worker_res = make_worker(
        store, db_pool, worker_id="w-res", model=slow_model,
        queue_classes=("research",), publisher=publisher,
    )
    task_res = spawn(worker_res.run_once())
    run(wait_until(slow_model.entered.is_set))

    # 2) Hızlı soru gelir: fast worker hemen çeker ve tamamlar — araştırma
    #    işi çalışmaya DEVAM EDERKEN.
    fast_payload = make_execution_payload("Bu makaledeki ana fikir nedir?", mode_preference="fast")
    fast_run, *_ = run(seed_execute_job(db_pool, payload=fast_payload, queue_class="fast"))
    worker_fast = make_worker(store, db_pool, worker_id="w-fast", publisher=publisher)
    fast_result = run(worker_fast.run_once())
    assert fast_result.action == "completed", f"çıkan: {fast_result.action}"

    row_fast = run(job_row(db_pool, fast_run))
    assert row_fast["status"] == "completed"
    row_res = run(job_row(db_pool, research_run))
    assert row_res["status"] == "running", "araştırma işi hızlı soruyu OLMADAN önce bitmeli değildi"
    assert not slow_model.release.is_set()

    # 3) Araştırma işi de kendi kapasitesinde tamamlanır.
    slow_model.release.set()
    research_result = run(_await_task(task_res))
    assert research_result.action == "completed"
    row_res = run(job_row(db_pool, research_run))
    assert row_res["status"] == "completed"


async def _await_task(task):
    return await task


# ---------------------------------------------------------------------------
# Research kapasitesi fast işe dokunmaz; fast kapasitesi research işe dokunmaz
# ---------------------------------------------------------------------------


def test_queue_class_isolation_between_capacities(store, db_pool, publisher):
    fast_run, *_ = run(seed_execute_job(db_pool, queue_class="fast"))
    research_run, *_ = run(seed_execute_job(db_pool, queue_class="research"))

    assert run(store.claim_next_job("w-fast", lease_seconds=60, queue_class=("fast",))).run_id == fast_run
    assert run(store.claim_next_job("w-res", lease_seconds=60, queue_class=("research",))).run_id == research_run

    # her iki kapasiteyi birden çeken worker (küçük dağıtımda) ikisini de alır
    run_id_both, *_ = run(seed_execute_job(db_pool, queue_class="research"))
    both = run(store.claim_next_job("w-both", lease_seconds=60, queue_class=("fast", "research")))
    assert both is not None and both.run_id == run_id_both
