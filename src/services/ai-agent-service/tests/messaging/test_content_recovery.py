"""Production revision recovery checks without provider or broker doubles."""

from __future__ import annotations

import pytest

from agent_core.errors import AgentErrorCode, PortError
from messaging.content import ContentSyncState, StaleExecutionRejected
from messaging.contracts import ArticleContentChangedV1


def test_startup_restores_removed_content_guards() -> None:
    state = ContentSyncState()
    state.restore_articles([
        {"article_id": "article-1", "revision": 4, "content_hash": None, "deleted": True},
    ])
    with pytest.raises(StaleExecutionRejected):
        state.ensure_execution_allowed("article-1", 3)
    with pytest.raises(StaleExecutionRejected):
        state.ensure_execution_allowed("article-1", 4)
    state.ensure_execution_allowed("article-1", 5)
    assert state.known_revision("article-1") is None


def test_startup_restores_published_revision_ordering() -> None:
    state = ContentSyncState()
    state.restore_articles([
        {"article_id": "article-1", "revision": 4, "content_hash": "a" * 64, "deleted": False},
    ])
    event = ArticleContentChangedV1(
        article_id="article-1", article_revision=3, content_hash="b" * 64, action="updated"
    )
    assert state.preview_article_changed(event).reason == "stale_revision"
    assert state.known_revision("article-1") == (4, "a" * 64)


def test_revision_preview_never_commits_before_projection() -> None:
    state = ContentSyncState()
    event = ArticleContentChangedV1(
        article_id="article-1", article_revision=4, content_hash="a" * 64, action="updated"
    )
    assert state.preview_article_changed(event).applied
    assert state.known_revision("article-1") is None
    state.apply_article_changed(event)
    removal = ArticleContentChangedV1(article_id="article-1", article_revision=5, action="unpublished")
    assert state.preview_article_changed(removal).applied
    assert state.latest_removal_revision("article-1") is None
    assert state.known_revision("article-1") == (4, "a" * 64)


@pytest.mark.parametrize("row", [
    {"article_id": "article-1", "revision": -1, "content_hash": "a" * 64, "deleted": False},
    {"article_id": "article-1", "revision": 1, "content_hash": None, "deleted": False},
    {"article_id": "article-1", "revision": 1, "content_hash": "invalid", "deleted": False},
])
def test_invalid_persistent_revision_metadata_rejected(row) -> None:
    with pytest.raises(PortError) as raised:
        ContentSyncState().restore_articles([row])
    assert raised.value.code is AgentErrorCode.CONFIG_ERROR
