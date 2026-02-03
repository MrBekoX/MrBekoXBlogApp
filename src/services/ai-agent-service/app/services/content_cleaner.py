"""Content cleaner service - Utility for sanitizing content."""

import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)

# Common prompt injection patterns to detect
INJECTION_PATTERNS = [
    r'ignore\s+(previous|above|all)\s+instructions?',
    r'disregard\s+(previous|above|all)\s+instructions?',
    r'forget\s+(previous|above|all)\s+instructions?',
    r'override\s+(previous|above|all)\s+instructions?',
    r'new\s+instructions?:',
    r'system\s*:',
    r'assistant\s*:',
    r'user\s*:',
    r'you\s+are\s+(now|a)\s+',
    r'act\s+as\s+(if|a)\s+',
    r'pretend\s+(you|to\s+be)',
    r'roleplay\s+as',
    r'imagine\s+you\s+are',
    r'dan\s+mode',
    r'developer\s+mode',
    r'jailbreak',
    r'bypass\s+(filter|restriction|safety)',
    r'\[\s*system\s*\]',
    r'\[\s*inst\s*\]',
    r'\[\s*INST\s*\]',
    r'<\|im_start\|>',
    r'<\|im_end\|>',
    r'###\s*(System|User|Assistant)',
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


class ContentCleanerService:
    """
    Service for cleaning and sanitizing content.

    Single Responsibility: Content sanitization and security.
    """

    @staticmethod
    def detect_injection(content: str) -> Tuple[bool, list[str]]:
        """
        Detect potential prompt injection attempts.

        Args:
            content: User-provided content to analyze

        Returns:
            Tuple of (is_suspicious, matched_patterns)
        """
        matched = []
        for i, pattern in enumerate(COMPILED_PATTERNS):
            if pattern.search(content):
                matched.append(INJECTION_PATTERNS[i])

        if matched:
            logger.warning(f"Potential injection detected: {matched[:3]}")

        return bool(matched), matched

    @staticmethod
    def sanitize_content(content: str) -> str:
        """
        Sanitize content to reduce prompt injection risk.

        Args:
            content: Raw user content

        Returns:
            Sanitized content
        """
        if not content:
            return content

        # Remove null bytes and control characters
        content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', content)

        # Remove special Unicode characters
        content = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u206f]', '', content)

        # Normalize multiple newlines
        content = re.sub(r'\n{3,}', '\n\n', content)

        # Normalize multiple spaces
        content = re.sub(r' {2,}', ' ', content)

        return content.strip()

    @staticmethod
    def strip_html_and_images(content: str) -> str:
        """
        Remove HTML tags, base64 images, and URLs.
        Optimized for LLM processing.

        Args:
            content: Raw content with potential HTML

        Returns:
            Cleaned plain text
        """
        # Check for injection attempts
        is_suspicious, patterns = ContentCleanerService.detect_injection(content)
        if is_suspicious:
            logger.warning(f"Content contains potential injection: {patterns[:3]}")

        # Remove base64 images
        content = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '', content)

        # Remove markdown images
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)

        # Remove HTML image tags
        content = re.sub(r'<img[^>]*>', '', content, flags=re.IGNORECASE)

        # Remove HTML tags but keep text
        content = re.sub(r'<[^>]+>', ' ', content)

        # Remove URLs
        content = re.sub(r'https?://\S+', '', content)

        # Apply sanitization
        content = ContentCleanerService.sanitize_content(content)

        # Normalize whitespace
        content = re.sub(r'\s+', ' ', content).strip()

        return content

    @staticmethod
    def clean_for_rag(content: str) -> str:
        """
        Milder cleaning specifically for RAG indexing.
        Preserves more content structure than strip_html_and_images.

        Args:
            content: Raw content

        Returns:
            Cleaned content suitable for RAG
        """
        if not content:
            return ""

        # Remove base64 images
        content = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '', content)

        # Remove markdown images but keep alt text
        content = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', content)

        # Remove HTML images but keep alt text
        content = re.sub(
            r'<img[^>]*alt=["\']([^"\']*)["\'][^>]*>',
            r'\1',
            content,
            flags=re.IGNORECASE
        )
        content = re.sub(r'<img[^>]*>', '', content, flags=re.IGNORECASE)

        # Remove basic formatting tags
        content = re.sub(r'</?(b|i|em|strong)>', ' ', content, flags=re.IGNORECASE)

        # Remove other HTML tags
        content = re.sub(r'<[^>]+>', ' ', content)

        # Remove URLs
        content = re.sub(r'https?://\S+', '', content)

        # Apply mild sanitization
        content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', content)
        content = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u206f]', '', content)

        # Normalize whitespace but preserve paragraphs
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' {2,}', ' ', content)

        return content.strip()

    @staticmethod
    def is_safe_content(content: str, max_length: int = 100_000) -> Tuple[bool, str]:
        """
        Check if content is safe to process.

        Args:
            content: Content to check
            max_length: Maximum allowed length

        Returns:
            Tuple of (is_safe, reason)
        """
        if not content:
            return False, "Content is empty"

        if len(content) > max_length:
            return False, f"Content exceeds max length of {max_length}"

        # Check for excessive special characters
        special_ratio = len(re.findall(r'[^\w\s.,!?;:\-\'\"()]', content)) / len(content)
        if special_ratio > 0.3:
            return False, "Content contains too many special characters"

        return True, "OK"
