"""Custom exceptions for the application."""

from typing import Any


class AppException(Exception):
    """Base exception for application errors."""

    def __init__(self, message: str, details: Any = None):
        self.message = message
        self.details = details
        super().__init__(message)


class LLMException(AppException):
    """Exception for LLM-related errors."""

    pass


class CacheException(AppException):
    """Exception for cache-related errors."""

    pass


class VectorStoreException(AppException):
    """Exception for vector store errors."""

    pass


class MessageBrokerException(AppException):
    """Exception for message broker errors."""

    pass


class ValidationException(AppException):
    """Exception for validation errors."""

    pass


class ContentTooLargeException(ValidationException):
    """Exception when content exceeds maximum size."""

    def __init__(self, max_size: int, actual_size: int):
        super().__init__(
            f"Content size ({actual_size}) exceeds maximum ({max_size})",
            details={"max_size": max_size, "actual_size": actual_size}
        )


class InjectionDetectedException(ValidationException):
    """Exception when potential prompt injection is detected."""

    def __init__(self, patterns: list[str]):
        super().__init__(
            "Potential prompt injection detected",
            details={"patterns": patterns}
        )
