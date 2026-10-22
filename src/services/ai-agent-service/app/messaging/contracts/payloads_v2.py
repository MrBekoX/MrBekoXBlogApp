"""v2 run mesajı payload modelleri (``src/contracts/agent/v2/payloads/*.schema.json`` aynası).

v2 = v1'in run kapsamlı 13 türü + konu/niyet/profil sürümü alanları (karar kaydı
K3; üretici ``src/contracts/agent/_generate_v2.py``). ``content.*`` türleri yalnız
v1'dedir. v1 modelleri (``payloads.py``) DEĞİŞMEZ: v2 modelleri onları miras alır
ve yalnız v2 farklarını ekler; v1 ile aynı şekildeki türler ince alt sınıftır
(sürüm ``isinstance`` ile ayırt edilebilsin diye).

Kategori sınıflandırması (.NET doğrulayıcıyla aynı):

- Şemanın ``if/then`` + ``const``/``not`` ile ifade ettiği kurallar (who_am_i +
  makale bağlamı, profile niyeti + kapsam/web/citation türü/öneri) model
  doğrulayıcısında ``ValueError`` → ``wrong_type``.
- Biçim kuralları (profile ``url`` kalıbı ve ``/about#{section_id}`` eşliği,
  ``source_id`` biçimi, citation sürümü == payload ``profile_snapshot``)
  ``bad_format_error`` → ``bad_format``.
- Eksik-alan çapraz kuralları (who_am_i ve profile niyetinde ``profile_snapshot``
  zorunluluğu) ``validator._check_missing_rules`` içindedir → ``missing_field``.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .enums import ConversationTopic, RunIntent, SourceScope
from .formats import (
    HashHex,
    Identifier,
    ProfileIdString,
    SectionIdString,
    StrictInt,
    UtcIsoString,
    bad_format_error,
)
from .payloads import (
    AgentActionProposedV1,
    AgentActionResultV1,
    AgentCancellationRequestedV1,
    AgentExecutionRequestedV1,
    AgentResumeRequestedV1,
    AgentRunAcceptedV1,
    AgentRunCancelledV1,
    AgentRunCompletedV1,
    AgentRunFailedV1,
    AgentRunModeSelectedV1,
    AgentRunNeedsInputV1,
    AgentRunPartiallyCompletedV1,
    AgentRunProgressedV1,
    TransportModel,
)

__all__ = [
    "AgentActionProposedV2",
    "AgentActionResultV2",
    "AgentCancellationRequestedV2",
    "AgentExecutionRequestedV2",
    "AgentProfileSnapshotRef",
    "AgentResumeRequestedV2",
    "AgentRunAcceptedV2",
    "AgentRunCancelledV2",
    "AgentRunCompletedV2",
    "AgentRunFailedV2",
    "AgentRunModeSelectedV2",
    "AgentRunNeedsInputV2",
    "AgentRunPartiallyCompletedV2",
    "AgentRunProgressedV2",
    "AgentSourceReferenceV2",
    "PROFILE_URL_PREFIX",
    "expected_profile_source_id",
    "expected_profile_url",
]

#: Profil kaynağının tek geçerli bağlantı biçimi: ``/about#{section_id}`` (canonical metadata'dan).
PROFILE_URL_PREFIX = "/about#"
_PROFILE_URL_RE = re.compile(r"^/about#[a-z0-9][a-z0-9-]{0,127}$")


class AgentProfileSnapshotRef(TransportModel):
    """Gövdesiz profil sürüm referansı (common ``profile_snapshot_ref``); A1 ``ProfileSnapshotRef`` aynası."""

    profile_id: ProfileIdString
    revision: StrictInt = Field(ge=1)
    content_hash: HashHex

    def same_as(self, other: "AgentProfileSnapshotRef | None") -> bool:
        return (
            other is not None
            and self.profile_id == other.profile_id
            and self.revision == other.revision
            and self.content_hash == other.content_hash
        )


def expected_profile_source_id(
    profile_id: str, revision: int, content_hash: str, section_id: str, chunk_index: int
) -> str:
    """``profile:{profile_id}:{revision}:{content_hash}:{section_id}:{chunk_index}`` (K3 çapraz kural)."""

    return f"profile:{profile_id}:{revision}:{content_hash}:{section_id}:{chunk_index}"


def expected_profile_url(section_id: str) -> str:
    return f"{PROFILE_URL_PREFIX}{section_id}"


class AgentSourceReferenceV2(TransportModel):
    """v2 ``source_reference``: article | web | profile; tür bazlı alan ayrımı zorunludur."""

    kind: Literal["article", "web", "profile"]
    source_id: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    title: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    article_id: Identifier | None = None
    article_revision: StrictInt | None = Field(default=None, ge=0)
    chunk_index: StrictInt | None = Field(default=None, ge=0)
    url: Annotated[str, Field(min_length=1, max_length=2048)] | None = None
    accessed_at: UtcIsoString | None = None
    profile_id: ProfileIdString | None = None
    profile_revision: StrictInt | None = Field(default=None, ge=1)
    profile_content_hash: HashHex | None = None
    section_id: SectionIdString | None = None

    @property
    def profile_snapshot(self) -> AgentProfileSnapshotRef | None:
        if self.kind != "profile":
            return None
        return AgentProfileSnapshotRef(
            profile_id=self.profile_id,  # type: ignore[arg-type]
            revision=self.profile_revision,  # type: ignore[arg-type]
            content_hash=self.profile_content_hash,  # type: ignore[arg-type]
        )

    @model_validator(mode="after")
    def _kind_specific_fields(self) -> "AgentSourceReferenceV2":
        profile_fields = [
            f
            for f in ("profile_id", "profile_revision", "profile_content_hash", "section_id")
            if getattr(self, f) is not None
        ]
        if self.kind == "article":
            missing = [f for f in ("article_id", "article_revision", "chunk_index") if getattr(self, f) is None]
            if missing:
                raise ValueError(f"article kaynağı için zorunlu eksik alanlar: {', '.join(missing)}")
            if self.url is not None or self.accessed_at is not None:
                raise ValueError("article kaynağı url/accessed_at taşımaz")
            if profile_fields:
                raise ValueError(f"article kaynağı profil alanları taşımaz: {', '.join(profile_fields)}")
            return self
        if self.kind == "web":
            if self.url is None or self.accessed_at is None:
                raise ValueError("web kaynağı url ve accessed_at zorunludur")
            present = [f for f in ("article_id", "article_revision", "chunk_index") if getattr(self, f) is not None]
            if present:
                raise ValueError(f"web kaynağı makale alanları taşımaz: {', '.join(present)}")
            if profile_fields:
                raise ValueError(f"web kaynağı profil alanları taşımaz: {', '.join(profile_fields)}")
            return self
        return self._validate_profile()

    def _validate_profile(self) -> "AgentSourceReferenceV2":
        missing = [
            f
            for f in (
                "source_id",
                "title",
                "profile_id",
                "profile_revision",
                "profile_content_hash",
                "section_id",
                "chunk_index",
                "url",
            )
            if getattr(self, f) is None
        ]
        if missing:
            raise ValueError(f"profile kaynağı için zorunlu eksik alanlar: {', '.join(missing)}")
        forbidden = [f for f in ("article_id", "article_revision", "accessed_at") if getattr(self, f) is not None]
        if forbidden:
            raise ValueError(f"profile kaynağı makale/web alanları taşımaz: {', '.join(forbidden)}")
        # Biçim kuralları: URL modelden alınmaz; canonical metadata'dan üretilen
        # /about#{section_id} dışında bir değer (dış alan adı dahil) bad_format'tır.
        assert self.url is not None and self.section_id is not None
        if _PROFILE_URL_RE.match(self.url) is None or self.url != expected_profile_url(self.section_id):
            raise bad_format_error("profile url yalnız /about#{section_id} olabilir")
        expected = expected_profile_source_id(
            self.profile_id,  # type: ignore[arg-type]
            self.profile_revision,  # type: ignore[arg-type]
            self.profile_content_hash,  # type: ignore[arg-type]
            self.section_id,
            self.chunk_index,  # type: ignore[arg-type]
        )
        if self.source_id != expected:
            raise bad_format_error(
                "profile source_id 'profile:{profile_id}:{revision}:{content_hash}:{section_id}:{chunk_index}' "
                "biçiminde ve kaynak alanlarıyla tutarlı olmalıdır"
            )
        return self


def _check_profile_citations_bound(
    citations: list[AgentSourceReferenceV2], snapshot: AgentProfileSnapshotRef | None
) -> None:
    """Profile citation sürümü payload ``profile_snapshot`` ile aynı olmalıdır (bad_format).

    Snapshot hiç yoksa kural burada atlanır: profile niyetinde eksiklik
    ``missing_field`` (doğrulayıcı), diğer niyetlerde bağsız profile kaynağı
    ``bad_format`` olarak doğrulayıcının çapraz kuralında sınıflandırılır.
    """

    if snapshot is None:
        return
    for citation in citations:
        if citation.kind == "profile" and not snapshot.same_as(citation.profile_snapshot):
            raise bad_format_error("profile citation pinlenmiş profile_snapshot ile uyuşmuyor")


def _check_profile_intent(
    run_intent: RunIntent,
    source_scope: SourceScope,
    citations: list[AgentSourceReferenceV2],
    *,
    has_action_proposal: bool = False,
) -> None:
    """run_intent=profile → source_scope=profile, citation'lar yalnız profile, öneri yok (wrong_type)."""

    if run_intent is not RunIntent.PROFILE:
        return
    if source_scope is not SourceScope.PROFILE:
        raise ValueError("run_intent=profile sonucu yalnız source_scope=profile taşıyabilir")
    foreign = sorted({c.kind for c in citations if c.kind != "profile"})
    if foreign:
        raise ValueError(f"run_intent=profile sonucu profil dışı kaynak taşıyamaz: {', '.join(foreign)}")
    if has_action_proposal:
        raise ValueError("run_intent=profile sonucu içerik önerisi (action_proposal) taşıyamaz")


# --- Backend -> Agent: komutlar ---


class AgentExecutionRequestedV2(AgentExecutionRequestedV1):
    """v2 execute: ``conversation_topic`` zorunlu; who_am_i makale bağlamı/selected_text taşımaz.

    who_am_i'de ``profile_snapshot`` zorunluluğu ``missing_field`` kategorisinde
    doğrulayıcı tarafından uygulanır. ``auto`` konusu da backend kabulünde pinlenen
    snapshot'ı taşıyabilir (AUTO→PROFILE yalnız bu sürüme karşı yürür).
    """

    conversation_topic: ConversationTopic
    profile_snapshot: AgentProfileSnapshotRef | None = None

    @model_validator(mode="after")
    def _who_am_i_binding(self) -> "AgentExecutionRequestedV2":
        if self.conversation_topic is ConversationTopic.WHO_AM_I:
            present = [
                f
                for f in ("article_id", "article_revision", "article_content_hash", "selected_text")
                if getattr(self, f) is not None
            ]
            if present:
                raise ValueError(f"who_am_i konusu makale bağlamı taşımaz: {', '.join(present)}")
        return self


class AgentCancellationRequestedV2(AgentCancellationRequestedV1):
    """v2 iptal isteği (v1 ile aynı şekil)."""


class AgentResumeRequestedV2(AgentResumeRequestedV1):
    """v2 devam isteği (v1 ile aynı şekil)."""


class AgentActionResultV2(AgentActionResultV1):
    """v2 eylem sonucu (v1 ile aynı şekil)."""


# --- Agent -> Backend: run olayları ---


class AgentRunAcceptedV2(AgentRunAcceptedV1):
    """v2 kabul olayı (v1 ile aynı şekil)."""


class AgentRunModeSelectedV2(AgentRunModeSelectedV1):
    """v2 router kararı: etkin niyet + kapsam zorunlu; profile niyeti web'siz ve profil kapsamlıdır."""

    run_intent: RunIntent
    source_scope: SourceScope
    profile_snapshot: AgentProfileSnapshotRef | None = None

    @model_validator(mode="after")
    def _profile_intent_rules(self) -> "AgentRunModeSelectedV2":
        if self.run_intent is RunIntent.PROFILE:
            if self.source_scope is not SourceScope.PROFILE:
                raise ValueError("run_intent=profile kararı yalnız source_scope=profile taşıyabilir")
            if self.requires_web_search:
                raise ValueError("run_intent=profile kararı web araması gerektiremez")
        return self


class AgentRunProgressedV2(AgentRunProgressedV1):
    """v2 ilerleme olayı (v1 ile aynı şekil)."""


class AgentRunNeedsInputV2(AgentRunNeedsInputV1):
    """v2 girdi bekleme olayı (v1 ile aynı şekil)."""


class AgentRunCompletedV2(AgentRunCompletedV1):
    """v2 terminal başarı: ``run_intent`` zorunlu; profile kaynak türü ve sürüm bağı."""

    citations: list[AgentSourceReferenceV2] = []  # type: ignore[assignment]
    run_intent: RunIntent
    profile_snapshot: AgentProfileSnapshotRef | None = None

    @model_validator(mode="after")
    def _profile_rules(self) -> "AgentRunCompletedV2":
        _check_profile_intent(
            self.run_intent,
            self.source_scope,
            self.citations,
            has_action_proposal=self.action_proposal is not None,
        )
        _check_profile_citations_bound(self.citations, self.profile_snapshot)
        return self


class AgentRunPartiallyCompletedV2(AgentRunPartiallyCompletedV1):
    """v2 terminal kısmi başarı: completed ile aynı profil kuralları (öneri alanı yoktur)."""

    citations: list[AgentSourceReferenceV2] = []  # type: ignore[assignment]
    run_intent: RunIntent
    profile_snapshot: AgentProfileSnapshotRef | None = None

    @model_validator(mode="after")
    def _profile_rules(self) -> "AgentRunPartiallyCompletedV2":
        _check_profile_intent(self.run_intent, self.source_scope, self.citations)
        _check_profile_citations_bound(self.citations, self.profile_snapshot)
        return self


class AgentRunFailedV2(AgentRunFailedV1):
    """v2 terminal başarısızlık: ``run_intent`` ve ``profile_snapshot`` opsiyoneldir."""

    run_intent: RunIntent | None = None
    profile_snapshot: AgentProfileSnapshotRef | None = None


class AgentRunCancelledV2(AgentRunCancelledV1):
    """v2 iptal terminali (v1 ile aynı şekil)."""


class AgentActionProposedV2(AgentActionProposedV1):
    """v2 içerik önerisi (v1 ile aynı şekil)."""
