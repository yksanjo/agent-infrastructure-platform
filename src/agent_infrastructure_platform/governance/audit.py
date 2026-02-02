"""Audit logging for agent actions."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import structlog

from agent_infrastructure_platform.common.types import AgentID, TaskID

logger = structlog.get_logger()


@dataclass
class AuditEvent:
    """An auditable event."""

    id: str = field(default_factory=lambda: f"evt-{int(time.time()*1000)}-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}")
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Actor
    agent_id: AgentID | None = None
    user_id: str | None = None
    session_id: str | None = None
    
    # Action
    action: str = ""  # e.g., "task.execute", "capability.call"
    resource: str = ""  # e.g., "task://123", "capability://search"
    
    # Details
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] | None = None
    
    # Result
    success: bool = True
    error: str | None = None
    
    # Metadata
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Integrity
    previous_hash: str | None = None  # For blockchain-style chaining
    event_hash: str | None = None  # Hash of this event
    
    def compute_hash(self) -> str:
        """Compute hash of event for integrity verification."""
        data = {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "agent_id": self.agent_id,
            "action": self.action,
            "resource": self.resource,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "success": self.success,
            "previous_hash": self.previous_hash,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class AuditLogger:
    """
    Immutable audit trail for all agent decisions and interactions.
    
    Features:
    - Tamper-evident logging with hash chaining
    - Structured event format
    - Efficient querying
    - Compliance-ready exports
    
    Example:
        ```python
        audit = AuditLogger()
        
        # Log an event
        event = await audit.log(
            agent_id="agent-1",
            action="task.execute",
            resource="task://123",
            input_data={"query": "Hello"},
            output_data={"result": "Hi!"},
            success=True,
        )
        
        # Query events
        events = await audit.query(
            agent_id="agent-1",
            start_time=datetime.now() - timedelta(days=7),
        )
        
        # Verify integrity
        assert await audit.verify_chain()
        ```
    """

    def __init__(self, storage_backend: Any | None = None) -> None:
        self.storage = storage_backend or []
        self._last_hash: str | None = None
        self._event_count = 0
        
        self._logger = logger
    
    async def log(
        self,
        action: str,
        resource: str = "",
        agent_id: AgentID | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        success: bool = True,
        error: str | None = None,
        duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """
        Log an auditable event.
        
        Args:
            action: Action performed
            resource: Resource affected
            agent_id: Acting agent
            user_id: Acting user (if any)
            session_id: Session ID
            input_data: Input parameters
            output_data: Output results
            success: Whether action succeeded
            error: Error message if failed
            duration_ms: Execution duration
            metadata: Additional metadata
            
        Returns:
            Logged event
        """
        event = AuditEvent(
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            action=action,
            resource=resource,
            input_data=input_data or {},
            output_data=output_data,
            success=success,
            error=error,
            duration_ms=duration_ms,
            metadata=metadata or {},
            previous_hash=self._last_hash,
        )
        
        # Compute hash for integrity
        event.event_hash = event.compute_hash()
        self._last_hash = event.event_hash
        
        # Store event
        await self._store(event)
        
        self._event_count += 1
        
        self._logger.debug(
            "audit_event_logged",
            event_id=event.id,
            action=action,
            agent_id=agent_id,
        )
        
        return event
    
    async def _store(self, event: AuditEvent) -> None:
        """Store event in backend."""
        if isinstance(self.storage, list):
            self.storage.append(event)
        else:
            # Assume storage backend
            await self.storage.store(f"audit:{event.id}", event)
    
    async def query(
        self,
        agent_id: AgentID | None = None,
        action: str | None = None,
        resource: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        success: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        """
        Query audit events.
        
        Args:
            agent_id: Filter by agent
            action: Filter by action
            resource: Filter by resource
            start_time: Filter by start time
            end_time: Filter by end time
            success: Filter by success status
            limit: Maximum results
            offset: Skip first N results
            
        Returns:
            Matching events
        """
        events = []
        
        if isinstance(self.storage, list):
            for event in self.storage:
                if agent_id and event.agent_id != agent_id:
                    continue
                if action and event.action != action:
                    continue
                if resource and event.resource != resource:
                    continue
                if start_time and event.timestamp < start_time:
                    continue
                if end_time and event.timestamp > end_time:
                    continue
                if success is not None and event.success != success:
                    continue
                
                events.append(event)
        else:
            # Query from backend
            pass
        
        # Sort by timestamp (newest first)
        events.sort(key=lambda e: e.timestamp, reverse=True)
        
        return events[offset:offset + limit]
    
    async def verify_chain(self) -> tuple[bool, str | None]:
        """
        Verify integrity of the audit chain.
        
        Returns:
            (is_valid, first_broken_event_id or None)
        """
        if isinstance(self.storage, list):
            events = sorted(self.storage, key=lambda e: e.timestamp)
        else:
            events = []
        
        if not events:
            return True, None
        
        previous_hash: str | None = None
        
        for event in events:
            # Check previous hash link
            if event.previous_hash != previous_hash:
                return False, event.id
            
            # Verify event hash
            expected_hash = event.compute_hash()
            if event.event_hash != expected_hash:
                return False, event.id
            
            previous_hash = event.event_hash
        
        return True, None
    
    async def export(
        self,
        format: str = "json",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> str:
        """
        Export audit log for compliance.
        
        Args:
            format: Export format (json, csv)
            start_time: Start of range
            end_time: End of range
            
        Returns:
            Exported data
        """
        events = await self.query(
            start_time=start_time,
            end_time=end_time,
            limit=1000000,  # Large limit for export
        )
        
        if format == "json":
            data = [asdict(e) for e in events]
            return json.dumps(data, default=str, indent=2)
        
        elif format == "csv":
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header
            writer.writerow([
                "id", "timestamp", "agent_id", "action", "resource",
                "success", "error", "duration_ms", "event_hash",
            ])
            
            # Data
            for event in events:
                writer.writerow([
                    event.id,
                    event.timestamp.isoformat(),
                    event.agent_id,
                    event.action,
                    event.resource,
                    event.success,
                    event.error,
                    event.duration_ms,
                    event.event_hash,
                ])
            
            return output.getvalue()
        
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def get_stats(self) -> dict[str, Any]:
        """Get audit logger statistics."""
        return {
            "total_events": self._event_count,
            "last_hash": self._last_hash,
        }
