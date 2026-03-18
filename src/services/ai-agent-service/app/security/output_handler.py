import re
from typing import Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class PIIType(str, Enum):
    TCKN = "tckn"
    CREDIT_CARD = "credit_card"
    EMAIL = "email"
    PHONE = "phone"
    API_KEY = "api_key"
    IP_ADDRESS = "ip_address"

class SecureResponseHandler:
    """Secure response handler with PII redaction and XSS prevention."""

    # PII Patterns for Turkey and general sensitive data
    PII_PATTERNS = {
        PIIType.TCKN: re.compile(r'\b[1-9]\d{10}\b'),
        PIIType.CREDIT_CARD: re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
        PIIType.EMAIL: re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        PIIType.PHONE: re.compile(r'\b(05\d{2})\s?\d{3}\s?\d{2}\s?\d{2}\b'),
        PIIType.API_KEY: re.compile(r'\b[A-Z]{2,}[A-Z0-9]{32,}\b'),
        PIIType.IP_ADDRESS: re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
    }

    # XSS patterns — only match inside HTML tags to avoid false positives
    # on normal text like "based on =", "depends on =", or web search snippets
    XSS_PATTERNS = [
        r'<script[^>]*>.*?</script>',      # Script tags
        r'javascript\s*:',                  # JavaScript protocol
        r'<[^>]+\bon\w+\s*=',              # Event handlers ONLY inside HTML tags
        r'<iframe[^>]*>',                   # iFrame tags
        r'<object[^>]*>',                   # Object tags
        r'<embed[^>]*>',                    # Embed tags
        r'<form[^>]*>',                     # Form tags
        r'<meta[^>]*http-equiv',            # Meta refresh
    ]

    def __init__(self):
        self.xss_pattern = re.compile('|'.join(self.XSS_PATTERNS), re.IGNORECASE | re.DOTALL)

    def _strip_dangerous_content(self, text: str) -> str:
        """Strip dangerous HTML tags and attributes instead of raising errors."""
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<iframe[^>]*>.*?</iframe>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<object[^>]*>.*?</object>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<embed[^>]*/?>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<form[^>]*>.*?</form>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<meta[^>]*http-equiv[^>]*>', '', text, flags=re.IGNORECASE)
        # Strip event handlers from remaining tags
        text = re.sub(r'\bon\w+\s*=\s*["\'][^"\']*["\']', '', text, flags=re.IGNORECASE)
        text = re.sub(r'javascript\s*:', '', text, flags=re.IGNORECASE)
        return text

    def sanitize_response(self, response: str) -> str:
        """Sanitize LLM response by redacting PII and stripping dangerous content."""
        if not response:
            return response

        # Step 1: PII Redaction
        for pii_type, pattern in self.PII_PATTERNS.items():
            response = pattern.sub(f'[{pii_type.value.upper()}_REDACTED]', response)

        # Step 2: XSS — strip dangerous tags instead of raising
        if self.xss_pattern.search(response):
            logger.warning("Potential XSS content detected in LLM response, sanitizing.")
            response = self._strip_dangerous_content(response)

        return response

    def validate_response(self, response: Any) -> bool:
        """Validate response structure and content."""
        if not isinstance(response, dict):
            return True

        # Check for malicious content in string representations of the dict
        response_str = str(response)
        if self.xss_pattern.search(response_str):
            logger.warning("Potential XSS in structured response, will be sanitized via sanitize_dict")

        return True

    def sanitize_dict(self, data: dict) -> dict:
        """Recursively sanitize all string values in a dictionary."""
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, str):
                sanitized[key] = self.sanitize_response(value)
            elif isinstance(value, dict):
                sanitized[key] = self.sanitize_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self.sanitize_response(v) if isinstance(v, str) else 
                    self.sanitize_dict(v) if isinstance(v, dict) else v
                    for v in value
                ]
            else:
                sanitized[key] = value
        return sanitized
