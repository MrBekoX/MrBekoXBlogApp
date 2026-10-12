"""B8 projection durumu birim testleri: monotonluk, çatışma, tombstone, senkron birleşimi.

Plan B8 kabul ölçütlerinin projection karşılıkları:
- olayların ters gelmesi → eski revizyon yok sayılır (monotonluk),
- kaldırma → tombstone durumu + stale kaldırma idempotent karşılanır,
- ilk sync sırasında güncelleme → canlı olay batch referansını ezer (kayıp yok),
- eski sonucun geç gelmesi → stale execution komutu reddedilir.
"""

from __future__ import annotations

import pytest

from messaging import (
    ContentApplyOutcome,
    ContentSyncState,
    StaleExecutionRejected,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def changed(article_id: str = "art-1", revision: int = 1, content_hash: str = HASH_A, action: str = "updated"):
    from messaging.contracts import ArticleContentChangedV1

    payload: dict[str, object] = {
        "article_id": article_id,
        "article_revision": revision,
        "action": action,
    }
    if action == "updated":
        payload["content_hash"] = content_hash
    return ArticleContentChangedV1.model_validate(payload)


def batch(sync_id: str, batch_index: int, total: int, items: list[dict]):
    from messaging.contracts import ContentSnapshotBatchV1

    return ContentSnapshotBatchV1.model_validate(
        {"sync_id": sync_id, "batch_index": batch_index, "total_batches": total, "items": items}
    )


def completed(sync_id: str, item_count: int):
    from messaging.contracts import ContentSnapshotCompletedV1

    return ContentSnapshotCompletedV1.model_validate({"sync_id": sync_id, "item_count": item_count})


class TestArticleChangedMonotonicity:
    def test_newer_revision_applies(self):
        state = ContentSyncState()
        assert state.apply_article_changed(changed(revision=3)).applied
        assert state.known_revision("art-1") == (3, HASH_A)

    def test_older_revision_ignored_out_of_order_delivery(self):
        state = ContentSyncState()
        state.apply_article_changed(changed(revision=5))
        outcome = state.apply_article_changed(changed(revision=4, content_hash=HASH_B))
        assert outcome.applied is False
        assert outcome.reason == "stale_revision"
        # Durum gerilemez: eski olay bilgi tabanını eski sürüme çekemez.
        assert state.known_revision("art-1") == (5, HASH_A)

    def test_same_revision_same_hash_is_idempotent_duplicate(self):
        state = ContentSyncState()
        state.apply_article_changed(changed(revision=2))
        outcome = state.apply_article_changed(changed(revision=2))
        assert outcome.reason == "duplicate"
        assert state.conflicts == ()

    def test_same_revision_different_hash_records_visible_conflict(self):
        state = ContentSyncState()
        state.apply_article_changed(changed(revision=2, content_hash=HASH_A))
        outcome = state.apply_article_changed(changed(revision=2, content_hash=HASH_B))
        assert outcome.applied is False
        assert outcome.reason == "revision_conflict"
        conflicts = state.conflicts
        assert len(conflicts) == 1
        assert conflicts[0].article_id == "art-1"
        assert conflicts[0].revision == 2
        assert conflicts[0].known_hash == HASH_A
        assert conflicts[0].incoming_hash == HASH_B
        # Çatışmada mevcut durum korunur (hangisi doğruysa backend tek kaynağı çözer).
        assert state.known_revision("art-1") == (2, HASH_A)


class TestTombstone:
    def test_removal_applies_and_state_moves_to_removal(self):
        state = ContentSyncState()
        state.apply_article_changed(changed(revision=4))
        outcome = state.apply_article_changed(changed(revision=5, action="unpublished"))
        assert outcome.applied and outcome.reason == "removed"
        assert state.known_revision("art-1") is None
        assert state.latest_removal_revision("art-1") == 5

    def test_duplicate_removal_is_idempotent(self):
        state = ContentSyncState()
        state.apply_article_changed(changed(revision=5, action="unpublished"))
        outcome = state.apply_article_changed(changed(revision=5, action="unpublished"))
        assert outcome.applied is False
        assert outcome.reason == "duplicate_removal"

    def test_older_removal_after_republish_ignored(self):
        # Olayların ters gelmesi: kaldırma (rev 5) → yeniden yayın (rev 6) → geç gelen
        # eski kaldırma; makaleyi tekrar indirmemeli.
        state = ContentSyncState()
        state.apply_article_changed(changed(revision=5, action="unpublished"))
        state.apply_article_changed(changed(revision=6, content_hash=HASH_B))
        outcome = state.apply_article_changed(changed(revision=5, action="unpublished"))
        assert outcome.applied is False
        assert outcome.reason == "stale_revision"
        assert state.known_revision("art-1") == (6, HASH_B)
        # Eski kaldırma kaydı revizyonla geçersiz; en yüksek kaldırma revizyonu değişmez.
        assert state.latest_removal_revision("art-1") == 5

    def test_update_at_or_below_removal_revision_rejected_as_stale(self):
        state = ContentSyncState()
        state.apply_article_changed(changed(revision=5, action="unpublished"))
        outcome = state.apply_article_changed(changed(revision=5, content_hash=HASH_B))
        assert outcome.applied is False
        # Revizyon 5 kaldırma anının ta kendisidir; yayımlanmış an olarak geri gelemez.
        assert outcome.reason == "stale_after_removal"


class TestStaleExecutionCommand:
    def test_command_older_than_known_removal_rejected(self):
        state = ContentSyncState()
        state.apply_article_changed(changed(revision=7))
        state.apply_article_changed(changed(revision=8, action="unpublished"))
        with pytest.raises(StaleExecutionRejected) as excinfo:
            state.ensure_execution_allowed("art-1", 7)
        assert excinfo.value.removal_revision == 8
        assert excinfo.value.command_revision == 7

    def test_command_at_removal_revision_rejected(self):
        state = ContentSyncState()
        state.apply_article_changed(changed(revision=8, action="unpublished"))
        with pytest.raises(StaleExecutionRejected):
            state.ensure_execution_allowed("art-1", 8)

    def test_command_after_republish_allowed(self):
        state = ContentSyncState()
        state.apply_article_changed(changed(revision=8, action="unpublished"))
        state.apply_article_changed(changed(revision=9, content_hash=HASH_C))
        # Komut yeni yayımlanmış anı (9) referans veriyor: kaldırma eski, yürütme serbest.
        state.ensure_execution_allowed("art-1", 9)
        # Revizyon 8 kaldırma anının kendisidir; ona referans veren komut da reddedilir.
        with pytest.raises(StaleExecutionRejected):
            state.ensure_execution_allowed("art-1", 8)

    def test_unknown_article_allowed(self):
        state = ContentSyncState()
        state.ensure_execution_allowed("art-unknown", 1)


class TestInitialSyncMerge:
    def test_batch_items_applied_as_references(self):
        state = ContentSyncState()
        outcome = state.apply_snapshot_batch(
            batch("sync-1", 0, 2, [
                {"article_id": "a", "article_revision": 1, "content_hash": HASH_A},
                {"article_id": "b", "article_revision": 2, "content_hash": HASH_B},
            ])
        )
        assert outcome.applied
        assert state.known_revision("a") == (1, HASH_A)
        assert state.known_revision("b") == (2, HASH_B)

    def test_duplicate_batch_index_is_idempotent(self):
        state = ContentSyncState()
        items = [{"article_id": "a", "article_revision": 1, "content_hash": HASH_A}]
        state.apply_snapshot_batch(batch("sync-1", 0, 1, items))
        outcome = state.apply_snapshot_batch(batch("sync-1", 0, 1, items))
        assert outcome.applied is False
        assert outcome.reason == "duplicate_batch"

    def test_live_change_during_sync_wins_over_late_batch_reference(self):
        # İlk sync sırasında güncelleme: canlı olay (rev 3) batch referansından (rev 2)
        # önce işlenirse, geç gelen batch kalemi stale sayılır — değişiklik KAYBOLMAZ.
        state = ContentSyncState()
        assert state.apply_article_changed(changed(article_id="a", revision=3, content_hash=HASH_C)).applied
        outcome = state.apply_snapshot_batch(
            batch("sync-1", 0, 1, [{"article_id": "a", "article_revision": 2, "content_hash": HASH_A}])
        )
        assert outcome.applied  # batch işlendi
        report = state.sync_report("sync-1")
        assert report is not None
        assert report.stale_items == 1
        assert state.known_revision("a") == (3, HASH_C)

    def test_batch_item_with_same_revision_conflicting_hash_recorded(self):
        state = ContentSyncState()
        state.apply_article_changed(changed(article_id="a", revision=2, content_hash=HASH_A))
        state.apply_snapshot_batch(
            batch("sync-1", 0, 1, [{"article_id": "a", "article_revision": 2, "content_hash": HASH_B}])
        )
        assert len(state.conflicts) == 1

    def test_completed_marks_sync_and_detects_mismatch(self):
        state = ContentSyncState()
        state.apply_snapshot_batch(
            batch("sync-1", 0, 1, [{"article_id": "a", "article_revision": 1, "content_hash": HASH_A}])
        )
        # Backend 2 bildirir ama 1 kalem işlendi → görünür uyumsuzluk.
        outcome = state.apply_snapshot_completed(completed("sync-1", item_count=2))
        assert outcome.applied
        report = state.sync_report("sync-1")
        assert report is not None
        assert report.completed
        assert report.item_count_mismatch

    def test_incomplete_sync_does_not_trigger_removal(self):
        # Tamamlanmamış snapshot: total=3, yalnız 2 batch geldi; indeks SİLİNMEZ,
        # yalnız görünür "incomplete" işaretlenir.
        state = ContentSyncState()
        state.apply_snapshot_batch(batch("sync-1", 0, 3, [{"article_id": "a", "article_revision": 1, "content_hash": HASH_A}]))
        state.apply_snapshot_batch(batch("sync-1", 1, 3, [{"article_id": "b", "article_revision": 1, "content_hash": HASH_B}]))
        state.apply_snapshot_completed(completed("sync-1", item_count=2))
        report = state.sync_report("sync-1")
        assert report is not None
        assert report.completed and report.incomplete
        # İndeks tarafında hiçbir makale kaldırılmadı (projection'da kaldırma yalnız tombstone'la olur).
        assert state.latest_removal_revision("a") is None
        assert state.latest_removal_revision("b") is None

    def test_orphan_completed_recorded_without_any_index_effect(self):
        state = ContentSyncState()
        outcome = state.apply_snapshot_completed(completed("sync-ghost", item_count=0))
        assert outcome.applied is False
        assert outcome.reason == "orphan_completion"
        assert state.orphan_completions == ("sync-ghost",)


class TestProfileProjectEvents:
    def test_profile_revision_monotonic(self):
        from messaging.contracts import ProfileContentChangedV1

        state = ContentSyncState()
        assert state.apply_profile_changed(
            ProfileContentChangedV1.model_validate({"profile_revision": 1, "content_hash": HASH_A})
        ).applied
        stale = state.apply_profile_changed(
            ProfileContentChangedV1.model_validate({"profile_revision": 1, "content_hash": HASH_B})
        )
        assert stale.reason == "revision_conflict"
        newer = state.apply_profile_changed(
            ProfileContentChangedV1.model_validate({"profile_revision": 2, "content_hash": HASH_B})
        )
        assert newer.applied
        assert state.profile_revision() == (2, HASH_B)

    def test_project_revision_monotonic_per_project(self):
        from messaging.contracts import ProjectContentChangedV1

        state = ContentSyncState()
        assert state.apply_project_changed(
            ProjectContentChangedV1.model_validate(
                {"project_id": "p1", "project_revision": 1, "content_hash": HASH_A}
            )
        ).applied
        # Aynı revizyon farklı proje: ayrı izler.
        assert state.apply_project_changed(
            ProjectContentChangedV1.model_validate(
                {"project_id": "p2", "project_revision": 1, "content_hash": HASH_B}
            )
        ).applied
        assert state.project_revision("p1") == (1, HASH_A)
        assert state.project_revision("p2") == (1, HASH_B)
