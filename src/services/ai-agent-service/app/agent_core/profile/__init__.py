"""Who am I: canonical profil kaynağı + profil RAG (karar K2/K5).

Sorumluluk ayrımı:

- ``source``: canonical kaynak okuyucu/doğrulayıcı (``ProfileDocument``,
  ``ProfileSourceError``, ``resolve_profile_dir``, ``load_profile_source``).
- ``chunking``: deterministik başlık/paragraf/madde/FAQ bölümleme (``ProfileChunk``).
- ``repository``: gerçek dosya adaptörü ``CanonicalProfileRepository``
  (``ProfileKnowledgeRepository`` + legacy ``ProfileRepository``).
- ``detection``: sahip/ziyaretçi-kimliği/dil sinyalleri (routing ile ortak).
- ``policy``: güvenilen gizlilik politikası (kod).
- ``retrieval``: yerel lexical retrieval (BM25 + TR/EN alias), snapshot
  başına indeks ve sınırlı LRU sorgu önbelleği.
- ``validation``: yapılandırılmış model çıktısı denetimi.
- ``runner``: ``run_profile_rag`` — retrieval → model.complete → denetim →
  profil citations.
"""

from .chunking import CHUNKER_VERSION, DEFAULT_MAX_CHUNK_TOKENS, ProfileChunk, chunk_document, chunk_section
from .detection import (
    VISITOR_IDENTITY_ROUTE_REASON,
    detect_question_language,
    is_owner_profile_question,
    is_visitor_identity_question,
    is_visitor_identity_route,
    mentions_owner,
)
from .policy import PolicyVerdict, evaluate_policy, policy_note, policy_only_answer
from .repository import CanonicalProfileRepository, profile_summary_from_document
from .retrieval import (
    DEFAULT_PROFILE_RETRIEVER,
    INDEX_VERSION,
    MODE_RETRIEVAL_BUDGETS,
    ProfileIndex,
    ProfileEmbedding,
    ProfileRetriever,
    RetrievalBudget,
    RetrievalResult,
    RetrievedChunk,
    budget_for_mode,
)
from .runner import (
    ProfileQueryPlan,
    ProfileRunConfig,
    ProfileRunResult,
    plan_profile_query,
    run_profile_rag,
    visitor_identity_outcome,
)
from .source import (
    PROFILE_DIR_ENV,
    ContactChannel,
    PrivacyConfig,
    ProfileDocument,
    ProfileOwner,
    ProfileSection,
    ProfileSourceError,
    load_profile_source,
    resolve_profile_dir,
)
from .validation import EvidenceEntry, ValidationResult, validate_model_output

__all__ = [
    "CHUNKER_VERSION",
    "DEFAULT_MAX_CHUNK_TOKENS",
    "DEFAULT_PROFILE_RETRIEVER",
    "INDEX_VERSION",
    "MODE_RETRIEVAL_BUDGETS",
    "PROFILE_DIR_ENV",
    "VISITOR_IDENTITY_ROUTE_REASON",
    "CanonicalProfileRepository",
    "ContactChannel",
    "EvidenceEntry",
    "PolicyVerdict",
    "PrivacyConfig",
    "ProfileChunk",
    "ProfileDocument",
    "ProfileIndex",
    "ProfileOwner",
    "ProfileQueryPlan",
    "ProfileEmbedding",
    "ProfileRetriever",
    "ProfileRunConfig",
    "ProfileRunResult",
    "ProfileSection",
    "ProfileSourceError",
    "RetrievalBudget",
    "RetrievalResult",
    "RetrievedChunk",
    "ValidationResult",
    "budget_for_mode",
    "chunk_document",
    "chunk_section",
    "detect_question_language",
    "evaluate_policy",
    "is_owner_profile_question",
    "is_visitor_identity_question",
    "is_visitor_identity_route",
    "load_profile_source",
    "mentions_owner",
    "plan_profile_query",
    "policy_note",
    "policy_only_answer",
    "profile_summary_from_document",
    "resolve_profile_dir",
    "run_profile_rag",
    "validate_model_output",
    "visitor_identity_outcome",
]
