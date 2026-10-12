"""B1 mesaj sözleşmeleri: zarf + tür bazlı payload modelleri ve kategorize doğrulayıcı.

Tek sözleşme kaynağı: ``src/contracts/agent/v1/`` (JSON Schema dosyaları +
contract.json). Bu modül aynı sözleşmenin Pydantic karşılığıdır; ortak fixture
seti (``src/contracts/agent/fixtures/``) iki dilin denkliğini testlerle sabitler.
"""

from .enums import AgentErrorCode, AgentMode, Direction, ModePreference, Producer, ProgressKind, SourceScope
from .errors import AgentContractError, ContractErrorCategory
from .registry import MAX_PAYLOAD_BYTES, SCHEMA_VERSION, MESSAGE_TYPE_REGISTRY, MessageTypeSpec
from .envelope import AgentEnvelope
from .payloads import (
    AgentActionProposedV1,
    AgentActionResultV1,
    AgentCancellationRequestedV1,
    AgentExecutionRequestedV1,
    AgentRunAcceptedV1,
    AgentRunCancelledV1,
    AgentRunCompletedV1,
    AgentRunFailedV1,
    AgentRunModeSelectedV1,
    AgentRunNeedsInputV1,
    AgentRunPartiallyCompletedV1,
    AgentRunProgressedV1,
    AgentResumeRequestedV1,
    ArticleContentChangedV1,
    ContentSnapshotBatchV1,
    ContentSnapshotCompletedV1,
    ProfileContentChangedV1,
    ProjectContentChangedV1,
)
from .validator import ParsedEnvelope, parse_envelope
from .amqp import to_amqp_properties
from .sequence import EventSequenceTracker, SequenceRegression

__all__ = [
    "MAX_PAYLOAD_BYTES",
    "SCHEMA_VERSION",
    "MESSAGE_TYPE_REGISTRY",
    "MessageTypeSpec",
    "AgentEnvelope",
    "ParsedEnvelope",
    "parse_envelope",
    "AgentContractError",
    "ContractErrorCategory",
    "to_amqp_properties",
    "EventSequenceTracker",
    "SequenceRegression",
    "Direction",
    "Producer",
    "AgentMode",
    "ModePreference",
    "SourceScope",
    "AgentErrorCode",
    "ProgressKind",
    "AgentExecutionRequestedV1",
    "AgentCancellationRequestedV1",
    "AgentResumeRequestedV1",
    "AgentActionResultV1",
    "AgentRunAcceptedV1",
    "AgentRunModeSelectedV1",
    "AgentRunProgressedV1",
    "AgentRunNeedsInputV1",
    "AgentRunCompletedV1",
    "AgentRunPartiallyCompletedV1",
    "AgentRunFailedV1",
    "AgentRunCancelledV1",
    "AgentActionProposedV1",
    "ArticleContentChangedV1",
    "ContentSnapshotBatchV1",
    "ContentSnapshotCompletedV1",
    "ProfileContentChangedV1",
    "ProjectContentChangedV1",
]
