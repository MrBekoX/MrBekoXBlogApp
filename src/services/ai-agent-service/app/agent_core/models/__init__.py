"""Agent çekirdeğinin iş modelleri.

13 iş modeli + ``RunStatus`` (plan A1 listesi; W0 §2.1): ``ExecutionContext``,
``AgentOutcome``, ``RouteDecision``, ``ArticleSnapshot``, ``ArticleChunk``,
``SourceReference``, ``EvidenceItem``, ``ResearchPlan``, ``ResearchFinding``,
``DomainProgress``, ``UsageRecord``, ``ActionProposal``, ``ValidatedActionResult``.

Bu modellerde AMQP header'ı, queue adı ve HTTP response nesnesi yoktur
(agent-architecture §3). Alan adları snake_case, JSON temsili W0 §6.3 ile
uyumludur.
"""

from .action import ActionProposal, ValidatedActionResult
from .article import ArticleChunk, ArticleSnapshot, compute_content_hash
from .base import BusinessModel, HashHex, Identifier, LanguageCode, NonEmptyText, UtcDatetime
from .context import BudgetProfile, ConversationTurn, ExecutionContext
from .enums import AgentMode, ModePreference, ProgressKind, RunIntent, RunStatus, SourceScope
from .outcome import AgentOutcome
from .progress import DomainProgress, MAX_GENERATION_DELTA_CHARS, split_generation_delta
from .research import ResearchFinding, ResearchPlan
from .routing import ModeUpgradeRecord, RouteDecision
from .sources import EvidenceItem, SourceReference
from .usage import UsageRecord

__all__ = [
    "ActionProposal",
    "AgentMode",
    "AgentOutcome",
    "ArticleChunk",
    "ArticleSnapshot",
    "BudgetProfile",
    "BusinessModel",
    "ConversationTurn",
    "DomainProgress",
    "EvidenceItem",
    "ExecutionContext",
    "HashHex",
    "Identifier",
    "LanguageCode",
    "MAX_GENERATION_DELTA_CHARS",
    "ModePreference",
    "ModeUpgradeRecord",
    "NonEmptyText",
    "ProgressKind",
    "ResearchFinding",
    "ResearchPlan",
    "RouteDecision",
    "RunIntent",
    "RunStatus",
    "SourceReference",
    "SourceScope",
    "UsageRecord",
    "UtcDatetime",
    "ValidatedActionResult",
    "compute_content_hash",
    "split_generation_delta",
]
