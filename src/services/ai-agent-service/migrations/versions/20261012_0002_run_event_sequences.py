"""run_event_sequences: run başına atomik event_sequence üretimi (B5, D011).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12

Değişiklikler (ADDITIVE — mevcut kolonlar değişmez):

- ``agent.run_event_sequences``: run_id PK + last_sequence. B5 olay yayıncısı
  sırayı ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING`` ile TEK satır
  kilidi altında tahsis eder; eşzamanlı yayıncılar çakışan/ters sequence
  üretemez (plan B5: "Olay sırası için run başına atomik event_sequence").
  B4'ün accepted olayı event_sequence 0'dır; tahsis bu yüzden 1'den başlar.
- ``ck_jobs_status`` genişletilir: terminal sonuç yayıncısı iş durumunu
  outbox kaydıyla AYNI transaction'da yazar (plan B5: "Kritik durum ve
  terminal sonuçla agent outbox kaydıyla AYNI transaction'da sakla").
  Kısıt genişlemesi veri kaybettirmez; B4'ün 'accepted' değerleri korunur.

Downgrade zinciri 0001'e döner: kısıt eski değer kümesine döndürülür (yalnız
'accepted' kalan satır varken geçerlidir) ve tablo düşürülür.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "agent"

#: B5 sonrası geçerli iş durumları: accepted + terminal sonuçlar.
#: 'needs_input' BURADA YOKTUR: kullanıcı girdisi bekleme terminal değildir ve
#: iş durumu accepted kalır (backend projection'ı NeedsInput'u ayrı saklar).
JOB_STATUSES = ("accepted", "completed", "partially_completed", "failed", "cancelled")


def upgrade() -> None:
    op.create_table(
        "run_event_sequences",
        sa.Column("run_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_run_event_sequences"),
        schema=SCHEMA,
    )

    op.drop_constraint("ck_jobs_status", "jobs", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "ck_jobs_status",
        "jobs",
        "status IN ('accepted', 'completed', 'partially_completed', 'failed', 'cancelled')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM {SCHEMA}.jobs "
        "WHERE status NOT IN ('accepted')"
    )
    op.drop_constraint("ck_jobs_status", "jobs", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "ck_jobs_status", "jobs", "status IN ('accepted')", schema=SCHEMA
    )
    op.drop_table("run_event_sequences", schema=SCHEMA)
