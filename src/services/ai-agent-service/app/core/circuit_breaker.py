"""Circuit Breaker pattern implementation."""

import time
import logging
from enum import Enum
from typing import Callable, Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

class CircuitState(Enum):
    CLOSED = "CLOSED"     # Normal operation
    OPEN = "OPEN"         # Failing, blocking requests
    HALF_OPEN = "HALF_OPEN" # Testing if service is back

class CircuitOpenException(Exception):
    """Exception raised when circuit is open."""
    pass

class CircuitBreaker:
    """
    State machine for Circuit Breaker pattern.
    
    Prevents cascading failures by stopping requests to a failing service.
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 60):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> CircuitState:
        return self._state

    def allow_request(self) -> bool:
        """Check if request should be allowed based on state."""
        if self._state == CircuitState.CLOSED:
            return True
            
        if self._state == CircuitState.OPEN:
            # Check if timeout has passed
            if time.time() - self._last_failure_time > self._recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)
                return True
            return False
            
        if self._state == CircuitState.HALF_OPEN:
            # Allow one request to test
            return True
            
        return False

    def record_success(self):
        """Record a successful request."""
        if self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.CLOSED)
            self._failures = 0
        elif self._state == CircuitState.CLOSED:
            self._failures = 0

    def record_failure(self):
        """Record a failed request."""
        self._failures += 1
        self._last_failure_time = time.time()
        
        if self._state == CircuitState.CLOSED:
            if self._failures >= self._failure_threshold:
                self._transition_to(CircuitState.OPEN)
        
        elif self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState):
        """Transition to a new state."""
        if self._state != new_state:
            logger.warning(f"CircuitBreaker transition: {self._state.value} -> {new_state.value}")
            self._state = new_state

    async def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Execute async function with circuit breaker protection."""
        if not self.allow_request():
            raise CircuitOpenException("Circuit is OPEN")
            
        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            # Don't count CircuitOpenException as a failure (shouldn't happen here but safe guard)
            if not isinstance(e, CircuitOpenException):
                self.record_failure()
            raise e
