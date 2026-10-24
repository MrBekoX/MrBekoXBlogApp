"""Durable OpenAI embeddings, article chunks and removal tombstones.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE agent.embedding_cache (
            model_id text NOT NULL,
            dimensions integer NOT NULL CHECK (dimensions > 0),
            input_hash text NOT NULL CHECK (length(input_hash) = 64),
            embedding real[] NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (model_id, dimensions, input_hash),
            CHECK (cardinality(embedding) = dimensions)
        )
    """)
    op.execute("""
        CREATE TABLE agent.content_articles (
            article_id text PRIMARY KEY,
            revision bigint NOT NULL CHECK (revision >= 0),
            content_hash text,
            deleted boolean NOT NULL DEFAULT false,
            model_id text,
            dimensions integer,
            index_version integer,
            chunk_chars integer,
            url_template text,
            published boolean NOT NULL DEFAULT true,
            chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count >= 0)
        )
    """)
    op.execute("""
        CREATE TABLE agent.content_chunks (
            article_id text NOT NULL REFERENCES agent.content_articles(article_id) ON DELETE CASCADE,
            chunk_index integer NOT NULL CHECK (chunk_index >= 0),
            content text NOT NULL,
            heading text,
            char_start integer NOT NULL,
            char_end integer NOT NULL CHECK (char_end >= char_start),
            heading_path text[] NOT NULL,
            anchor text NOT NULL,
            language text,
            published boolean NOT NULL,
            canonical_url text,
            embedding real[] NOT NULL CHECK (cardinality(embedding) = 1536),
            PRIMARY KEY (article_id, chunk_index)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE agent.content_chunks")
    op.execute("DROP TABLE agent.content_articles")
    op.execute("DROP TABLE agent.embedding_cache")
