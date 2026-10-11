"""ExecutionContext ve destek modelleri.

Alan kümesi plan A1'den alınmıştır (``01-agent-gelistirme-plani.md:170``);
alan anlamı A0 §7 ve W0 §1.4 ile sabitlenmiştir. ``run_id`` backend'in
ürettiği ve sahipliğini doğruladığı tek yürütme kimliğidir; istemci yetki
kaynağı değildir. EC yalnız doğrulanmış ve gerekli alanları taşır (A0 §2).
"""

from __future__ import annotations

from pydantic import Field, NonNegativeInt, PositiveFloat, PositiveInt, model_validator

from .article import ArticleSnapshot, Revision
from .base import BusinessModel, HashHex, Identifier, LanguageCode, NonEmptyText, UtcDatetime
from .enums import ModePreference

__all__ = ["BudgetProfile", "ConversationTurn", "ExecutionContext"]


class ConversationTurn(BusinessModel):
    """Tamamlanmış konuşma geçmişinin tek turu."""

    role: str = Field(pattern=r"^(user|assistant)$")
    content: NonEmptyText
    created_at: UtcDatetime


class BudgetProfile(BusinessModel):
    """Sunucu tarafından izin verilen bütçe profili.

    A1 yalnız tipi tanımlar; alanları backend doldurur, bütçe denetimi A2'de
    BudgetStore üzerinden uygulanır (plan A2; W0 §6.5).
    """

    name: Identifier
    max_model_calls: PositiveInt
    max_total_tokens: PositiveInt
    max_tool_calls: NonNegativeInt = 0
    max_web_search_calls: NonNegativeInt = 0
    max_duration_seconds: PositiveFloat


class ExecutionContext(BusinessModel):
    """Agent'ın gördüğü tek girdi; transport dönüşümü içermez (W0 §1)."""

    run_id: Identifier
    conversation_id: Identifier
    question: NonEmptyText = Field(max_length=8000)
    language: LanguageCode
    mode_preference: ModePreference = ModePreference.AUTO

    #: İçerik referansı (K7: içerik gömülmezken bu üçlü referanstır).
    article_id: Identifier | None = None
    article_revision: Revision | None = None
    article_content_hash: HashHex | None = None

    #: İçerik referansının dolu hali: doğrulanmış makale snapshot'ı.
    article_snapshot: ArticleSnapshot | None = None

    selected_text: str | None = Field(default=None, max_length=20000)
    conversation_history: list[ConversationTurn] = []
    budget_profile: BudgetProfile

    @model_validator(mode="after")
    def _snapshot_binding(self) -> "ExecutionContext":
        """Snapshot verildiyse içerik referansı alanları zorunlu ve tutarlı olmalıdır.

        İçerik hash'inin snapshot içeriğine uygunluğu burada değil, giriş
        noktasında yeniden hesaplanarak denetlenir (stale_snapshot sözleşmesi,
        A0 §7.2); burada yalnız kimlik tutarlılığı reddedilir.
        """

        if self.article_snapshot is None:
            return self
        missing = [
            field
            for field in ("article_id", "article_revision", "article_content_hash")
            if getattr(self, field) is None
        ]
        if missing:
            raise ValueError(f"article_snapshot verildiği halde eksik alanlar: {', '.join(missing)}")
        if self.article_snapshot.article_id != self.article_id:
            raise ValueError("article_snapshot.article_id, ExecutionContext.article_id ile uyuşmuyor")
        if self.article_snapshot.article_revision != self.article_revision:
            raise ValueError("article_snapshot.article_revision, ExecutionContext.article_revision ile uyuşmuyor")
        return self
