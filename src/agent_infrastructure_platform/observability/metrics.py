"""Metrics collection for agent monitoring."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class MetricPoint:
    """A single metric data point."""
    
    timestamp: float
    value: float
    labels: dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """
    Collect and aggregate metrics from agents and infrastructure.
    
    Features:
    - Counter, Gauge, and Histogram metrics
    - Label-based aggregation
    - Prometheus-compatible export
    - Real-time dashboards
    
    Example:
        ```python
        metrics = MetricsCollector()
        
        # Counter
        metrics.counter(
            "tasks_completed",
            labels={"agent": "agent-1", "status": "success"},
        ).inc()
        
        # Gauge
        metrics.gauge("active_agents").set(10)
        
        # Histogram
        metrics.histogram("task_duration_ms").observe(150.0)
        
        # Export for Prometheus
        prometheus_data = metrics.export_prometheus()
        ```
    """

    def __init__(self) -> None:
        self._counters: dict[str, dict[tuple, float]] = defaultdict(lambda: defaultdict(float))
        self._gauges: dict[str, dict[tuple, float]] = defaultdict(dict)
        self._histograms: dict[str, dict[tuple, list[float]]] = defaultdict(lambda: defaultdict(list))
        
        self._lock = threading.Lock()
        self._start_time = time.time()
        
        self._logger = logger
    
    def counter(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        description: str = "",
    ) -> Counter:
        """Get or create a counter metric."""
        return Counter(name, labels or {}, self)
    
    def gauge(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        description: str = "",
    ) -> Gauge:
        """Get or create a gauge metric."""
        return Gauge(name, labels or {}, self)
    
    def histogram(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        buckets: list[float] | None = None,
        description: str = "",
    ) -> Histogram:
        """Get or create a histogram metric."""
        return Histogram(name, labels or {}, buckets, self)
    
    def _inc_counter(self, name: str, labels: dict[str, str], value: float = 1) -> None:
        """Increment a counter."""
        label_tuple = tuple(sorted(labels.items()))
        with self._lock:
            self._counters[name][label_tuple] += value
    
    def _set_gauge(self, name: str, labels: dict[str, str], value: float) -> None:
        """Set a gauge value."""
        label_tuple = tuple(sorted(labels.items()))
        with self._lock:
            self._gauges[name][label_tuple] = value
    
    def _observe_histogram(
        self,
        name: str,
        labels: dict[str, str],
        value: float,
    ) -> None:
        """Observe a histogram value."""
        label_tuple = tuple(sorted(labels.items()))
        with self._lock:
            self._histograms[name][label_tuple].append(value)
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        
        with self._lock:
            # Counters
            for name, values in self._counters.items():
                lines.append(f"# TYPE {name} counter")
                for label_tuple, value in values.items():
                    labels_str = ",".join(f'{k}="{v}"' for k, v in label_tuple)
                    if labels_str:
                        lines.append(f"{name}{{{labels_str}}} {value}")
                    else:
                        lines.append(f"{name} {value}")
            
            # Gauges
            for name, values in self._gauges.items():
                lines.append(f"# TYPE {name} gauge")
                for label_tuple, value in values.items():
                    labels_str = ",".join(f'{k}="{v}"' for k, v in label_tuple)
                    if labels_str:
                        lines.append(f"{name}{{{labels_str}}} {value}")
                    else:
                        lines.append(f"{name} {value}")
            
            # Histograms (simplified)
            for name, values in self._histograms.items():
                lines.append(f"# TYPE {name} histogram")
                for label_tuple, observations in values.items():
                    labels_str = ",".join(f'{k}="{v}"' for k, v in label_tuple)
                    count = len(observations)
                    total = sum(observations)
                    
                    if labels_str:
                        lines.append(f"{name}_count{{{labels_str}}} {count}")
                        lines.append(f"{name}_sum{{{labels_str}}} {total}")
                    else:
                        lines.append(f"{name}_count {count}")
                        lines.append(f"{name}_sum {total}")
        
        return "\n".join(lines)
    
    def get_stats(self) -> dict[str, Any]:
        """Get collector statistics."""
        with self._lock:
            return {
                "counters": len(self._counters),
                "gauges": len(self._gauges),
                "histograms": len(self._histograms),
                "uptime_seconds": time.time() - self._start_time,
            }


class Counter:
    """Counter metric."""

    def __init__(
        self,
        name: str,
        labels: dict[str, str],
        collector: MetricsCollector,
    ) -> None:
        self.name = name
        self.labels = labels
        self._collector = collector
    
    def inc(self, value: float = 1) -> None:
        """Increment counter."""
        self._collector._inc_counter(self.name, self.labels, value)


class Gauge:
    """Gauge metric."""

    def __init__(
        self,
        name: str,
        labels: dict[str, str],
        collector: MetricsCollector,
    ) -> None:
        self.name = name
        self.labels = labels
        self._collector = collector
    
    def set(self, value: float) -> None:
        """Set gauge value."""
        self._collector._set_gauge(self.name, self.labels, value)
    
    def inc(self, value: float = 1) -> None:
        """Increment gauge."""
        # Note: This is not atomic
        current = self._collector._gauges[self.name].get(
            tuple(sorted(self.labels.items())), 0
        )
        self._collector._set_gauge(self.name, self.labels, current + value)
    
    def dec(self, value: float = 1) -> None:
        """Decrement gauge."""
        self.inc(-value)


class Histogram:
    """Histogram metric."""

    def __init__(
        self,
        name: str,
        labels: dict[str, str],
        buckets: list[float] | None,
        collector: MetricsCollector,
    ) -> None:
        self.name = name
        self.labels = labels
        self.buckets = buckets or [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
        self._collector = collector
    
    def observe(self, value: float) -> None:
        """Observe a value."""
        self._collector._observe_histogram(self.name, self.labels, value)
