"""Tür bazlı payload modelleri (plan satır 202-217 listesinin tamamı).

Alan adları JSON sözleşmesindeki snake_case adlardır; kısıtlar
``src/contracts/agent/v1/payloads/*.schema.json`` dosyalarının aynasıdır.
Model içi çapraz kurallar (ör. answer/report ayrıklığı) ``ValueError`` ile
reddedilir ve ``wrong_type`` kategorisine eşlenir; zarf bağlantısı gerektiren
kurallar (usage.run_id == zarf.run_id) parse_envelope içinde uygulanır.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from .enums import AgentErrorCode, AgentMode, ModePreference, ProgressKind, SourceScope
from .formats import HashHex, Identifier, LanguageCode, StrictBool, StrictFloat, StrictInt, UtcIsoString

__all__ = [
    "AgentActionProposalContent",
    "AgentContentReference",
    "AgentConversationTurn",
    "AgentSourceReference",
    "AgentUsageRecord",
    "AgentActionProposedV1",
    "AgentActionResultV1",
    "AgentCancellationRequestedV1",
    "AgentExecutionRequestedV1",
    "AgentPayload",
    "AgentRunAcceptedV1",
    "AgentRunCancelledV1",
    "AgentRunCompletedV1",
    "AgentRunEventPayload",
    "AgentRunFailedV1",
    "AgentRunModeSelectedV1",
    "AgentRunNeedsInputV1",
    "AgentRunPartiallyCompletedV1",
    "AgentRunProgressedV1",
    "AgentResumeRequestedV1",
    "ArticleContentChangedV1",
    "ContentSnapshotBatchV1",
    "ContentSnapshotCompletedV1",
    "ProfileContentChangedV1",
    "ProjectContentChangedV1",
    "TransportModel",
]

QuestionText = Annotated[str, Field(min_length=1, max_length=20000)]


class TransportModel(BaseModel):
    """Tüm transport modellerinin temeli: bilinmeyen alan reddedilir, null taşınmaz.

    JSON sözleşmesi additionalProperties: false'tur ve 'null taşımak yerine alan
    çıkarın' kuralını uygular; açık null girdi ``wrong_type`` kategorisiyle reddedilir.
    """

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "TransportModel":
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"'{name}' alanı null taşınamaz; alan çıkarılmalıdır")
        return self


class AgentConversationTurn(TransportModel):
    """A1 ConversationTurn'un taşıma karşılığı."""

    role: Literal["user", "assistant"]
    content: QuestionText
    created_at: UtcIsoString


class AgentUsageRecord(TransportModel):
    """A1 UsageRecord'un taşıma karşılığı; run_id zarf run_id ile uyuşmak zorundadır."""

    run_id: Identifier
    model_calls: StrictInt = Field(default=0, ge=0)
    prompt_tokens: StrictInt = Field(default=0, ge=0)
    completion_tokens: StrictInt = Field(default=0, ge=0)
    total_tokens: StrictInt = Field(default=0, ge=0)
    tool_calls: StrictInt = Field(default=0, ge=0)
    web_search_calls: StrictInt = Field(default=0, ge=0)
    duration_seconds: StrictFloat = Field(default=0.0, ge=0.0)
    recorded_at: UtcIsoString


class AgentSourceReference(TransportModel):
    """A1 SourceReference'un taşıma karşılığı; kind'a göre alan ayrımı zorunludur."""

    kind: Literal["article", "web"]
    source_id: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    title: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    article_id: Identifier | None = None
    article_revision: StrictInt | None = Field(default=None, ge=0)
    chunk_index: StrictInt | None = Field(default=None, ge=0)
    url: Annotated[str, Field(min_length=1, max_length=2048)] | None = None
    accessed_at: UtcIsoString | None = None

    @model_validator(mode="after")
    def _kind_specific_fields(self) -> "AgentSourceReference":
        if self.kind == "article":
            missing = [f for f in ("article_id", "article_revision", "chunk_index") if getattr(self, f) is None]
            if missing:
                raise ValueError(f"article kaynağı için zorunlu eksik alanlar: {', '.join(missing)}")
            if self.url is not None or self.accessed_at is not None:
                raise ValueError("article kaynağı url/accessed_at taşımaz")
        else:
            if self.url is None or self.accessed_at is None:
                raise ValueError("web kaynağı url ve accessed_at zorunludur")
            present = [f for f in ("article_id", "article_revision", "chunk_index") if getattr(self, f) is not None]
            if present:
                raise ValueError(f"web kaynağı makale alanları taşımaz: {', '.join(present)}")
        return self


class AgentActionProposalContent(TransportModel):
    """A1 ActionProposal'un taşıma karşılığı; kayıt yalnız açık gönderim onayıyla yapılar."""

    run_id: Identifier
    proposal_id: Identifier
    article_id: Identifier
    article_revision: StrictInt = Field(ge=0)
    base_content_hash: HashHex
    summary: Annotated[str, Field(min_length=1, max_length=8000)]
    proposed_content: QuestionText
    created_at: UtcIsoString


class AgentContentReference(TransportModel):
    """İçerik senkronizasyonu toplu referans kaydı (K7: içerik gömülmez)."""

    article_id: Identifier
    article_revision: StrictInt = Field(ge=0)
    content_hash: HashHex


# --- Backend -> Agent: komutlar ---


class AgentExecutionRequestedV1(TransportModel):
    """Execution isteği (plan satır 235). UserRef backend kimliği doğruladıktan sonra
    ekler; bu alanın varlığı tek başına yetki kanıtı değildir (plan satır 198)."""

    user_ref: Identifier
    question: Annotated[str, Field(min_length=1, max_length=8000)]
    language: LanguageCode
    mode_preference: ModePreference
    budget_profile: Identifier
    article_id: Identifier | None = None
    article_revision: StrictInt | None = Field(default=None, ge=0)
    article_content_hash: HashHex | None = None
    context_snapshot_reference: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    selected_text: QuestionText | None = None
    conversation_history: list[AgentConversationTurn] = []

    @model_validator(mode="after")
    def _article_reference_trio(self) -> "AgentExecutionRequestedV1":
        any_present = any(
            getattr(self, f) is not None
            for f in ("article_id", "article_revision", "article_content_hash")
        )
        all_present = all(
            getattr(self, f) is not None
            for f in ("article_id", "article_revision", "article_content_hash")
        )
        if any_present and not all_present:
            raise ValueError("makale referansı article_id/article_revision/article_content_hash üçlüsü halinde taşınır")
        return self


class AgentCancellationRequestedV1(TransportModel):
    """İptal isteği; hedef run zarfın run_id alanından gelir."""

    reason: Annotated[str, Field(min_length=1, max_length=2000)] | None = None


class AgentResumeRequestedV1(TransportModel):
    """Kesinti sonrası devam isteği; checkpoint referansı zorunludur."""

    checkpoint_reference: Annotated[str, Field(min_length=1, max_length=512)]
    user_ref: Identifier


class AgentActionResultV1(TransportModel):
    """Backend'in ActionProposal kararı: kabul veya gerekçeli ret."""

    proposal_id: Identifier
    outcome: Literal["accepted", "rejected"]
    reason: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    applied_article_revision: StrictInt | None = Field(default=None, ge=0)
    validated_at: UtcIsoString


# --- Agent -> Backend: run olayları (ortak sıra alanları) ---


class AgentRunEventPayload(TransportModel):
    """Run olaylarının ortak alanları: event_sequence run başına monoton artar;
    execution_attempt agent yürütme denemesidir ve zarf delivery_attempt
    (transport tekrar sayacı) ile bilinçli olarak ayrıdır (plan satır 237)."""

    event_sequence: StrictInt = Field(ge=0)
    execution_attempt: StrictInt | None = Field(default=None, ge=1)
    fencing_token: Annotated[str, Field(min_length=1, max_length=128)] | None = None


class AgentRunAcceptedV1(AgentRunEventPayload):
    """Intake işi kalıcı kabul etti."""

    accepted_at: UtcIsoString


class AgentRunModeSelectedV1(AgentRunEventPayload):
    """Router kararı (A1 RouteDecision); web bayrağı yalnız deep_research'te true olabilir."""

    selected_mode: AgentMode
    requires_web_search: StrictBool
    reason: Annotated[str, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def _web_only_for_research(self) -> "AgentRunModeSelectedV1":
        if self.requires_web_search and self.selected_mode is not AgentMode.DEEP_RESEARCH:
            raise ValueError("requires_web_search yalnız deep_research modunda true olabilir")
        return self


class AgentRunProgressedV1(AgentRunEventPayload):
    """DomainProgress olayının taşıma karşılığı (W0 Ç6); terminal sonuç değildir."""

    kind: ProgressKind
    message: Annotated[str, Field(min_length=1, max_length=2000)]
    detail: dict[str, str] = {}


class AgentRunNeedsInputV1(AgentRunEventPayload):
    """Kullanıcı girdisi bekleniyor; en az bir açık soru zorunludur."""

    unresolved_questions: list[QuestionText] = Field(min_length=1)
    usage: AgentUsageRecord | None = None


class AgentRunCompletedV1(AgentRunEventPayload):
    """Terminal başarı: answer veya report tam olarak biri zorunludur."""

    selected_mode: AgentMode
    answer: Annotated[str, Field(min_length=1, max_length=200000)] | None = None
    report: Annotated[str, Field(min_length=1, max_length=200000)] | None = None
    citations: list[AgentSourceReference] = []
    source_scope: SourceScope
    unresolved_questions: list[QuestionText] = []
    usage: AgentUsageRecord
    action_proposal: AgentActionProposalContent | None = None

    @model_validator(mode="after")
    def _exactly_one_of_answer_report(self) -> "AgentRunCompletedV1":
        if self.answer is not None and self.report is not None:
            raise ValueError("answer ve report aynı anda dolu olamaz")
        return self


class AgentRunPartiallyCompletedV1(AgentRunEventPayload):
    """Terminal kısmi başarı: answer veya report zorunlu, ikisi aynı anda dolu olamaz."""

    selected_mode: AgentMode
    answer: Annotated[str, Field(min_length=1, max_length=200000)] | None = None
    report: Annotated[str, Field(min_length=1, max_length=200000)] | None = None
    citations: list[AgentSourceReference] = []
    source_scope: SourceScope
    unresolved_questions: list[QuestionText] = []
    usage: AgentUsageRecord

    @model_validator(mode="after")
    def _exactly_one_of_answer_report(self) -> "AgentRunPartiallyCompletedV1":
        if self.answer is not None and self.report is not None:
            raise ValueError("answer ve report aynı anda dolu olamaz")
        return self


class AgentRunFailedV1(AgentRunEventPayload):
    """Terminal başarısızlık: error_code ortak kümeden bir koddur."""

    error_code: AgentErrorCode
    error_message: Annotated[str, Field(min_length=1, max_length=4000)] | None = None
    selected_mode: AgentMode | None = None
    usage: AgentUsageRecord | None = None


class AgentRunCancelledV1(AgentRunEventPayload):
    """Terminal iptal bildirimi."""

    reason: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    usage: AgentUsageRecord | None = None


class AgentActionProposedV1(AgentRunEventPayload):
    """Backend'e sunulan içerik önerisi; run_id zarf run_id ile uyuşmak zorundadır."""

    run_id: Identifier
    proposal_id: Identifier
    article_id: Identifier
    article_revision: StrictInt = Field(ge=0)
    base_content_hash: HashHex
    summary: Annotated[str, Field(min_length=1, max_length=8000)]
    proposed_content: QuestionText
    created_at: UtcIsoString


# --- Backend -> Agent: içerik olayları ---


class ArticleContentChangedV1(TransportModel):
    """Makale içeriği değişti; içerik gömülmez, hash referansı taşınır (K7)."""

    article_id: Identifier
    article_revision: StrictInt = Field(ge=0)
    action: Literal["updated", "unpublished"]
    content_hash: HashHex | None = None
    language: LanguageCode | None = None
    title: Annotated[str, Field(min_length=1, max_length=512)] | None = None


class ContentSnapshotBatchV1(TransportModel):
    """Başlangıç içerik senkronizasyonu toplu referans paketi."""

    sync_id: Identifier
    batch_index: StrictInt = Field(ge=0)
    total_batches: StrictInt = Field(ge=1)
    items: list[AgentContentReference] = Field(min_length=1)

    @model_validator(mode="after")
    def _batch_index_in_range(self) -> "ContentSnapshotBatchV1":
        if self.batch_index >= self.total_batches:
            raise ValueError("batch_index, total_batches değerinden küçük olmalıdır")
        return self


class ContentSnapshotCompletedV1(TransportModel):
    """İçerik senkronizasyonu tamamlandı."""

    sync_id: Identifier
    item_count: StrictInt = Field(ge=0)


class ProfileContentChangedV1(TransportModel):
    """Profil tanıtım içeriği değişti."""

    profile_revision: StrictInt = Field(ge=0)
    content_hash: HashHex
    context_snapshot_reference: Annotated[str, Field(min_length=1, max_length=512)] | None = None


class ProjectContentChangedV1(TransportModel):
    """Proje rehberi içeriği değişti."""

    project_id: Identifier
    project_revision: StrictInt = Field(ge=0)
    content_hash: HashHex
    context_snapshot_reference: Annotated[str, Field(min_length=1, max_length=512)] | None = None


#: 18 payload modelinin birlik tipi; registry payload_model alanları bu kümedendir.
AgentPayload = (
    AgentExecutionRequestedV1
    | AgentCancellationRequestedV1
    | AgentResumeRequestedV1
    | AgentActionResultV1
    | AgentRunAcceptedV1
    | AgentRunModeSelectedV1
    | AgentRunProgressedV1
    | AgentRunNeedsInputV1
    | AgentRunCompletedV1
    | AgentRunPartiallyCompletedV1
    | AgentRunFailedV1
    | AgentRunCancelledV1
    | AgentActionProposedV1
    | ArticleContentChangedV1
    | ContentSnapshotBatchV1
    | ContentSnapshotCompletedV1
    | ProfileContentChangedV1
    | ProjectContentChangedV1
)
