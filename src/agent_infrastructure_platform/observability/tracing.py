"""Distributed tracing for agent interactions."""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import structlog

logger = structlog.get_logger()

# Context variables for trace propagation
_current_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_current_span_id: ContextVar[str | None] = ContextVar("span_id", default=None)


@dataclass
class Span:
    """A trace span."""
    
    id: str = field(default_factory=lambda: f"span-{uuid4().hex[:16]}")
    trace_id: str = ""
    parent_id: str | None = None
    name: str = ""
    
    # Timing
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    
    # Context
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    
    # Status
    status: str = "unset"  # unset, ok, error
    error_message: str | None = None
    
    def end(self, status: str = "ok", error: str | None = None) -> None:
        """End the span."""
        self.end_time = time.time()
        self.status = status
        if error:
            self.error_message = error
    
    def set_attribute(self, key: str, value: Any) -> None:
        """Set an attribute."""
        self.attributes[key] = value
    
    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add an event."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })
    
    @property
    def duration_ms(self) -> float:
        """Get span duration in milliseconds."""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000


class Tracer:
    """
    Distributed tracer for agent interactions.
    
    Implements OpenTelemetry-compatible tracing for:
    - Cross-agent request tracing
    - Performance monitoring
    - Error tracking
    - Dependency mapping
    
    Example:
        ```python
        tracer = Tracer(service_name="agent-orchestrator")
        
        # Start a span
        with tracer.start_span("process_task") as span:
            span.set_attribute("task.id", task_id)
            span.set_attribute("agent.id", agent_id)
            
            # Process task
            result = await process_task(task)
            
            if result.error:
                span.add_event("error", {"message": result.error})
        
        # Export traces
        traces = tracer.export()
        ```
    """

    def __init__(self, service_name: str = "aip") -> None:
        self.service_name = service_name
        self._spans: list[Span] = []
        self._active_spans: dict[str, Span] = {}
        
        self._logger = logger
    
    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """
        Start a new span.
        
        Args:
            name: Span name
            attributes: Initial attributes
            
        Returns:
            New span
        """
        # Get parent context
        parent_id = _current_span_id.get()
        trace_id = _current_trace_id.get()
        
        if not trace_id:
            trace_id = f"trace-{uuid4().hex[:16]}"
            _current_trace_id.set(trace_id)
        
        span = Span(
            trace_id=trace_id,
            parent_id=parent_id,
            name=name,
            attributes=attributes or {},
        )
        
        self._spans.append(span)
        self._active_spans[span.id] = span
        
        # Set as current span
        _current_span_id.set(span.id)
        
        return span
    
    def end_span(self, span: Span, status: str = "ok", error: str | None = None) -> None:
        """End a span and restore parent context."""
        span.end(status, error)
        
        if span.id in self._active_spans:
            del self._active_spans[span.id]
        
        # Restore parent context
        if span.parent_id:
            _current_span_id.set(span.parent_id)
        else:
            _current_span_id.set(None)
    
    def get_current_span(self) -> Span | None:
        """Get the current active span."""
        span_id = _current_span_id.get()
        if span_id:
            return self._active_spans.get(span_id)
        return None
    
    def add_event(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Add an event to the current span."""
        span = self.get_current_span()
        if span:
            span.add_event(name, attributes)
    
    def set_attribute(self, key: str, value: Any) -> None:
        """Set an attribute on the current span."""
        span = self.get_current_span()
        if span:
            span.set_attribute(key, value)
    
    def inject_context(self, carrier: dict[str, str]) -> dict[str, str]:
        """
        Inject trace context into a carrier.
        
        Args:
            carrier: Dictionary to inject into
            
        Returns:
            Updated carrier
        """
        trace_id = _current_trace_id.get()
        span_id = _current_span_id.get()
        
        if trace_id:
            carrier["trace_id"] = trace_id
        if span_id:
            carrier["span_id"] = span_id
        
        return carrier
    
    def extract_context(self, carrier: dict[str, str]) -> None:
        """
        Extract trace context from a carrier.
        
        Args:
            carrier: Dictionary containing trace context
        """
        if "trace_id" in carrier:
            _current_trace_id.set(carrier["trace_id"])
        if "span_id" in carrier:
            _current_span_id.set(carrier["span_id"])
    
    def export(self) -> list[dict[str, Any]]:
        """Export all spans."""
        return [
            {
                "id": span.id,
                "trace_id": span.trace_id,
                "parent_id": span.parent_id,
                "name": span.name,
                "start_time": span.start_time,
                "end_time": span.end_time,
                "duration_ms": span.duration_ms,
                "attributes": span.attributes,
                "events": span.events,
                "status": span.status,
                "error_message": span.error_message,
            }
            for span in self._spans
        ]
    
    def clear(self) -> None:
        """Clear all spans."""
        self._spans.clear()
        self._active_spans.clear()


# Context manager for spans
class SpanContext:
    """Context manager for span lifecycle."""

    def __init__(
        self,
        tracer: Tracer,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.tracer = tracer
        self.name = name
        self.attributes = attributes
        self.span: Span | None = None
    
    def __enter__(self) -> Span:
        self.span = self.tracer.start_span(self.name, self.attributes)
        return self.span
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.span:
            if exc_val:
                self.tracer.end_span(self.span, status="error", error=str(exc_val))
            else:
                self.tracer.end_span(self.span)
