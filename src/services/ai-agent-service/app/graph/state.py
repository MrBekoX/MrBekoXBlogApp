"""LangGraph state definitions for the multi-agent pipeline."""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """Root state for the LangGraph workflow.

    Carries data from RabbitMQ ingestion through routing, processing,
    and response publishing.
    """

    # Identifiers
    thread_id: str
    message_id: str
    operation_id: str
    correlation_id: str

    # Inbound event
    event_type: str
    payload: dict[str, Any]
    content: str
    language: str

    # Routing
    target_agent: str

    # Processing results
    analysis_result: dict[str, Any] | None
    chat_response: dict[str, Any] | None
    generation_result: dict[str, Any] | None

    # Outbound envelope prepared by respond node
    outbound_routing_key: str | None
    outbound_message: dict[str, Any] | None

    # Lifecycle
    status: str  # pending | routed | completed | ready_to_publish | failed | retryable_failed
    error: str | None