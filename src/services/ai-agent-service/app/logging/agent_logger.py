"""Structured agent logging for LangGraph node execution and routing."""

import json
import logging
import time
from typing import Any

logger = logging.getLogger("agent.trace")


class AgentLogger:
    """Emits structured JSON logs for agent observability.

    All methods are fire-and-forget — logging failures never propagate.
    """

    @staticmethod
    def log_node_execution(
        thread_id: str,
        node: str,
        duration_seconds: float,
        state_keys: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log a LangGraph node execution event."""
        try:
            event = {
                "event": "node_execution",
                "thread_id": thread_id,
                "node": node,
                "duration_ms": round(duration_seconds * 1000, 2),
                "state_keys": state_keys or [],
                "ts": time.time(),
            }
            if extra:
                event["extra"] = extra
            logger.info(json.dumps(event))
        except Exception:
            pass

    @staticmethod
    def log_agent_routing(
        thread_id: str,
        from_agent: str,
        to_agent: str,
        reason: str = "",
    ) -> None:
        """Log a routing decision by the supervisor."""
        try:
            event = {
                "event": "agent_routing",
                "thread_id": thread_id,
                "from": from_agent,
                "to": to_agent,
                "reason": reason,
                "ts": time.time(),
            }
            logger.info(json.dumps(event))
        except Exception:
            pass

    @staticmethod
    def log_verification(
        thread_id: str,
        passed: bool,
        hallucination_score: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log a verification result."""
        try:
            event = {
                "event": "verification",
                "thread_id": thread_id,
                "passed": passed,
                "hallucination_score": hallucination_score,
                "details": details or {},
                "ts": time.time(),
            }
            logger.info(json.dumps(event))
        except Exception:
            pass

    @staticmethod
    def log_react_iteration(
        thread_id: str,
        iteration: int,
        thought: str,
        action: str,
        observation_preview: str = "",
    ) -> None:
        """Log a ReAct reasoning iteration."""
        try:
            event = {
                "event": "react_iteration",
                "thread_id": thread_id,
                "iteration": iteration,
                "thought": thought[:200],
                "action": action,
                "observation_preview": observation_preview[:200],
                "ts": time.time(),
            }
            logger.info(json.dumps(event))
        except Exception:
            pass

    @staticmethod
    def log_memory_operation(
        session_id: str,
        operation: str,
        count: int = 0,
        duration_seconds: float = 0.0,
    ) -> None:
        """Log a memory read/write operation."""
        try:
            event = {
                "event": "memory_operation",
                "session_id": session_id,
                "operation": operation,
                "count": count,
                "duration_ms": round(duration_seconds * 1000, 2),
                "ts": time.time(),
            }
            logger.info(json.dumps(event))
        except Exception:
            pass
