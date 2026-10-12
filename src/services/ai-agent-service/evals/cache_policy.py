"""Cevap önbelleği anahtar sözleşmesi (plan A10: "Önbellek anahtarlarına
içerik hash'i, dil, soru kapsamı ve ilgili yapılandırma sürümlerini dahil et.
Konuşmaya bağlı cevapları uygunsuz ortak önbelleğe koyma.")

Bu modül kuralın REFERANS GERÇEKLEŞTİRİMİDİR ve koşucu tarafından ölçülür:

- ``answer_cache_key``: (makale içerik hash'i, dil, soru kapsamı, yapılandırma
  parmak izi) demetinin SHA-256'sı. Hangi bileşik eksilirse önbellek o
  boyutta yanlış paylaşır — ölçüm bunu denetler.
- ``is_shared_cache_eligible``: konuşma geçmişi veya seçili metin taşıyan
  sorular konuşmaya/scopeta bağlıdır; ORTAK önbelleğe girmez.
- ``config_fingerprint``: yapılandırma sürümlerinin (şema sürümleri, akış
  yapılandırması, gömme modeli, prompt sürümü) demetlenmiş parmak izi.

Mevcut üretim önbellekleriyle ilişki (dokümantasyon sözleşmesi):
``InMemoryContentIndex.search`` sorgu önbelleği anahtarını
``(katlanmış sorgu, filtreler[dil dâhil], top_k, embedding model_id)``
olarak kurar (``agent_core/content/index.py:354`` ve
``agent_core/content/retrieval.py:51``); bu ANAHTAR-SEVİYESİ anahtar dil
ve model sürümünü taşır, içerik hash'i ise indekslemenin
``content_hash`` idempotentiyle makale bazında ayrışır ve makale
kaldırıldığında önbellek girişi çözülemez hale gelerek yeniden hesap
tetikler. Cevap-seviyesi önbellek (haberleşme adaptörü katmanında
konumlanır) bu modülün kuralını kullanmak zorundadır; koşucu bu kuralı
ölçerek A10 madde 5'in denetlenebilir karşılığını verir.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agent_core.models import ExecutionContext

__all__ = [
    "ANSWER_CACHE_KEY_VERSION",
    "PROMPT_TEMPLATE_VERSION",
    "answer_cache_key",
    "config_fingerprint",
    "is_shared_cache_eligible",
    "question_scope",
]

#: Anahtar sözleşmesinin sürümü; sözleşme değişince eski girişler çöpe düşer.
ANSWER_CACHE_KEY_VERSION = "answer-cache-key-v1"

#: Yönlendirme/üretim prompt sözleşmesinin sürümü (metin değişince artar).
PROMPT_TEMPLATE_VERSION = "eval-prompt-v1"


def question_scope(context: ExecutionContext) -> str:
    """Soru kapsamı: genel / makale / seçim.

    - ``selected``: seçili metinle sınırli açıklama (kapsam seçime bağlı).
    - ``article``: makale bağlamlı soru (makale hash'i anahtardadır).
    - ``general``: makalesiz genel soru.
    """

    if context.selected_text is not None:
        return "selected"
    if context.article_id is not None or context.article_snapshot is not None:
        return "article"
    return "general"


def is_shared_cache_eligible(context: ExecutionContext) -> bool:
    """Konuşmaya/scopeta bağlı cevaplar ortak önbelleğe GİRMEZ.

    - ``conversation_history`` doluysa cevap önceki turlara bağlıdır: ortak
      önbellek ANLAMSIZDIR (aynı anahtar farklı konuşmada farklı anlama gelir).
    - ``selected_text`` doluysa kapsam kullanıcı seçimine bağlıdır: ortak
      önbellek yanlış paylaşım üretir.
    """

    return not (context.conversation_history or context.selected_text is not None)


def config_fingerprint(
    *,
    embedding_model_id: str,
    qa_config: Any = None,
    analysis_config: Any = None,
    research_config: Any = None,
    budget_profile_name: str = "default",
    checkpoint_schema_version: int = 1,
    state_schema_version: int = 1,
    prompt_template_version: str = PROMPT_TEMPLATE_VERSION,
) -> str:
    """Yapılandırma sürümlerini deterministik kısa parmak izine sıkıştırır.

    Hangi yapılandırmanın anahtara girdiği açıkça listelenir: akış
    yapılandırmalarının tam JSON'u, gömme modeli, bütçe profili adı, zarf/state
    şema sürümleri ve prompt sözleşme sürümü.
    """
    from agent_core.checkpoint.models import CHECKPOINT_SCHEMA_VERSION
    from agent_core.state.state import STATE_SCHEMA_VERSION

    parts: list[str] = [
        f"embedding={embedding_model_id}",
        f"qa={qa_config.model_dump_json() if qa_config is not None else '-'}",
        f"analysis={analysis_config.model_dump_json() if analysis_config is not None else '-'}",
        f"research={research_config.model_dump_json() if research_config is not None else '-'}",
        f"budget={budget_profile_name}",
        f"checkpoint_schema={checkpoint_schema_version or CHECKPOINT_SCHEMA_VERSION}",
        f"state_schema={state_schema_version or STATE_SCHEMA_VERSION}",
        f"prompt={prompt_template_version}",
        f"key_contract={ANSWER_CACHE_KEY_VERSION}",
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]


def answer_cache_key(
    *,
    content_hash: str,
    language: str,
    scope: str,
    config_fingerprint_hex: str,
) -> str:
    """Cevap önbelleği anahtarı: içerik hash'i + dil + kapsam + yapılandırma.

    Dönen değer SHA-256 hex'idir; bileşenler tam hex'e gömülür (çakışma
    teşhisi için ``cache_key_components`` kullanılabilir).
    """
    canonical = "\n".join(
        [
            ANSWER_CACHE_KEY_VERSION,
            f"content={content_hash}",
            f"lang={language.casefold()}",
            f"scope={scope}",
            f"config={config_fingerprint_hex}",
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_key_components(context: ExecutionContext, config_fingerprint_hex: str) -> dict[str, str]:
    """Anahtarın bileşenlerini teşhis/raporlama için ayrı döndürür."""
    snapshot = context.article_snapshot
    return {
        "content_hash": snapshot.content_hash if snapshot is not None else (context.article_content_hash or "-"),
        "language": context.language,
        "scope": question_scope(context),
        "config": config_fingerprint_hex,
    }
