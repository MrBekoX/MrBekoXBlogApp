"""v2 wire geri dönüş (rollback) drain aracı (karar kaydı K4).

Amaç: Python worker'ı v2'yi bilmeyen eski sürüme geri almadan ÖNCE okunamaz v2
backlog'u bırakmamak. Eski worker v2 kuyruklarını tüketmez ve ``agent.jobs``
üzerindeki v2 satırlarını claim/kapatamaz (migration 0005 tetikleyicisi); bu
yüzden başlamış v2 işleri ya yeni worker ile bitirilir ya da bu araçla
kontrollü iptal edilir.

Geri dönüş sırası:

1. Backend üretici anahtarı kapatılır (``AgentWireV2:Enabled=false``): yeni v2
   run'ı üretilmez (``auto`` v1'e düşer, ``who_am_i`` 503 kapasite hatası alır).
2. Yeni worker çalışmaya devam ederken başlamış v2 işleri biter; durum
   ``--check`` ile izlenir.
3. Beklenemeyecek işler ``--cancel`` ile kapatılır: her aktif v2 işi için iptal
   niyeti + ``cancelled`` durumu + run'ın KENDİ sürümünde (v2)
   ``agent.run.cancelled`` olayı (gerekçe ``wire_v2_rollback``) TEK transaction'da
   yazılır; olayları outbox relay'i backend'e taşır (relay'in hâlâ çalışıyor
   olması gerekir).
4. ``--check`` sıfır aktif v2 işi gösterdikten sonra Python geri alınır; alembic
   ``downgrade 0003`` aktif v2 işi varken zaten reddeder.

Kullanım (``app`` dizini import kökündedir — ``cd app`` veya ``PYTHONPATH=app``)::

    python -m messaging.wire_drain --check            # aktif v2 işi varsa çıkış kodu 1
    python -m messaging.wire_drain --cancel           # aktif v2 işlerini v2 cancelled ile kapatır
    python -m messaging.wire_drain --check --json     # makine-okur özet

Çıkış kodları: 0 = aktif v2 işi yok (``--cancel`` sonrası dahil); 1 = aktif v2
işi kaldı; 2 = yapılandırma/bağlantı hatası. DB ayarları servisle aynıdır
(``AGENT_DB_*``; ``.env`` desteği ``env_file``). Havuz ``agent.worker_wire_max``
değerini en az hedef sürüm kadar bildirir; aksi halde tetikleyici güncellemeyi
atlardı.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field, replace
from typing import Any

from .contracts import WIRE_VERSION_V2
from .control_store import WIRE_DRAIN_REASON, ControlStore

__all__ = ["DrainReport", "check_active", "cancel_active", "main"]

logger = logging.getLogger("wire_drain")


@dataclass(frozen=True)
class DrainReport:
    """Tek drain çağrısının özeti."""

    wire_version: int
    active_by_version: dict[int, int]
    cancelled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        """Hedef sürümde hâlâ aktif (terminal olmayan) iş sayısı."""

        return int(self.active_by_version.get(self.wire_version, 0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "wire_version": self.wire_version,
            "active_by_version": {str(k): v for k, v in sorted(self.active_by_version.items())},
            "remaining": self.remaining,
            "cancelled": list(self.cancelled),
            "skipped": list(self.skipped),
        }


async def check_active(store: ControlStore, *, wire_version: int = WIRE_VERSION_V2) -> DrainReport:
    """Aktif işlerin sürüm dağılımı (``--check``)."""

    return DrainReport(wire_version=wire_version, active_by_version=await store.active_jobs_by_wire_version())


async def cancel_active(
    store: ControlStore,
    *,
    wire_version: int = WIRE_VERSION_V2,
    reason: str = WIRE_DRAIN_REASON,
    batch_size: int = 100,
) -> DrainReport:
    """Hedef sürümün aktif işlerini run sürümünün ``cancelled`` olayıyla kapatır (``--cancel``).

    Her iş kendi transaction'ındadır (``ControlStore.finalize_cancelled_for_drain``);
    bu arada terminale geçen iş atlanır. Bir turda ilerleme olmazsa döngü biter
    (sonsuz döngü yok); kalan sayı rapordadır.
    """

    cancelled: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    while True:
        rows = await store.active_jobs_for_wire_version(wire_version, limit=batch_size)
        candidates = [str(row["run_id"]) for row in rows if str(row["run_id"]) not in seen]
        if not candidates:
            break
        for run_id in candidates:
            seen.add(run_id)
            if await store.finalize_cancelled_for_drain(
                run_id, reason=reason, expected_wire_version=wire_version
            ):
                cancelled.append(run_id)
            else:
                skipped.append(run_id)
    report = await check_active(store, wire_version=wire_version)
    return replace(report, cancelled=cancelled, skipped=skipped)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m messaging.wire_drain",
        description="v2 wire geri dönüşü öncesi aktif v2 işlerini denetler veya kontrollü iptal eder.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="aktif v2 işlerini say; varsa çıkış kodu 1")
    mode.add_argument("--cancel", action="store_true", help="aktif v2 işlerini v2 cancelled olayıyla kapat")
    parser.add_argument("--wire-version", type=int, default=WIRE_VERSION_V2, help="hedef wire sürümü (varsayılan 2)")
    parser.add_argument("--reason", default=WIRE_DRAIN_REASON, help="iptal gerekçesi (varsayılan wire_v2_rollback)")
    parser.add_argument("--json", action="store_true", help="özeti JSON olarak yaz")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    from env_file import EnvConfigError, EnvFileError, load_env_file

    from .db import AgentDbError, connect_pool, from_env

    try:
        load_env_file()
        settings = from_env()
    except (AgentDbError, EnvFileError, EnvConfigError) as error:
        print(f"yapılandırma hatası: {error}", file=sys.stderr)
        return 2
    # Tetikleyici: oturum en az hedef sürümü bildirmeli (aksi halde güncelleme atlanır).
    settings = replace(settings, worker_wire_max=max(settings.worker_wire_max, args.wire_version))
    try:
        pool = await connect_pool(settings)
    except AgentDbError as error:
        print(f"bağlantı hatası: {error}", file=sys.stderr)
        return 2
    try:
        store = ControlStore(pool, schema=settings.schema)
        if args.cancel:
            report = await cancel_active(store, wire_version=args.wire_version, reason=args.reason)
        else:
            report = await check_active(store, wire_version=args.wire_version)
    finally:
        await pool.close()

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False))
    else:
        distribution = ", ".join(f"v{k}={v}" for k, v in sorted(report.active_by_version.items())) or "yok"
        print(f"aktif işler (sürüme göre): {distribution}")
        if args.cancel:
            print(f"iptal edilen v{report.wire_version} işi: {len(report.cancelled)}; atlanan: {len(report.skipped)}")
        print(f"kalan aktif v{report.wire_version} işi: {report.remaining}")
    return 0 if report.remaining == 0 else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
