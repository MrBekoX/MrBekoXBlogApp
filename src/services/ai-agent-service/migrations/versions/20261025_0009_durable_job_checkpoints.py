"""Commit authoritative checkpoint bytes with job ownership in PostgreSQL.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE agent.job_checkpoints (
            run_id uuid NOT NULL REFERENCES agent.jobs(run_id) ON DELETE CASCADE,
            checkpoint_id text NOT NULL CHECK (length(checkpoint_id) BETWEEN 1 AND 128),
            payload bytea NOT NULL,
            fencing_token bigint NOT NULL CHECK (fencing_token > 0),
            version bigserial NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (run_id,checkpoint_id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX ix_job_checkpoints_latest ON agent.job_checkpoints(run_id,version DESC)")


def downgrade() -> None:
    # Legacy files are deliberately not rewritten. Production rollback needs
    # quiescence plus an approved state export/restore; prefer roll-forward.
    op.execute("DROP TABLE agent.job_checkpoints")
