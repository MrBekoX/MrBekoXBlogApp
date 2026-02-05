import re
import hashlib
from typing import Any, Dict

class LogSanitizer:
    """Sanitize sensitive data from logs."""

    SENSITIVE_PATTERNS = {
        'tckn': re.compile(r'\b\d{11}\b'),
        'credit_card': re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
        'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        'phone': re.compile(r'\b(05\d{2})\s?\d{3}\s?\d{2}\s?\d{2}\b'),
        'password': re.compile(r'password["\']?\s*[:=]\s*["\']?[^"\']+', re.IGNORECASE),
        'token': re.compile(r'token["\']?\s*[:=]\s*["\']?[^"\']{20,}', re.IGNORECASE),
        'api_key': re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?[^"\']{20,}', re.IGNORECASE),
    }

    def __init__(self, max_content_length: int = 100):
        self.max_content_length = max_content_length

    def sanitize(self, data: Any, mask_ids: bool = True) -> Any:
        """Sanitize sensitive data from logs."""
        if isinstance(data, str):
            return self._sanitize_string(data, mask_ids)
        elif isinstance(data, dict):
            return self._sanitize_dict(data, mask_ids)
        elif isinstance(data, list):
            return [self.sanitize(item, mask_ids) for item in data]
        return data

    def _sanitize_string(self, text: str, mask_ids: bool) -> str:
        """Sanitize a string value."""
        # Truncate long content
        if self.max_content_length > 0 and len(text) > self.max_content_length:
            text = text[:self.max_content_length] + "..."

        # Mask sensitive patterns
        for label, pattern in self.SENSITIVE_PATTERNS.items():
            text = pattern.sub(f'[{label.upper()}_REDACTED]', text)

        return text

    def _sanitize_dict(self, data: Dict[str, Any], mask_ids: bool) -> Dict[str, Any]:
        """Sanitize dictionary values."""
        sanitized = {}
        for key, value in data.items():
            # Always redact sensitive keys
            if any(sensitive in key.lower() for sensitive in ['password', 'token', 'secret', 'api_key']):
                sanitized[key] = '***REDACTED***'
            elif isinstance(value, str):
                sanitized[key] = self._sanitize_string(value, mask_ids)
            elif isinstance(value, (dict, list)):
                sanitized[key] = self.sanitize(value, mask_ids)
            else:
                sanitized[key] = value
        return sanitized

    def hash_id(self, id: str) -> str:
        """Hash an ID for audit trail (preserves format for tracing)."""
        if not id:
            return ""
        return hashlib.sha256(id.encode()).hexdigest()[:16]
