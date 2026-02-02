"""Common decorators for AIP components."""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agent_infrastructure_platform.common.exceptions import RetryExhaustedError

logger = structlog.get_logger()

P = ParamSpec("P")
T = TypeVar("T")


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """
    Retry decorator with exponential backoff for async functions.
    
    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        exceptions: Tuple of exception types to retry on
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            attempt = 0
            last_exception: Exception | None = None
            
            while attempt < max_attempts:
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    attempt += 1
                    last_exception = e
                    
                    if attempt >= max_attempts:
                        break
                    
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    logger.warning(
                        "retry_attempt",
                        func=func.__name__,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
            
            raise RetryExhaustedError(
                f"All {max_attempts} retry attempts exhausted for {func.__name__}",
                cause=last_exception,
            )
        
        return wrapper
    
    return decorator


def trace_span(
    operation_name: str | None = None,
    tags: dict[str, str] | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """
    Decorator to create an OpenTelemetry trace span.
    
    Args:
        operation_name: Name of the operation (defaults to function name)
        tags: Additional tags to add to the span
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            import opentelemetry.trace
            
            tracer = opentelemetry.trace.get_tracer(__name__)
            span_name = operation_name or func.__name__
            
            with tracer.start_as_current_span(span_name) as span:
                # Add default tags
                span.set_attribute("function.name", func.__name__)
                span.set_attribute("function.module", func.__module__)
                
                # Add custom tags
                if tags:
                    for key, value in tags.items():
                        span.set_attribute(key, value)
                
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("success", True)
                    return result
                except Exception as e:
                    span.set_attribute("success", False)
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                    span.record_exception(e)
                    raise
        
        return wrapper
    
    return decorator


class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(
        self,
        rate: float,  # tokens per second
        burst: int,   # maximum bucket size
    ) -> None:
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens from the bucket."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    async def wait(self, tokens: int = 1) -> None:
        """Wait until tokens are available."""
        while not await self.acquire(tokens):
            await asyncio.sleep(0.01)


def rate_limit(
    rate: float,
    burst: int,
    key_func: Callable[[Any], str] | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """
    Rate limit decorator using token bucket algorithm.
    
    Args:
        rate: Tokens per second
        burst: Maximum bucket size
        key_func: Function to extract rate limit key from arguments
    """
    limiters: dict[str, RateLimiter] = {}
    
    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Determine rate limit key
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = "default"
            
            # Get or create limiter
            if key not in limiters:
                limiters[key] = RateLimiter(rate, burst)
            limiter = limiters[key]
            
            # Wait for rate limit
            await limiter.wait()
            
            return await func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def cache_result(
    ttl_seconds: float,
    key_func: Callable[[Any], str] | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """
    Simple in-memory cache decorator for async functions.
    
    Args:
        ttl_seconds: Cache TTL in seconds
        key_func: Function to generate cache key from arguments
    """
    cache: dict[str, tuple[T, float]] = {}
    
    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Generate cache key
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = f"{func.__name__}:{hash(str(args) + str(kwargs))}"
            
            # Check cache
            now = time.monotonic()
            if key in cache:
                result, expiry = cache[key]
                if now < expiry:
                    return result
            
            # Execute and cache
            result = await func(*args, **kwargs)
            cache[key] = (result, now + ttl_seconds)
            return result
        
        return wrapper
    
    return decorator


def singleton[T](cls: type[T]) -> type[T]:
    """Singleton decorator for classes."""
    instances: dict[type[T], T] = {}
    
    @functools.wraps(cls)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    
    return wrapper  # type: ignore[return-value]


def measure_time[
    T
](func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[tuple[T, float]]]:
    """Decorator that measures execution time and returns (result, duration_ms)."""
    
    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> tuple[T, float]:
        start = time.perf_counter()
        result = await func(*args, **kwargs)
        duration = (time.perf_counter() - start) * 1000
        return result, duration
    
    return wrapper
