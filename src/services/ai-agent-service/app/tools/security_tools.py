"""Security tools for the AI agent tool registry."""

import logging
from typing import Any

from app.security.audit_logger import AuditLogger
from app.security.jailbreak_detector import SemanticJailbreakDetector
from app.security.output_handler import SecureResponseHandler

logger = logging.getLogger(__name__)

_jailbreak_detector = SemanticJailbreakDetector(use_llm=False)
_output_handler = SecureResponseHandler()
_audit = AuditLogger()


class InputGuardTool:
    """Screens user-supplied text for prompt injection and jailbreak attempts."""

    async def __call__(self, query: str, **kwargs: Any) -> str:
        try:
            result = await _jailbreak_detector.detect(query)
            if result.is_jailbreak:
                _audit.log_event(
                    event_type="prompt_injection_blocked",
                    user_id=kwargs.get("session_id", "unknown"),
                    resource_id=kwargs.get("post_id", ""),
                    action="input_guard_blocked",
                    success=False,
                    details={
                        "jailbreak_type": str(result.jailbreak_type),
                        "confidence": round(result.confidence, 3),
                        "patterns": result.patterns[:5],
                    },
                )
                return (
                    f"BLOCKED: Input flagged as {result.jailbreak_type} "
                    f"(confidence {result.confidence:.0%}). "
                    "Do NOT forward this to the LLM."
                )
            return "safe"
        except Exception as exc:
            _audit.log_event(
                event_type="prompt_injection_guard_error",
                user_id=kwargs.get("session_id", "unknown"),
                resource_id=kwargs.get("post_id", ""),
                action="input_guard_error",
                success=False,
                details={"error": str(exc)},
            )
            logger.warning("[InputGuardTool] Detection error: %s", exc)
            raise RuntimeError("input_guard_failed") from exc


class OutputGuardTool:
    """Sanitizes LLM-generated text before it is returned to the user."""

    async def __call__(self, query: str, **kwargs: Any) -> str:
        try:
            sanitized = _output_handler.sanitize_response(query)
            if sanitized != query:
                _audit.log_event(
                    event_type="pii_redacted",
                    user_id=kwargs.get("session_id", "unknown"),
                    resource_id=kwargs.get("post_id", ""),
                    action="output_guard_redacted",
                    success=True,
                )
            return sanitized
        except ValueError as exc:
            _audit.log_event(
                event_type="output_guard_blocked",
                user_id=kwargs.get("session_id", "unknown"),
                resource_id=kwargs.get("post_id", ""),
                action="output_guard_xss_blocked",
                success=False,
                details={"error": str(exc)},
            )
            raise RuntimeError("output_guard_blocked") from exc
        except Exception as exc:
            _audit.log_event(
                event_type="output_guard_error",
                user_id=kwargs.get("session_id", "unknown"),
                resource_id=kwargs.get("post_id", ""),
                action="output_guard_error",
                success=False,
                details={"error": str(exc)},
            )
            logger.warning("[OutputGuardTool] Sanitization error: %s", exc)
            raise RuntimeError("output_guard_failed") from exc


class SecurityAuditTool:
    """Emits structured audit log entries for agent-initiated operations."""

    async def __call__(self, query: str, **kwargs: Any) -> str:
        _audit.log_event(
            event_type="ai_analysis",
            user_id=kwargs.get("session_id", "unknown"),
            resource_id=kwargs.get("post_id", ""),
            action=query[:200],
            success=True,
            details=kwargs.get("metadata"),
        )
        return f"Audit event recorded: {query[:80]}"
