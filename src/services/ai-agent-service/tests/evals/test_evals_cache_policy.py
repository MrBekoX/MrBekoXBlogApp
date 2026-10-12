"""Önbellek anahtar sözleşmesi denetimleri (plan A10 madde 5).

İçerik hash'i, dil, soru kapsamı ve yapılandırma sürümleri anahtara girmeli;
konuşmaya bağlı (geçmiş/sezim) istekler ortak önbelleğe girmemeli.
"""

from __future__ import annotations

import evals_bootstrap  # noqa: F401 - sys.path kurulumu

from evals import articles as fx
from evals.cache_policy import (
    answer_cache_key,
    config_fingerprint,
    is_shared_cache_eligible,
    question_scope,
)
from evals.harness import EMBEDDING_MODEL_ID, _make_context, _make_history
from agent_core.models import compute_content_hash
from evals.dataset import case_by_id


def _key(context, fingerprint: str | None = None) -> str:
    snapshot = context.article_snapshot
    return answer_cache_key(
        content_hash=snapshot.content_hash if snapshot else (context.article_content_hash or "-"),
        language=context.language,
        scope=question_scope(context),
        config_fingerprint_hex=fingerprint or config_fingerprint(embedding_model_id=EMBEDDING_MODEL_ID),
    )


def _article_context(run_id: str):
    case = case_by_id("c01")
    return _make_context(case, run_id, fx.EVAL_ARTICLES[fx.ASYNCIO_ARTICLE_ID])


def test_same_inputs_produce_same_key():
    assert _key(_article_context("k-a")) == _key(_article_context("k-b"))


def test_content_hash_changes_key():
    snapshot = fx.EVAL_ARTICLES[fx.ASYNCIO_ARTICLE_ID]
    case = case_by_id("c01")
    before = _key(_make_context(case, "k-1", snapshot))
    advanced_content = snapshot.content + "\nYeni satır."
    advanced = snapshot.model_copy(
        update={
            "content": advanced_content,
            "content_hash": compute_content_hash(advanced_content),
            "article_revision": snapshot.article_revision + 1,
        }
    )
    after = _key(_make_context(case, "k-2", advanced))
    assert before != after


def test_language_changes_key():
    case = case_by_id("c01")
    tr = _key(_make_context(case, "k-tr", fx.EVAL_ARTICLES[fx.ASYNCIO_ARTICLE_ID]))
    en_case = case.model_copy(update={"language": "en"})
    en = _key(_make_context(en_case, "k-en", fx.EVAL_ARTICLES[fx.ASYNCIO_ARTICLE_ID]))
    assert tr != en


def test_scope_changes_key():
    case = case_by_id("c01")
    article_ctx = _make_context(case, "k-art", fx.EVAL_ARTICLES[fx.ASYNCIO_ARTICLE_ID])
    general_ctx = _make_context(case, "k-gen", None)
    selected_ctx = _make_context(case, "k-sel", fx.EVAL_ARTICLES[fx.ASYNCIO_ARTICLE_ID]).model_copy(
        update={"selected_text": "kuyruk"}
    )
    keys = {_key(ctx) for ctx in (article_ctx, general_ctx, selected_ctx)}
    assert len(keys) == 3
    assert {question_scope(ctx) for ctx in (article_ctx, general_ctx, selected_ctx)} == {
        "article",
        "general",
        "selected",
    }


def test_config_version_changes_key():
    context = _article_context("k-cfg")
    base = _key(context, config_fingerprint(embedding_model_id=EMBEDDING_MODEL_ID))
    bumped = _key(context, config_fingerprint(embedding_model_id=EMBEDDING_MODEL_ID, prompt_template_version="v2"))
    embed_changed = _key(context, config_fingerprint(embedding_model_id="other-model"))
    assert base != bumped
    assert base != embed_changed


def test_conversation_dependent_requests_are_not_shared():
    context = _article_context("k-hist")
    assert is_shared_cache_eligible(context) is True
    history_ctx = context.model_copy(update={"conversation_history": [_make_history("user", "önceki tur")]})
    selected_ctx = context.model_copy(update={"selected_text": "kuyruk"})
    assert is_shared_cache_eligible(history_ctx) is False
    assert is_shared_cache_eligible(selected_ctx) is False
