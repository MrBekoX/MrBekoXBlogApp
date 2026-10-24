"""Run-wide budget reservations survive crashes and lease recovery.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE agent.run_budgets (
            run_id uuid PRIMARY KEY REFERENCES agent.jobs(run_id) ON DELETE CASCADE,
            limits jsonb NOT NULL CHECK (jsonb_typeof(limits) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE agent.budget_reservations (
            reservation_id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES agent.run_budgets(run_id) ON DELETE CASCADE,
            fencing_token bigint NOT NULL CHECK (fencing_token >= 0),
            kind text NOT NULL CHECK (kind IN
                ('model_call','token','tool_call','web_search_call','source_page_read','research_round')),
            reserved_amount bigint NOT NULL CHECK (reserved_amount > 0),
            actual_amount bigint CHECK (actual_amount > 0),
            status text NOT NULL CHECK (status IN ('reserved','committed','released','uncertain')),
            created_at timestamptz NOT NULL DEFAULT now(),
            resolved_at timestamptz,
            uncertainty_reason text CHECK (uncertainty_reason IN ('lease_recovered','legacy_attempt')),
            CHECK ((status = 'committed') = (actual_amount IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX ix_budget_reservations_run ON agent.budget_reservations(run_id)")


def downgrade() -> None:
    op.execute("DROP TABLE agent.budget_reservations")
    op.execute("DROP TABLE agent.run_budgets")
