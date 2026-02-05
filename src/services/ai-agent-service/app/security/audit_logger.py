import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict
from app.security.log_sanitizer import LogSanitizer

audit_logger = logging.getLogger('audit')

class AuditLogger:
    """Structured audit logging for security events."""

    EVENT_TYPES = [
        "ai_analysis",
        "prompt_injection_blocked",
        "unauthorized_access",
        "rag_retrieve",
        "pii_redacted",
        "authentication",
        "authorization_failed",
    ]

    def __init__(self):
        self.sanitizer = LogSanitizer()

    def log_event(
        self,
        event_type: str,
        user_id: str,
        resource_id: str,
        action: str,
        success: bool,
        details: Optional[Dict] = None,
        ip_address: Optional[str] = None
    ):
        """Log a security event with proper sanitization."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "user_id": self.sanitizer.hash_id(user_id),
            "resource_id": self.sanitizer.hash_id(resource_id),
            "action": action,
            "success": success,
            "details": self.sanitizer.sanitize(details or {}),
            "ip_address": self._mask_ip(ip_address) if ip_address else None,
        }

        audit_logger.info(f"AUDIT: {json.dumps(event)}")

    def _mask_ip(self, ip: str) -> str:
        """Mask IP address (preserve first two octets)."""
        parts = ip.split('.')
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.***.***"
        return "***"
