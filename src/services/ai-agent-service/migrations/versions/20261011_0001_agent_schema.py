"""agent schema'sı: inbox, jobs ve outbox tabloları (B4, D011).

Revision ID: 0001
Revises:
Create Date: 2026-10-11

Tablolar:

- ``agent.inbox_messages``: consumer kapsamlı mesaj idempotency kaydı.
  PK (consumer_name, message_id); bir mesajın işlenmiş olması yalnız bu satırın
  varlığıyla anlaşılır ve satır yalnız iş kabulü ile AYNI transaction'da yazılır
  (plan B4: "Job kalıcı olarak oluşmadan mesajın sorumluluğu devralınmış sayılmasın").
- ``agent.jobs``: kalıcı iş kabulü kaydı; run_id UNIQUE ile idempotent kabul,
  payload_hash ile çatışma saptaması (aynı run_id farklı payload → raporlanır).
- ``agent.outbox_events``: accepted olayının outbox kaydı; job ile aynı
  transaction'da yazılır, relay confirm sonrası published_at yazar.
  ``claimed_until`` lease kolonudur: birden fazla relay'in aynı kaydı kontrolsüz
  almasını engeller (plan B3 outbox publisher kurallarıyla aynı desen) ve
  relay çökmesinde kaydın lease bitiminde tekrar alınmasını sağlar.

gen_random_uuid() PostgreSQL 13+ gömülüdür (burada 18.0). Downgrade tüm
schema'yı kaldırır: tabloların tek sahibi bu zincirdir (D011).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "agent"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "inbox_messages",
        sa.Column("consumer_name", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("message_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("consumer_name", "message_id", name="pk_inbox_messages"),
        sa.CheckConstraint(
            "status IN ('accepted', 'conflict')", name="ck_inbox_messages_status"
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "run_id", sa.Uuid(), nullable=False, unique=True
        ),  # idempotent iş kabulü anahtarı (plan B4 adım 4)
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("origin_message_id", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("envelope", JSONB(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("job_id", name="pk_jobs"),
        sa.CheckConstraint("status IN ('accepted')", name="ck_jobs_status"),
        schema=SCHEMA,
    )

    op.create_table(
        "outbox_events",
        sa.Column("outbox_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("message_type", sa.String(length=64), nullable=False),
        sa.Column("exchange", sa.String(length=128), nullable=False),
        sa.Column("routing_key", sa.String(length=128), nullable=False),
        sa.Column("envelope", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("outbox_id", name="pk_outbox_events"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    # NOT: schema'nın kendisi bilinçli olarak bırakılır — alembic sürüm tablosu
    # (agent.alembic_version_agent) da onun içinde yaşar; CASCADE ile silinirse
    # alembic sürüm kaydını güncelleyemez ("relation does not exist"). Tablolar
    # sahibi olan zincirce kaldırılır; boş schema kapsül olarak kalır.
    op.drop_index("ix_outbox_events_pending", table_name="outbox_events", schema=SCHEMA)
    op.drop_table("outbox_events", schema=SCHEMA)
    op.drop_table("jobs", schema=SCHEMA)
    op.drop_table("inbox_messages", schema=SCHEMA)
