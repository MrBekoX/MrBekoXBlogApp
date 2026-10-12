"""Transport katmanı: RabbitMQ üzerinden backend (.NET) ile agent çekirdeği arasındaki taşıma.

Bu paket agent iş modellerinin (``agent_core``) DIŞINDADIR; yön tek yönlüdür
(messaging → agent_core izinli, tersi yasak — W0 Ç2). Broker envelope'u yalnız
burada bilinir; agent_core transport kavramı görmez.
"""

from .settings import BrokerSettings, from_env
from .topology import (
    BACKEND_EVENTS_QUEUE,
    COMMANDS_EXCHANGE,
    CONTENT_EXCHANGE,
    CONTENT_QUEUE,
    CONTROL_QUEUE,
    DEAD_EXCHANGE,
    DEFAULT_RETRY_TIER_SECONDS,
    EVENTS_EXCHANGE,
    EXECUTE_QUEUE,
    QueueSpec,
    Topology,
    build_topology,
    declare_topology,
    verify_topology,
)
from .errors import TopologyError
from .connection import broker_connection, connect_broker
from .publisher import BrokerPublisher, PublishResult
from .consumer import BrokerConsumer
from .db import AgentDbError, AgentDbSettings, connect_pool
from .job_store import (
    ACCEPTED_MESSAGE_TYPE,
    JOB_STATUS_ACCEPTED,
    AcceptOutcome,
    JobPayloadConflict,
    JobStore,
    build_accepted_envelope,
    compute_payload_hash,
)
from .intake import EXECUTE_COMMAND_TYPE, IntakeOutcome, IntakePolicyError, IntakeService
from .outbox import OutboxRelay, RelayBatchResult
from .events import (
    AgentEventPublisher,
    AgentOutcome,
    AlreadyTerminal,
    EventPublishError,
    ThrottledProgress,
)
from .content import (
    CONTENT_MESSAGE_TYPES,
    ContentApplyOutcome,
    ContentConsumerService,
    ContentIndexProjector,
    ContentPolicyError,
    ContentRevisionConflict,
    ContentSyncReport,
    ContentSyncState,
    StaleExecutionRejected,
    build_content_consumer,
)
from .control_store import (
    ACTIVE_JOB_STATUSES,
    BackpressureSnapshot,
    CancelIntentOutcome,
    CancelIntentResult,
    ControlStore,
    PENDING_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
)
from .control import (
    ACTION_RESULT_COMMAND_TYPE,
    CANCEL_COMMAND_TYPE,
    CONTROL_MESSAGE_TYPES,
    ControlConsumerService,
    ControlPolicyError,
    RESUME_COMMAND_TYPE,
    build_control_consumer,
)
from .control_driver import CollaborationResumeDriver, ContinuationBusy
from .worker import ExecutionDependencies, ExecutionWorker, WorkerSettings
from .retry import (
    DEFAULT_RETRY_TIERS,
    DlqReplayService,
    GraphExecutionError,
    PermanentContractError,
    ReplayDecision,
    ReplayGuard,
    RetryAction,
    RetryAwareBrokerConsumer,
    RetryDecision,
    RetryTierPolicy,
    TransportError,
    TransportRetryService,
    classify_exception,
    next_retry_tier,
)
from .reaper import DeadlineReaper, ReapResult

__all__ = [
    "BrokerSettings",
    "from_env",
    "Topology",
    "QueueSpec",
    "build_topology",
    "declare_topology",
    "verify_topology",
    "TopologyError",
    "connect_broker",
    "broker_connection",
    "BrokerPublisher",
    "PublishResult",
    "BrokerConsumer",
    "COMMANDS_EXCHANGE",
    "EVENTS_EXCHANGE",
    "CONTENT_EXCHANGE",
    "DEAD_EXCHANGE",
    "EXECUTE_QUEUE",
    "CONTROL_QUEUE",
    "CONTENT_QUEUE",
    "BACKEND_EVENTS_QUEUE",
    "DEFAULT_RETRY_TIER_SECONDS",
    # B4: kalıcı iş kabulü
    "AgentDbError",
    "AgentDbSettings",
    "connect_pool",
    "JobStore",
    "AcceptOutcome",
    "JobPayloadConflict",
    "compute_payload_hash",
    "build_accepted_envelope",
    "ACCEPTED_MESSAGE_TYPE",
    "JOB_STATUS_ACCEPTED",
    "IntakeService",
    "IntakeOutcome",
    "IntakePolicyError",
    "EXECUTE_COMMAND_TYPE",
    "OutboxRelay",
    "RelayBatchResult",
    # B5: agent olay yayını
    "AgentEventPublisher",
    "AgentOutcome",
    "AlreadyTerminal",
    "EventPublishError",
    "ThrottledProgress",
    # B8: içerik olayları ve güncellik projection'u
    "CONTENT_MESSAGE_TYPES",
    "ContentApplyOutcome",
    "ContentConsumerService",
    "ContentIndexProjector",
    "ContentPolicyError",
    "ContentRevisionConflict",
    "ContentSyncReport",
    "ContentSyncState",
    "StaleExecutionRejected",
    "build_content_consumer",
    # B7: retry/DLQ, iptal ve backpressure
    "TransportError",
    "GraphExecutionError",
    "PermanentContractError",
    "RetryAction",
    "RetryDecision",
    "TransportRetryService",
    "RetryAwareBrokerConsumer",
    "RetryTierPolicy",
    "DEFAULT_RETRY_TIERS",
    "classify_exception",
    "next_retry_tier",
    "DlqReplayService",
    "ReplayDecision",
    "ReplayGuard",
    "ControlStore",
    "CancelIntentOutcome",
    "CancelIntentResult",
    "BackpressureSnapshot",
    "TERMINAL_JOB_STATUSES",
    "ACTIVE_JOB_STATUSES",
    "PENDING_JOB_STATUSES",
    "ControlConsumerService",
    "ControlPolicyError",
    "CONTROL_MESSAGE_TYPES",
    "CANCEL_COMMAND_TYPE",
    "RESUME_COMMAND_TYPE",
    "ACTION_RESULT_COMMAND_TYPE",
    "build_control_consumer",
    # W6 F3: kontrol komutlarının graph devamı sürücüsü + worker yüzeyi
    "CollaborationResumeDriver",
    "ContinuationBusy",
    "ExecutionWorker",
    "ExecutionDependencies",
    "WorkerSettings",
    "DeadlineReaper",
    "ReapResult",
]
