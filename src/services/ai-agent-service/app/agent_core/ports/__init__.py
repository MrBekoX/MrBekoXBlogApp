"""Agent çekirdeğinin 11 dış portu (plan A1, ``01-agent-gelistirme-plani.md:184``).

Portlar agent paketi içindeki arayüzlerdir; somut sağlayıcı adaptörleri
``agent_core.adapters`` altında yaşar. Production uses configured real
providers and fails closed when their configuration is missing. Ortak hata sözleşmesi:
``agent_core.errors.AgentErrorCode`` ve ``PortError``.
"""

from .budget import BudgetKind, BudgetReservation, BudgetStore, BudgetUsage
from .cancellation import CancellationToken
from .checkpoint import CheckpointStore
from .content import ContentRepository
from .embedding import EmbeddingProvider
from .model import ModelProvider, ModelRequest, ModelResponse, ModelUsage
from .profile import ProfileKnowledgeRepository, ProfileRepository, ProfileSummary
from .progress import ProgressSink
from .project import ProjectRecord, ProjectRepository
from .source_reader import ReadSource, SourceReader
from .web_search import WebSearchProvider, WebSearchResult

__all__ = [
    "BudgetKind",
    "BudgetReservation",
    "BudgetStore",
    "BudgetUsage",
    "CancellationToken",
    "CheckpointStore",
    "ContentRepository",
    "EmbeddingProvider",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "ModelUsage",
    "ProfileKnowledgeRepository",
    "ProfileRepository",
    "ProfileSummary",
    "ProgressSink",
    "ProjectRecord",
    "ProjectRepository",
    "ReadSource",
    "SourceReader",
    "WebSearchProvider",
    "WebSearchResult",
]
