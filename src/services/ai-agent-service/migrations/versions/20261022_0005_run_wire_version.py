"""run_wire_version: run başına mesaj sözleşmesi sürümü ve sürüm izolasyonu (Who am I, K4).

Revision ID: 0005
Revises: 0003
Create Date: 2026-10-22

Numaralandırma notu: kimlik karar kaydındaki adla (K4 "migration 0005") hizalıdır;
``0004`` bilinçli olarak kullanılmamıştır ve zincir 0003 → 0005'tir. Yeni bir
migration ``down_revision = "0005"`` ile eklenmelidir (ikinci head oluşmaz).

Değişiklikler (ADDITIVE — mevcut kolonlar ve v1 davranışı değişmez):

- ``agent.jobs.wire_version smallint NOT NULL DEFAULT 1`` + ``ck_jobs_wire_version``
  (1|2). Run'ın wire sürümü kabul anında execute zarfının ``schema_version``'ından
  yazılır ve run boyunca değişmez; mevcut (v1) satırlar varsayılanla 1 olur —
  eksik değer v1 okunur (restart/legacy satırlar migration'sız yorumlanmaz).
- ``trg_jobs_wire_claim_guard`` (jobs BEFORE UPDATE): satırın sürümü oturumun
  ``agent.worker_wire_max`` GUC'undan (yoksa/boşsa 1) büyükse güncelleme SESSİZCE
  ATLANIR (``RETURN NULL``). Etki: v2'yi bilmeyen eski worker kodu v2 işini claim
  edemez, lease/terminal/iptal/reaper/deneme-tükenmesi güncellemesi yapamaz
  (koşullu UPDATE'leri "satır yok" görür). Yeni worker DB havuzu bağlantı
  başlangıcında ``server_settings={'agent.worker_wire_max': '2'}`` bildirir
  (``messaging.db.connect_pool``). ``queue_class`` kapasite sınıfıdır; protokol
  izolasyonu bu tetikleyicidir.
- ``trg_outbox_wire_version_guard`` (outbox_events BEFORE INSERT): zarfın
  ``run_id``'si için jobs satırı varsa ``envelope.schema_version`` ≠
  ``jobs.wire_version`` ise kayıt ``check_violation`` (23514) ile REDDEDİLİR:
  bir run'ın olayları sürüm karıştıramaz (ör. v2 run'ı için v1 cancelled).

Downgrade: aktif (terminal olmayan) v2 işi varken REDDEDİLİR — önce
``python -m messaging.wire_drain --check`` / ``--cancel`` ile v2 işleri boşaltılır
(geri dönüşte okunamaz v2 backlog bırakılmaz). Ardından iki tetikleyici,
fonksiyonları, kısıt ve kolon kaldırılır.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# SQL içi hata metinleri bilinçli ASCII'dir (istemci kodlamasından bağımsız okunur).

revision: str = "0005"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "agent"

#: Tetikleyicinin okuduğu oturum ayarı (messaging.wire.WORKER_WIRE_MAX_SETTING ile aynı ad).
WORKER_WIRE_MAX_SETTING = "agent.worker_wire_max"

#: Aktif (terminal olmayan) iş durumları — downgrade guard'ı.
ACTIVE_JOB_STATUSES = ("accepted", "queued", "running")


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("wire_version", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_jobs_wire_version", "jobs", "wire_version IN (1, 2)", schema=SCHEMA
    )

    # Claim/güncelleme izolasyonu: eski worker (GUC yok → 1) v2 satırına dokunamaz.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.jobs_wire_claim_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.wire_version > coalesce(
                nullif(current_setting('{WORKER_WIRE_MAX_SETTING}', true), ''), '1'
            )::int THEN
                RETURN NULL;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_jobs_wire_claim_guard BEFORE UPDATE ON {SCHEMA}.jobs "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.jobs_wire_claim_guard()"
    )

    # Outbox sürüm bağı: run olayının zarf sürümü run'ın wire sürümüyle aynı olmalı.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.outbox_wire_version_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            run_text text := NEW.envelope->>'run_id';
            envelope_version int := (NEW.envelope->>'schema_version')::int;
            job_version smallint;
        BEGIN
            IF run_text IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT j.wire_version INTO job_version FROM {SCHEMA}.jobs j WHERE j.run_id = run_text::uuid;
            IF NOT FOUND THEN
                RETURN NEW;
            END IF;
            IF envelope_version IS DISTINCT FROM job_version THEN
                RAISE EXCEPTION USING
                    ERRCODE = 'check_violation',
                    MESSAGE = format(
                        'outbox zarf surumu (%s) run wire surumuyle (%s) uyusmuyor: run_id=%s',
                        envelope_version, job_version, run_text
                    );
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_outbox_wire_version_guard BEFORE INSERT ON {SCHEMA}.outbox_events "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.outbox_wire_version_guard()"
    )


def downgrade() -> None:
    statuses = ", ".join(f"'{status}'" for status in ACTIVE_JOB_STATUSES)
    op.execute(
        f"""
        DO $$
        DECLARE
            active_v2 bigint;
        BEGIN
            SELECT count(*) INTO active_v2 FROM {SCHEMA}.jobs
            WHERE wire_version > 1 AND status IN ({statuses});
            IF active_v2 > 0 THEN
                RAISE EXCEPTION USING
                    ERRCODE = 'object_in_use',
                    MESSAGE = format(
                        '%s aktif v2 isi var; once python -m messaging.wire_drain --check/--cancel calistirin',
                        active_v2
                    );
            END IF;
        END
        $$
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS trg_outbox_wire_version_guard ON {SCHEMA}.outbox_events")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.outbox_wire_version_guard()")
    op.execute(f"DROP TRIGGER IF EXISTS trg_jobs_wire_claim_guard ON {SCHEMA}.jobs")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.jobs_wire_claim_guard()")
    op.drop_constraint("ck_jobs_wire_version", "jobs", schema=SCHEMA, type_="check")
    op.drop_column("jobs", "wire_version", schema=SCHEMA)
