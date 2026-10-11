"""pgvector adaptör sözleşmesi testleri (A3'te çalıştırılmaz, belgelenir).

Sınır kararı: bu testler gerçek bağlantı KURMAZ ve kuramaz; şema dosyasının
sözleşme öğelerini taşıdığını ve iskeletin sürücüsüz ortamda anlaşılır
config_error ürettiğini sabitler. Gerçek entegrasyon B8'de doğrulanır.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.content import PgvectorContentIndex, PgvectorContentIndexStore
from agent_core.content.config import INDEX_VERSION
from agent_core.errors import AgentErrorCode, PortError
from agent_core.content import pgvector as pgvector_module


def schema_sql() -> str:
    return (Path(pgvector_module.__file__).parent / "pgvector_schema.sql").read_text(
        encoding="utf-8"
    )


def test_skeleton_refuses_to_construct_without_driver() -> None:
    with pytest.raises(PortError) as excinfo:
        PgvectorContentIndex(dsn="postgresql://localhost/test")
    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
    assert "B8" in excinfo.value.message


def test_skeleton_declares_same_operation_surface_as_in_memory_index() -> None:
    skeleton_methods = {
        name for name, value in vars(PgvectorContentIndex).items() if not name.startswith("_")
    }
    assert {"index_article", "remove_article", "search"} <= skeleton_methods


def test_store_protocol_declares_driver_surface() -> None:
    assert hasattr(PgvectorContentIndexStore, "upsert_article_chunks")
    assert hasattr(PgvectorContentIndexStore, "delete_article")
    assert hasattr(PgvectorContentIndexStore, "search_hybrid")


def test_schema_sql_carries_contract_columns_and_indexes() -> None:
    sql = schema_sql()
    assert "CREATE TABLE IF NOT EXISTS agent.content_chunk" in sql
    assert "PRIMARY KEY (article_id, article_revision, chunk_index)" in sql
    for column in (
        "content_hash",
        "heading_path",
        "anchor",
        "canonical_url",
        "language",
        "published",
        "embedding_model_id",
        "index_version",
    ):
        assert column in sql, f"şemada {column} sütunu sözleşmesi eksik"
    assert "USING hnsw" in sql  # yaklaşık komşu araması [PGVECTOR#C1]
    assert "vector_cosine_ops" in sql
    assert "tsvector" in sql  # full text search tarafı [PGVECTOR#C2]
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql


def test_index_version_constant_is_declared() -> None:
    assert isinstance(INDEX_VERSION, int) and INDEX_VERSION >= 1
    assert PgvectorContentIndex.index_version == INDEX_VERSION
