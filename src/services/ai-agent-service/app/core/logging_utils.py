"""Logging utilities for secure credential handling."""

import re
from urllib.parse import urlparse, urlunparse


def sanitize_url(url: str) -> str:
    """
    Remove credentials from a URL for safe logging.

    Examples:
        redis://:password@host:6379 -> redis://***@host:6379
        amqp://user:password@host:5672 -> amqp://***:***@host:5672
        postgresql://user:pass@host/db -> postgresql://***:***@host/db

    Args:
        url: URL that may contain credentials

    Returns:
        URL with credentials masked as ***
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)

        # No credentials in URL
        if not parsed.username and not parsed.password:
            return url

        # Build masked netloc
        masked_parts = []

        if parsed.username:
            masked_parts.append("***")
        if parsed.password:
            masked_parts.append("***")

        masked_userinfo = ":".join(masked_parts) if masked_parts else ""

        # Reconstruct netloc with masked credentials
        if masked_userinfo:
            if parsed.port:
                masked_netloc = f"{masked_userinfo}@{parsed.hostname}:{parsed.port}"
            else:
                masked_netloc = f"{masked_userinfo}@{parsed.hostname}"
        else:
            masked_netloc = parsed.netloc

        # Reconstruct the full URL
        sanitized = urlunparse((
            parsed.scheme,
            masked_netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))

        return sanitized

    except Exception:
        # If parsing fails, try regex fallback
        # Pattern: scheme://user:password@host or scheme://:password@host
        pattern = r'(://[^:]+:)[^@]+(@)'
        return re.sub(pattern, r'\1***\2', url)


def sanitize_dict_urls(data: dict, url_keys: list[str] | None = None) -> dict:
    """
    Sanitize URL fields in a dictionary for safe logging.

    Args:
        data: Dictionary that may contain URLs
        url_keys: List of keys to check for URLs (default: common URL key names)

    Returns:
        Dictionary with URL credentials masked
    """
    if url_keys is None:
        url_keys = [
            'url', 'redis_url', 'rabbitmq_url', 'database_url',
            'connection_string', 'dsn', 'uri', 'endpoint'
        ]

    result = data.copy()

    for key, value in result.items():
        if isinstance(value, str):
            # Check if key suggests it's a URL
            key_lower = key.lower()
            if any(url_key in key_lower for url_key in url_keys):
                result[key] = sanitize_url(value)
            # Also check if value looks like a URL
            elif '://' in value and '@' in value:
                result[key] = sanitize_url(value)
        elif isinstance(value, dict):
            result[key] = sanitize_dict_urls(value, url_keys)

    return result
