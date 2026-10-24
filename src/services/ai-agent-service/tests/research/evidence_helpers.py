"""Input records for deterministic claim and provenance validation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from agent_core.models import compute_content_hash

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

QUESTION = "asyncio kuyruk sınırı ve hata yönetimi için güncel öneriler nelerdir?"

CLAIM_1 = "asyncio kuyruk sınırı için önerilen üst değer 1000'dir."
CLAIM_2 = "Kuyruk dolunca QueueFull istisnası fırlar; hata yönetimi try/except ile yapılmalıdır."

#: Makale: iki iddialı cümle; başlıklar ve kod blokları iddia değildir.
ARTICLE_CONTENT = (
    "# asyncio Kuyruk Rehberi\n\n"
    "## Kuyruk sınırı\n\n"
    f"{CLAIM_1}\n\n"
    "## Hata yönetimi\n\n"
    f"{CLAIM_2}\n"
)

#: Input text for claim support and provenance checks.
GUIDE_TEXT = (
    "asyncio kuyruk sınırı için güncel öneri 1000 üst değeridir. "
    "Küçük kuyruklar bellek kullanımını düşürür."
)
#: İki cümle: ilki iddiayla sayısal çelişir (100 ≠ 1000).
CONFLICT_TEXT = "Önerilen kuyruk sınırı 100'dür. 1000 değeri aşırı beklemeye yol açabilir."
ERRORS_TEXT = (
    "Kuyruk dolunca QueueFull istisnası fırlar; hata yönetimi try/except bloğuyla yapılmalıdır."
)


def make_research_snapshot(**overrides: Any):
    from agent_core.models import ArticleSnapshot

    content = overrides.pop("content", ARTICLE_CONTENT)
    defaults: dict[str, Any] = dict(
        article_id="post-queue",
        slug="asyncio-kuyruk-rehberi",
        title="asyncio Kuyruk Rehberi",
        content=content,
        content_hash=compute_content_hash(content),
        article_revision=7,
        language="tr",
        fetched_at=NOW,
    )
    defaults.update(overrides)
    return ArticleSnapshot(**defaults)
