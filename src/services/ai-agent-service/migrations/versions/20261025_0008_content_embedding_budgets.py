"""Bound content-sync embedding cost across duplicate deliveries and restarts.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent.budget_reservations DROP CONSTRAINT budget_reservations_uncertainty_reason_check")
    op.execute("""ALTER TABLE agent.budget_reservations ADD CONSTRAINT budget_reservations_uncertainty_reason_check
        CHECK (uncertainty_reason IN ('lease_recovered','legacy_attempt','provider_estimated','provider_interrupted'))""")
    op.execute("""
        CREATE TABLE agent.content_embedding_budgets (
            scope_id text PRIMARY KEY CHECK (scope_id ~ '^[0-9a-f]{64}$'),
            token_limit bigint NOT NULL CHECK (token_limit > 0),
            request_limit bigint NOT NULL CHECK (request_limit > 0),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE agent.content_embedding_reservations (
            reservation_id uuid PRIMARY KEY,
            scope_id text NOT NULL REFERENCES agent.content_embedding_budgets(scope_id) ON DELETE CASCADE,
            reserved_amount bigint NOT NULL CHECK (reserved_amount > 0),
            actual_amount bigint CHECK (actual_amount > 0),
            status text NOT NULL CHECK (status IN ('reserved','reported','estimated','uncertain')),
            created_at timestamptz NOT NULL DEFAULT now(),
            resolved_at timestamptz,
            CHECK ((status = 'reserved') = (actual_amount IS NULL))
        )
    """)
    op.execute("CREATE INDEX ix_content_embedding_reservations_scope ON agent.content_embedding_reservations(scope_id)")


def downgrade() -> None:
    op.execute("DROP TABLE agent.content_embedding_reservations")
    op.execute("DROP TABLE agent.content_embedding_budgets")
    # Preserve all charged amounts while restoring the earlier metadata domain.
    op.execute("UPDATE agent.budget_reservations SET uncertainty_reason=NULL WHERE uncertainty_reason='provider_estimated'")
    op.execute("UPDATE agent.budget_reservations SET uncertainty_reason=NULL WHERE uncertainty_reason='provider_interrupted'")
    op.execute("ALTER TABLE agent.budget_reservations DROP CONSTRAINT budget_reservations_uncertainty_reason_check")
    op.execute("""ALTER TABLE agent.budget_reservations ADD CONSTRAINT budget_reservations_uncertainty_reason_check
        CHECK (uncertainty_reason IN ('lease_recovered','legacy_attempt'))""")
