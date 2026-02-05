import pytest
import re
from app.security.output_handler import SecureResponseHandler, PIIType

class TestOutputSanitization:
    """Output sanitization test suite."""

    def test_pii_redaction(self):
        """Test PII redaction in responses."""
        handler = SecureResponseHandler()

        # Turkish ID, Email
        response = "User's TCKN is 12345678901 and email is test@example.com"
        sanitized = handler.sanitize_response(response)

        assert "[TCKN_REDACTED]" in sanitized
        assert "[EMAIL_REDACTED]" in sanitized
        assert "12345678901" not in sanitized
        assert "test@example.com" not in sanitized

    def test_xss_prevention(self):
        """Test XSS attack prevention."""
        handler = SecureResponseHandler()

        with pytest.raises(ValueError, match="XSS"):
            handler.sanitize_response("<script>alert('XSS')</script>")

    def test_dict_sanitization(self):
        """Test dictionary sanitization."""
        handler = SecureResponseHandler()

        data = {
            "summary": "Call me at 0555 123 45 67",
            "details": {"contact": "user@example.com"}
        }

        sanitized = handler.sanitize_dict(data)

        # Phone regex usually handles spaces, let's verify regex in output_handler
        # PIIType.PHONE regex: r'\b(05\d{2})\s?\d{3}\s?\d{2}\s?\d{2}\b'
        # Matches "0555 123 45 67" or "05551234567"
        
        assert "[PHONE_REDACTED]" in sanitized["summary"]
        assert "[EMAIL_REDACTED]" in sanitized["details"]["contact"]
