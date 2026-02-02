"""Kill Switch for emergency agent termination."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Awaitable, Callable

import structlog

from agent_infrastructure_platform.common.exceptions import KillSwitchActivated
from agent_infrastructure_platform.common.types import AgentID

logger = structlog.get_logger()


class KillSwitchLevel(Enum):
    """Levels of kill switch activation."""

    AGENT = auto()  # Single agent
    SWARM = auto()  # Group of agents
    NAMESPACE = auto()  # Entire namespace
    GLOBAL = auto()  # All agents


class KillSwitchReason(Enum):
    """Reasons for kill switch activation."""

    POLICY_VIOLATION = auto()
    SECURITY_BREACH = auto()
    RESOURCE_EXHAUSTION = auto()
    MANUAL_OVERRIDE = auto()
    CASCADE_FAILURE = auto()
    EMERGENCY_STOP = auto()


@dataclass
class KillSwitchEvent:
    """A kill switch activation event."""

    id: str = field(default_factory=lambda: f"kill-{datetime.utcnow().timestamp()}")
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    level: KillSwitchLevel = KillSwitchLevel.AGENT
    target: str = ""  # Agent ID, swarm ID, or namespace
    reason: KillSwitchReason = KillSwitchReason.MANUAL_OVERRIDE
    
    triggered_by: str = ""  # User or system that triggered
    explanation: str = ""
    
    # Impact
    agents_terminated: int = 0
    tasks_cancelled: int = 0


class KillSwitch:
    """
    Distributed circuit breaker for rogue agent containment.
    
    Features:
    - Multi-level activation (agent, swarm, namespace, global)
    - Immediate termination
    - Audit logging
    - Automatic notification
    
    Example:
        ```python
        killswitch = KillSwitch()
        
        # Monitor agents
        killswitch.monitor_agent(agent_id, agent_task)
        
        # Activate kill switch
        await killswitch.activate(
            level=KillSwitchLevel.AGENT,
            target="rogue-agent-1",
            reason=KillSwitchReason.POLICY_VIOLATION,
            explanation="Agent exceeded resource limits",
        )
        
        # Check if agent is killed
        if killswitch.is_killed(agent_id):
            raise KillSwitchActivated()
        ```
    """

    def __init__(self) -> None:
        self._killed_agents: set[AgentID] = set()
        self._killed_swarms: set[str] = set()
        self._killed_namespaces: set[str] = set()
        self._global_kill: bool = False
        
        # Monitored agents
        self._monitored: dict[AgentID, asyncio.Task] = {}
        self._agent_metadata: dict[AgentID, dict[str, Any]] = {}
        
        # Event history
        self._events: list[KillSwitchEvent] = []
        
        # Callbacks
        self._on_activate: list[Callable[[KillSwitchEvent], Awaitable[None]]] = []
        
        self._logger = logger
    
    def on_activate(
        self,
        callback: Callable[[KillSwitchEvent], Awaitable[None]],
    ) -> Callable[[KillSwitchEvent], Awaitable[None]]:
        """Register a callback for kill switch activation."""
        self._on_activate.append(callback)
        return callback
    
    def monitor_agent(
        self,
        agent_id: AgentID,
        task: asyncio.Task,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Monitor an agent task for kill switch activation.
        
        Args:
            agent_id: Agent to monitor
            task: Agent's main task
            metadata: Additional metadata
        """
        self._monitored[agent_id] = task
        self._agent_metadata[agent_id] = metadata or {}
        
        self._logger.debug("agent_monitored", agent_id=agent_id)
    
    def unmonitor_agent(self, agent_id: AgentID) -> bool:
        """Stop monitoring an agent."""
        if agent_id in self._monitored:
            del self._monitored[agent_id]
            del self._agent_metadata[agent_id]
            return True
        return False
    
    async def activate(
        self,
        level: KillSwitchLevel,
        target: str,
        reason: KillSwitchReason,
        triggered_by: str = "system",
        explanation: str = "",
    ) -> KillSwitchEvent:
        """
        Activate the kill switch.
        
        Args:
            level: Activation level
            target: Target ID (agent, swarm, or namespace)
            reason: Reason for activation
            triggered_by: Who/what triggered
            explanation: Detailed explanation
            
        Returns:
            Kill switch event
        """
        event = KillSwitchEvent(
            level=level,
            target=target,
            reason=reason,
            triggered_by=triggered_by,
            explanation=explanation,
        )
        
        self._logger.critical(
            "killswitch_activated",
            level=level.name,
            target=target,
            reason=reason.name,
        )
        
        # Apply kills
        if level == KillSwitchLevel.GLOBAL:
            self._global_kill = True
            event.agents_terminated = len(self._monitored)
            for agent_id, task in list(self._monitored.items()):
                self._killed_agents.add(agent_id)
                task.cancel()
        
        elif level == KillSwitchLevel.NAMESPACE:
            self._killed_namespaces.add(target)
            # Kill all agents in namespace
            for agent_id, metadata in self._agent_metadata.items():
                if metadata.get("namespace") == target:
                    self._killed_agents.add(agent_id)
                    if agent_id in self._monitored:
                        self._monitored[agent_id].cancel()
                        event.agents_terminated += 1
        
        elif level == KillSwitchLevel.SWARM:
            self._killed_swarms.add(target)
            # Kill all agents in swarm
            for agent_id, metadata in self._agent_metadata.items():
                if metadata.get("swarm") == target:
                    self._killed_agents.add(agent_id)
                    if agent_id in self._monitored:
                        self._monitored[agent_id].cancel()
                        event.agents_terminated += 1
        
        elif level == KillSwitchLevel.AGENT:
            self._killed_agents.add(AgentID(target))
            if target in self._monitored:
                self._monitored[target].cancel()
                event.agents_terminated = 1
        
        # Store event
        self._events.append(event)
        
        # Notify callbacks
        for callback in self._on_activate:
            try:
                await callback(event)
            except Exception as e:
                self._logger.error("killswitch_callback_error", error=str(e))
        
        return event
    
    async def deactivate(
        self,
        level: KillSwitchLevel,
        target: str,
    ) -> bool:
        """
        Deactivate the kill switch for a target.
        
        Args:
            level: Activation level
            target: Target ID
            
        Returns:
            True if deactivated
        """
        if level == KillSwitchLevel.GLOBAL:
            self._global_kill = False
            self._logger.info("killswitch_global_deactivated")
            return True
        
        elif level == KillSwitchLevel.NAMESPACE:
            if target in self._killed_namespaces:
                self._killed_namespaces.remove(target)
                self._logger.info("killswitch_namespace_deactivated", namespace=target)
                return True
        
        elif level == KillSwitchLevel.SWARM:
            if target in self._killed_swarms:
                self._killed_swarms.remove(target)
                self._logger.info("killswitch_swarm_deactivated", swarm=target)
                return True
        
        elif level == KillSwitchLevel.AGENT:
            agent_id = AgentID(target)
            if agent_id in self._killed_agents:
                self._killed_agents.remove(agent_id)
                self._logger.info("killswitch_agent_deactivated", agent_id=target)
                return True
        
        return False
    
    def is_killed(self, agent_id: AgentID) -> bool:
        """
        Check if an agent is killed.
        
        Args:
            agent_id: Agent to check
            
        Returns:
            True if agent should stop
        """
        if self._global_kill:
            return True
        
        if agent_id in self._killed_agents:
            return True
        
        metadata = self._agent_metadata.get(agent_id, {})
        
        if metadata.get("namespace") in self._killed_namespaces:
            return True
        
        if metadata.get("swarm") in self._killed_swarms:
            return True
        
        return False
    
    def check_or_raise(self, agent_id: AgentID) -> None:
        """Raise KillSwitchActivated if agent is killed."""
        if self.is_killed(agent_id):
            raise KillSwitchActivated(f"Kill switch active for agent: {agent_id}")
    
    def get_status(self) -> dict[str, Any]:
        """Get kill switch status."""
        return {
            "global_kill": self._global_kill,
            "killed_namespaces": list(self._killed_namespaces),
            "killed_swarms": list(self._killed_swarms),
            "killed_agents": list(self._killed_agents),
            "monitored_agents": len(self._monitored),
            "total_events": len(self._events),
            "latest_event": self._events[-1] if self._events else None,
        }
    
    async def get_events(
        self,
        level: KillSwitchLevel | None = None,
        reason: KillSwitchReason | None = None,
        limit: int = 100,
    ) -> list[KillSwitchEvent]:
        """Get kill switch activation events."""
        events = self._events
        
        if level:
            events = [e for e in events if e.level == level]
        
        if reason:
            events = [e for e in events if e.reason == reason]
        
        return events[-limit:]
