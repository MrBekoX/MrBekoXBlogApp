"""job_leases_and_cancel_intents: B6 yürütme lease'i, fencing ve iptal niyeti (D011).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12

Değişiklikler (mevcut kolonlar değişmez; B4 kabul ve B5 terminal yazımları bozulmaz):

- ``agent.jobs`` genişletilir (ortak store sözleşmesi — entegrasyon sahibi tanımı):
    * ``queue_class``: 'fast' | 'research' — derin araştırma AYRI yürütme
      kapasitesinde koşar; hızlı sorular uzun işlere takılmaz (plan B6).
      Varsayılan 'fast': B4 kabulünün yazdığı işler hızlı sınıftadır; sınıf
      yalnız worker'ın router kararından sonraki erteleme yazımıyla değişir
      (router kararı agent çekirdeğinde üretilir; backend yeniden sınıflandırmaz).
    * ``lease_owner`` / ``lease_until``: claim eden worker'ın lease'i;
      ``FOR UPDATE SKIP LOCKED`` ile claim, biten lease ile SINIRLI recovery
      (plan B6: "Süresi geçen işi sınırlı recovery ile yeniden sahiplen").
    * ``execution_attempt``: yürütme deneme sayacı; fencing'in eşlik ettiği
      kalıcı sayaç (B1 zarfındaki ``delivery_attempt`` transport tekrarıdır,
      bu alan yürütme denemesidir — plan satır 237 ayrımı).
    * ``fencing_token``: ``agent.job_fencing_seq`` global monoton dizisinden
      claim anında tahsis edilir; eski worker'ın yeni denemenin sonucunu
      ezmesini engeller (complete/fail ATOMİK guard'da eşlik şartı).
    * ``result_json``: terminal/yanıt özeti (kullanım, belirsiz dış çağrı
      maliyeti işareti, yürütme kimliği).
    * ``started_at``: ilk claim anı (gözlem; kabul anı ``accepted_at`` kalır).
- ``ck_jobs_status`` genişletilir: 'queued' ve 'running' eklenir. B4 kabulünün
  yazdığı 'accepted' değeri claim edilebilir bekleyen durum olarak KORUNUR
  (worker her ikisini claim eder); 'queued' ortak sözleşmedeki bekleyen
  karşılıktır (B7 test double'ları bu değeri yazar).
- ``agent.cancel_intents``: iptal niyeti kaydı (run_id PK, requested_at,
  requested_by). B7 ``control_store.record_mark`` akışının yazdığı satır;
  complete/fail guard'ı ve claim koşulu ``NOT EXISTS`` ile okur. Intent
  terminal DEĞİLDİR: terminal 'cancelled' geçişini B7'nin atomik koşullu
  UPDATE'i üretir (terminal-öncelik kuralı: completed commit'i intent
  insert'ünden önceysede tamamlanma kazanır).
- ``agent.job_fencing_seq``: bigint global monoton dizi. Claim arasında
  kesin artan token üretir; sıfırlanmaz (downgrade'de diziyle birlikte düşer).

Downgrade zinciri 0002'ye döner: 'queued'/'running' satırları silinir, yeni
kolonlar düşürülür ve kısıt 0002 değer kümesine döndürülür.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "agent"

#: 0002 durumlarına B6 bekleyen/yürütülüyor durumlarının eklenmesi.
JOB_STATUSES = (
    "accepted",
    "queued",
    "running",
    "completed",
    "partially_completed",
    "failed",
    "cancelled",
)

JOB_STATUS_CONSTRAINT_SQL = (
    "status IN ('accepted', 'queued', 'running', 'completed', "
    "'partially_completed', 'failed', 'cancelled')"
)


def upgrade() -> None:
    # Fencing dizisi: claim anında atomik, kesin artan token.
    op.execute(f"CREATE SEQUENCE IF NOT EXISTS {SCHEMA}.job_fencing_seq AS bigint START WITH 1")

    # İş durumu kümesi genişletilir; mevcut 'accepted'/'terminal' değerleri korunur.
    op.drop_constraint("ck_jobs_status", "jobs", schema=SCHEMA, type_="check")
    op.create_check_constraint("ck_jobs_status", "jobs", JOB_STATUS_CONSTRAINT_SQL, schema=SCHEMA)

    op.add_column(
        "jobs",
        sa.Column(
            "queue_class",
            sa.String(length=16),
            nullable=False,
            server_default="fast",
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_jobs_queue_class", "jobs", "queue_class IN ('fast', 'research')", schema=SCHEMA
    )
    op.add_column("jobs", sa.Column("lease_owner", sa.String(length=128), nullable=True), schema=SCHEMA)
    op.add_column(
        "jobs", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "jobs",
        sa.Column(
            "execution_attempt",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_jobs_execution_attempt", "jobs", "execution_attempt >= 0", schema=SCHEMA
    )
    op.add_column(
        "jobs",
        sa.Column(
            "fencing_token",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        schema=SCHEMA,
    )
    op.add_column("jobs", sa.Column("result_json", JSONB(), nullable=True), schema=SCHEMA)
    op.add_column(
        "jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA
    )

    # Claim taramaları: bekleyen işler (kabul sırasına göre) ve lease'i bitmiş
    # yürütmeler (recovery adayı). Kısmi endeksler claim yolunu dar tutar.
    op.create_index(
        "ix_jobs_claimable",
        "jobs",
        ["queue_class", "accepted_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('accepted', 'queued')"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jobs_expired_running",
        "jobs",
        ["lease_until"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
        schema=SCHEMA,
    )

    # İptal niyeti: terminal DEĞİL; complete/fail guard'ının ve claim koşulunun
    # okuduğu satır. Yazım B7 control akışının sorumluluğudur (outbox olayıyla).
    op.create_table(
        "cancel_intents",
        sa.Column("run_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name="pk_cancel_intents"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("cancel_intents", schema=SCHEMA)
    op.drop_index("ix_jobs_expired_running", table_name="jobs", schema=SCHEMA)
    op.drop_index("ix_jobs_claimable", table_name="jobs", schema=SCHEMA)
    op.drop_column("jobs", "started_at", schema=SCHEMA)
    op.drop_column("jobs", "result_json", schema=SCHEMA)
    op.drop_column("jobs", "fencing_token", schema=SCHEMA)
    op.drop_column("jobs", "execution_attempt", schema=SCHEMA)
    op.drop_column("jobs", "lease_until", schema=SCHEMA)
    op.drop_column("jobs", "lease_owner", schema=SCHEMA)
    op.drop_constraint("ck_jobs_queue_class", "jobs", schema=SCHEMA, type_="check")
    op.drop_column("jobs", "queue_class", schema=SCHEMA)
    op.execute(f"DELETE FROM {SCHEMA}.jobs WHERE status IN ('queued', 'running')")
    op.drop_constraint("ck_jobs_status", "jobs", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "ck_jobs_status",
        "jobs",
        "status IN ('accepted', 'completed', 'partially_completed', 'failed', 'cancelled')",
        schema=SCHEMA,
    )
    op.execute(f"DROP SEQUENCE IF EXISTS {SCHEMA}.job_fencing_seq")
