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
        PIIType.TCKN: re.compile(r'\b\d{11}\b'),
        PIIType.CREDIT_CARD: re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
        PIIType.EMAIL: re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        PIIType.PHONE: re.compile(r'\b(05\d{2})\s?\d{3}\s?\d{2}\s?\d{2}\b'),
        PIIType.API_KEY: re.compile(r'\b[A-Z]{2,}[A-Z0-9]{32,}\b'),
        PIIType.IP_ADDRESS: re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
    }

    # XSS patterns
    XSS_PATTERNS = [
        r'<script[^>]*>.*?</script>',
        r'javascript:',
        r'on\w+\s*=',
        r'<iframe[^>]*>',
        r'<object[^>]*>',
        r'<embed[^>]*>',
    ]

    def __init__(self):
        self.xss_pattern = re.compile('|'.join(self.XSS_PATTERNS), re.IGNORECASE | re.DOTALL)

    def sanitize_response(self, response: str) -> str:
        """Sanitize LLM response by redacting PII and filtering XSS."""
        if not response:
            return response

        # Step 1: PII Redaction
        for pii_type, pattern in self.PII_PATTERNS.items():
            response = pattern.sub(f'[{pii_type.value.upper()}_REDACTED]', response)

        # Step 2: XSS Detection (raise error if found)
        if self.xss_pattern.search(response):
             # Log the attempt but maybe don't display the full payload to avoid log pollution/security risks
             logger.warning("Potential XSS attack detected in LLM response.")
             raise ValueError('Potential XSS attack detected in LLM response')

        return response

    def validate_response(self, response: Any) -> bool:
        """Validate response structure and content."""
        if not isinstance(response, dict):
            # If we expect a dict but get something else, it might be valid if the caller handles it,
            # but this method specifically validates dict structure safety if utilized that way.
            # For general validation, we rely on sanitize_response for strings.
            return True

        # Check for malicious content in string representations of the dict
        # This is a broad check
        response_str = str(response)
        if self.xss_pattern.search(response_str):
             logger.warning("Potential XSS in structured response")
             raise ValueError('Potential XSS in response')

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
