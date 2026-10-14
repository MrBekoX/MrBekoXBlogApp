"""``HttpContentRepository`` OFFLINE testleri.

Tüm akışlar ``httpx.MockTransport`` ile scripted yanıt üzerinden koşar —
GERÇEK AĞ ÇAĞRISI YAPILMAZ. Kanıtlananlar: sözleşme alanlarının
``ArticleSnapshot``'a birebir maplenmesi (alan adları models/article.py'den),
hash-tutarlılığı (endpoint hash'i agent tarafı ``compute_content_hash``
hesabıyla tutarlı akar — stale_snapshot guard'ının girdisi), 404 → ``not_found``,
HTTP/ağ arızası → ``provider_error`` (retryable bayrağıyla), zaman aşımı →
``timeout``, ortam fabrikası (``AGENT_CONTENT_BASE_URL`` doluysa depo, boşsa
``None`` — mevcut davranış).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from agent_core.adapters import (
    ContentRepositorySettings,
    HttpContentRepository,
    build_content_repository_from_env,
)
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import compute_content_hash
from agent_core.ports import ContentRepository

pytest.importorskip("httpx")

ARTICLE_ID = "3f2b8c6e-1a4d-4e5f-9a7b-2c3d4e5f6a7b"
ARTICLE_CONTENT = "# Başlık\n\nGövde paragrafı: asyncio içerik deposu."
CONTENT_HASH = compute_content_hash(ARTICLE_CONTENT)
PUBLISHED_AT = "2026-10-01T09:30:00Z"


def make_payload(**overrides) -> dict:
    """SABİT SÖZLEŞME yanıt gövdesi: ApiResponse zarfı + sözleşme alanları.

    Backend uç konvansiyonu: 200 gövdesi ``{"success": true, "data": {…}}``
    zarfıdır (AgentInternalEndpoints.cs); adaptör ``data`` alanını açar.
    """

    body = {
        "articleId": ARTICLE_ID,
        "revision": 7,
        "contentHash": CONTENT_HASH,
        "title": "İçerik depolu makale",
        "content": ARTICLE_CONTENT,
        "tags": ["python", "asyncio"],
        "publishedAt": PUBLISHED_AT,
    }
    body.update(overrides)
    return {"success": True, "data": body}


def make_repo(
    payload: dict | Exception,
    *,
    status: int = 200,
    captured: list[httpx.Request] | None = None,
    settings: ContentRepositorySettings | None = None,
) -> HttpContentRepository:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(
            status,
            content=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpContentRepository(
        settings
        or ContentRepositorySettings(base_url="http://content.test/api/v1", service_key="ic-anahtar"),
        client=client,
    )


def get_article(repo: HttpContentRepository, article_id: str = ARTICLE_ID):
    return asyncio.run(repo.get_article(article_id))


# ------------------------------------------------------------------ found + mapleme


def test_get_article_maps_contract_fields_one_to_one() -> None:
    captured: list[httpx.Request] = []
    repo = make_repo(make_payload(), captured=captured)

    snapshot = get_article(repo)

    # SABİT SÖZLEŞME yolu + yetki başlığı
    assert str(captured[0].url) == (
        f"http://content.test/api/v1/agent/internal/content/{ARTICLE_ID}"
    )
    assert captured[0].headers["x-agent-service-key"] == "ic-anahtar"

    # Alan adları models/article.py'den birebir
    assert snapshot.article_id == ARTICLE_ID
    assert snapshot.article_revision == 7
    assert snapshot.content_hash == CONTENT_HASH
    assert snapshot.title == "İçerik depolu makale"
    assert snapshot.content == ARTICLE_CONTENT
    assert snapshot.tags == ["python", "asyncio"]
    assert snapshot.published_at == datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
    # Yanıtta taşınmayan alanlar: slug kimliğe düşer, fetched_at okuma anıdır.
    assert snapshot.slug == ARTICLE_ID
    assert snapshot.fetched_at.tzinfo is not None


def test_snapshot_hash_is_agent_side_compute_of_content() -> None:
    """Hash-tutarlılığı: endpoint hash'i agent hesabıyla tutarlı akar.

    Kabul kodu (backend) UTF-8 SHA-256 hex-lower yazar; ``compute_content_hash``
    aynı hesabı yapar — stale_snapshot guard'ı (qa.nodes._fetch_snapshot) bu
    alan üzerinden execute payload hash'i ile karşılaştırır.
    """

    snapshot = get_article(make_repo(make_payload()))

    assert snapshot.content_hash == compute_content_hash(snapshot.content)
    assert snapshot.content_hash == snapshot.content_hash.lower()


def test_http_repository_satisfies_content_repository_protocol() -> None:
    repo = make_repo(make_payload())
    assert isinstance(repo, ContentRepository)


# ------------------------------------------------------------------ arıza eşlemesi


def test_404_maps_to_not_found_without_retry() -> None:
    repo = make_repo({"error": "not published"}, status=404)

    try:
        get_article(repo)
    except PortError as error:
        assert error.code is AgentErrorCode.NOT_FOUND
        assert error.retryable is False
        assert ARTICLE_ID in error.message  # insan-okur TR mesaj makaleyi gösterir
    else:  # pragma: no cover
        raise AssertionError("HTTP 404 not_found'a eşlenmedi")


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(500, True), (429, True), (401, False)],
)
def test_http_error_maps_to_provider_error_with_retryable_flag(status: int, retryable: bool) -> None:
    repo = make_repo({"error": "x"}, status=status)

    try:
        get_article(repo)
    except PortError as error:
        assert error.code is AgentErrorCode.PROVIDER_ERROR
        assert error.retryable is retryable
    else:  # pragma: no cover
        raise AssertionError(f"HTTP {status} provider_error'a eşlenmedi")


def test_timeout_maps_to_timeout_error() -> None:
    repo = make_repo(httpx.ReadTimeout("read timed out"))

    try:
        get_article(repo)
    except PortError as error:
        assert error.code is AgentErrorCode.TIMEOUT
        assert error.retryable is True
    else:  # pragma: no cover
        raise AssertionError("zaman aşımı timeout'a eşlenmedi")


def test_network_failure_maps_to_retryable_provider_error() -> None:
    repo = make_repo(httpx.ConnectError("bağlantı kurulamadı"))

    try:
        get_article(repo)
    except PortError as error:
        assert error.code is AgentErrorCode.PROVIDER_ERROR
        assert error.retryable is True
    else:  # pragma: no cover
        raise AssertionError("ağ arızası provider_error'a eşlenmedi")


def test_contract_violating_body_maps_to_provider_error() -> None:
    """Eksik zorunlu alan sessiz varsayana düşmez; provider_error yükselir."""

    payload = make_payload()
    del payload["data"]["contentHash"]
    repo = make_repo(payload)

    try:
        get_article(repo)
    except PortError as error:
        assert error.code is AgentErrorCode.PROVIDER_ERROR
        assert "contentHash" in error.message
    else:  # pragma: no cover
        raise AssertionError("sözleşme ihlali provider_error'a eşlenmedi")


def test_non_object_body_maps_to_provider_error() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"[1, 2]"))
    )
    repo = HttpContentRepository(
        ContentRepositorySettings(base_url="http://content.test/api/v1", service_key="k"),
        client=client,
    )

    try:
        get_article(repo)
    except PortError as error:
        assert error.code is AgentErrorCode.PROVIDER_ERROR
    else:  # pragma: no cover
        raise AssertionError("nesne olmayan gövde provider_error'a eşlenmedi")


# ------------------------------------------------------------------ ortam fabrikası


def test_settings_from_env_empty_base_url_is_unconfigured() -> None:
    assert ContentRepositorySettings.from_env({}) is None
    assert ContentRepositorySettings.from_env({"AGENT_CONTENT_BASE_URL": ""}) is None
    assert ContentRepositorySettings.from_env({"AGENT_CONTENT_BASE_URL": "   "}) is None


def test_settings_missing_service_key_raises_config_error() -> None:
    with pytest.raises(PortError) as excinfo:
        ContentRepositorySettings.from_env({"AGENT_CONTENT_BASE_URL": "http://content.test/api/v1"})
    assert excinfo.value.code is AgentErrorCode.CONFIG_ERROR
    assert "AGENT_CONTENT_SERVICE_KEY" in excinfo.value.message


def test_settings_from_env_defaults_and_custom_timeout() -> None:
    settings = ContentRepositorySettings.from_env(
        {
            "AGENT_CONTENT_BASE_URL": "http://content.test/api/v1",
            "AGENT_CONTENT_SERVICE_KEY": "anahtar",
        }
    )
    assert settings is not None
    assert settings.base_url == "http://content.test/api/v1"
    assert settings.service_key == "anahtar"
    assert settings.timeout_seconds == 10.0  # default

    custom = ContentRepositorySettings.from_env(
        {
            "AGENT_CONTENT_BASE_URL": "http://content.test/api/v1",
            "AGENT_CONTENT_SERVICE_KEY": "anahtar",
            "AGENT_CONTENT_TIMEOUT_SECONDS": "2.5",
        }
    )
    assert custom is not None
    assert custom.timeout_seconds == 2.5


def test_build_content_repository_from_env_switch() -> None:
    # Base URL boş: None — çağıran MEVCUT davranışıyla sürer (birebir korunur).
    assert build_content_repository_from_env({}) is None

    repo = build_content_repository_from_env(
        {
            "AGENT_CONTENT_BASE_URL": "http://content.test/api/v1",
            "AGENT_CONTENT_SERVICE_KEY": "anahtar",
        }
    )
    assert isinstance(repo, HttpContentRepository)
    assert isinstance(repo, ContentRepository)


def test_failed_envelope_maps_to_provider_error() -> None:
    """success=false zarfı (AgentResponse FailureResult) provider_error'a eşlenir."""

    repo = make_repo({"success": False, "errors": ["beklenmeyen iç hata"]})

    try:
        get_article(repo)
    except PortError as error:
        assert error.code is AgentErrorCode.PROVIDER_ERROR
        assert error.retryable is True
    else:  # pragma: no cover
        raise AssertionError("başarısız zarf provider_error'a eşlenmedi")
