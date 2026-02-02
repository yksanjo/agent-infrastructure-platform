"""Circuit Breaker pattern for fault tolerance."""

from __future__ import annotations

import time
from enum import Enum, auto
from typing import Any

import structlog

logger = structlog.get_logger()


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = auto()  # Normal operation
    OPEN = auto()  # Failing, rejecting requests
    HALF_OPEN = auto()  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker for preventing cascade failures.
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests are rejected immediately
    - HALF_OPEN: Testing if service recovered with limited requests
    
    Example:
        ```python
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        
        if cb.can_execute():
            try:
                result = await risky_operation()
                cb.record_success()
            except Exception as e:
                cb.record_failure()
                raise
        else:
            # Circuit is open, fail fast
            raise CircuitBreakerError("Service unavailable")
        ```
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        success_threshold: int = 2,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        
        self._logger = logger
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state
    
    def can_execute(self) -> bool:
        """
        Check if a request should be allowed.
        
        Returns:
            True if request should proceed
        """
        if self._state == CircuitState.CLOSED:
            return True
        
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    self._logger.info("circuit_breaker_half_open")
                    return True
            return False
        
        if self._state == CircuitState.HALF_OPEN:
            # Allow limited requests in half-open state
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        
        return True
    
    def record_success(self) -> None:
        """Record a successful request."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            
            if self._success_count >= self.success_threshold:
                # Service recovered
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                self._half_open_calls = 0
                self._logger.info("circuit_breaker_closed")
        
        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success
            if self._failure_count > 0:
                self._failure_count = 0
    
    def record_failure(self) -> None:
        """Record a failed request."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._state == CircuitState.HALF_OPEN:
            # Service still failing
            self._state = CircuitState.OPEN
            self._half_open_calls = 0
            self._success_count = 0
            self._logger.warning("circuit_breaker_open_from_half_open")
        
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.failure_threshold:
                # Too many failures, open circuit
                self._state = CircuitState.OPEN
                self._logger.warning(
                    "circuit_breaker_open",
                    failure_count=self._failure_count,
                )
    
    def get_metrics(self) -> dict[str, Any]:
        """Get circuit breaker metrics."""
        return {
            "state": self._state.name,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
            "half_open_calls": self._half_open_calls,
        }


class CircuitBreakerRegistry:
    """Registry of circuit breakers for multiple services."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
    
    def get_or_create(
        self,
        service_id: str,
        **kwargs: Any,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker for a service."""
        if service_id not in self._breakers:
            self._breakers[service_id] = CircuitBreaker(**kwargs)
        return self._breakers[service_id]
    
    def get(self, service_id: str) -> CircuitBreaker | None:
        """Get a circuit breaker by ID."""
        return self._breakers.get(service_id)
    
    def remove(self, service_id: str) -> bool:
        """Remove a circuit breaker."""
        if service_id in self._breakers:
            del self._breakers[service_id]
            return True
        return False
    
    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """Get metrics for all circuit breakers."""
        return {
            service_id: breaker.get_metrics()
            for service_id, breaker in self._breakers.items()
        }
