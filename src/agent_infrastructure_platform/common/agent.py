"""Base Agent class for the Agent Infrastructure Platform."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent_infrastructure_platform.common.decorators import trace_span
from agent_infrastructure_platform.common.exceptions import AgentUnavailableError
from agent_infrastructure_platform.common.types import (
    AgentID,
    AgentState,
    Capability,
    Context,
    HealthStatus,
    Message,
    MessageType,
    ProtocolType,
    SessionID,
    Task,
)

logger = structlog.get_logger()


class AgentConfig(BaseModel):
    """Configuration for an Agent."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    version: str = "1.0.0"
    
    # Protocol support
    supported_protocols: list[ProtocolType] = Field(default_factory=lambda: [ProtocolType.A2A])
    
    # Resource limits
    max_concurrent_tasks: int = 10
    task_timeout_seconds: float = 300.0
    
    # Health check
    health_check_interval_seconds: float = 30.0
    
    # Retry settings
    max_retries: int = 3
    retry_base_delay: float = 1.0


class AgentMetrics(BaseModel):
    """Runtime metrics for an agent."""

    tasks_completed: int = 0
    tasks_failed: int = 0
    messages_received: int = 0
    messages_sent: int = 0
    total_execution_time_ms: float = 0.0
    last_active: datetime | None = None
    error_count: int = 0


class Agent(ABC):
    """
    Base class for all agents in the Agent Infrastructure Platform.
    
    This class provides the foundation for building agents that can:
    - Register and advertise capabilities
    - Handle tasks and messages
    - Participate in multi-agent protocols (MCP, A2A, ACP, ANP)
    - Report health and metrics
    - Manage state and lifecycle
    
    Example:
        ```python
        class MyAgent(Agent):
            def __init__(self):
                super().__init__(AgentConfig(name="my-agent"))
                self.register_capability(Capability(
                    name="text-generation",
                    category=CapabilityCategory.COGNITIVE,
                ))
            
            async def handle_task(self, task: Task, ctx: Context) -> Task:
                # Implement task handling
                task.output_data = {"result": "Hello!"}
                return task
        ```
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.id = AgentID(f"{config.name}-{uuid4().hex[:8]}")
        self.state = AgentState.INITIALIZING
        self.capabilities: dict[str, Capability] = {}
        self.metrics = AgentMetrics()
        
        # Task management
        self._active_tasks: dict[str, Task] = {}
        self._task_semaphore = asyncio.Semaphore(config.max_concurrent_tasks)
        self._task_handlers: dict[str, Callable[[Task, Context], Awaitable[Task]]] = {}
        
        # Message handling
        self._message_handlers: dict[str, Callable[[Message, Context], Awaitable[Message | None]]] = {}
        
        # Background tasks
        self._health_check_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        
        # Logger
        self._logger = logger.bind(agent_id=self.id, agent_name=config.name)
    
    #region Lifecycle
    
    async def initialize(self) -> None:
        """Initialize the agent. Override for custom initialization."""
        self._logger.info("agent_initializing")
        
        # Start health check loop
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        
        self.state = AgentState.IDLE
        self._logger.info("agent_initialized", state=self.state)
    
    async def shutdown(self, timeout: float = 30.0) -> None:
        """Gracefully shut down the agent."""
        self._logger.info("agent_shutting_down", timeout=timeout)
        self.state = AgentState.SHUTTING_DOWN
        self._shutdown_event.set()
        
        # Cancel active tasks
        if self._active_tasks:
            self._logger.warning(
                "cancelling_active_tasks",
                count=len(self._active_tasks),
            )
            for task in self._active_tasks.values():
                # Signal cancellation (actual implementation depends on task structure)
                pass
        
        # Wait for health check to stop
        if self._health_check_task:
            try:
                await asyncio.wait_for(self._health_check_task, timeout=timeout)
            except asyncio.TimeoutError:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
        
        self.state = AgentState.OFFLINE
        self._logger.info("agent_shutdown_complete")
    
    @asynccontextmanager
    async def session(self):
        """Context manager for agent lifecycle."""
        await self.initialize()
        try:
            yield self
        finally:
            await self.shutdown()
    
    #endregion
    
    #region Capabilities
    
    def register_capability(self, capability: Capability) -> None:
        """Register a capability this agent can provide."""
        self.capabilities[capability.name] = capability
        self._logger.debug("capability_registered", capability=capability.name)
    
    def unregister_capability(self, name: str) -> None:
        """Unregister a capability."""
        if name in self.capabilities:
            del self.capabilities[name]
            self._logger.debug("capability_unregistered", capability=name)
    
    def has_capability(self, name: str) -> bool:
        """Check if agent has a specific capability."""
        return name in self.capabilities
    
    def list_capabilities(self) -> list[Capability]:
        """List all registered capabilities."""
        return list(self.capabilities.values())
    
    #endregion
    
    #region Task Handling
    
    @abstractmethod
    async def handle_task(self, task: Task, ctx: Context) -> Task:
        """
        Handle a task. Must be implemented by subclasses.
        
        Args:
            task: The task to handle
            ctx: Execution context
            
        Returns:
            The completed task with results
        """
        raise NotImplementedError
    
    def register_task_handler(
        self,
        task_type: str,
        handler: Callable[[Task, Context], Awaitable[Task]],
    ) -> None:
        """Register a handler for a specific task type."""
        self._task_handlers[task_type] = handler
    
    @trace_span()
    async def execute_task(self, task: Task, ctx: Context | None = None) -> Task:
        """
        Execute a task with resource management.
        
        Args:
            task: The task to execute
            ctx: Optional execution context
            
        Returns:
            The completed task
        """
        if self.state not in (AgentState.IDLE, AgentState.BUSY):
            raise AgentUnavailableError(f"Agent is {self.state.value}")
        
        ctx = ctx or Context()
        task.assigned_to = self.id
        task.started_at = datetime.utcnow()
        self._active_tasks[task.id] = task
        
        self._logger.info(
            "task_starting",
            task_id=task.id,
            task_name=task.name,
        )
        
        async with self._task_semaphore:
            self.state = AgentState.BUSY
            start_time = asyncio.get_event_loop().time()
            
            try:
                # Check for specific handler
                handler = self._task_handlers.get(task.name)
                if handler:
                    result = await handler(task, ctx)
                else:
                    result = await self.handle_task(task, ctx)
                
                result.status = TaskStatus.COMPLETED
                self.metrics.tasks_completed += 1
                
            except Exception as e:
                self._logger.error(
                    "task_failed",
                    task_id=task.id,
                    error=str(e),
                )
                task.status = TaskStatus.FAILED
                task.output_data = {"error": str(e)}
                self.metrics.tasks_failed += 1
                self.metrics.error_count += 1
                raise
            
            finally:
                duration = (asyncio.get_event_loop().time() - start_time) * 1000
                self.metrics.total_execution_time_ms += duration
                self.metrics.last_active = datetime.utcnow()
                del self._active_tasks[task.id]
                
                if not self._active_tasks:
                    self.state = AgentState.IDLE
                
                task.completed_at = datetime.utcnow()
                self._logger.info(
                    "task_completed",
                    task_id=task.id,
                    status=result.status.value,
                    duration_ms=duration,
                )
        
        return result
    
    #endregion
    
    #region Message Handling
    
    @abstractmethod
    async def handle_message(self, message: Message, ctx: Context) -> Message | None:
        """
        Handle an incoming message. Must be implemented by subclasses.
        
        Args:
            message: The incoming message
            ctx: Execution context
            
        Returns:
            Response message or None
        """
        raise NotImplementedError
    
    def register_message_handler(
        self,
        message_type: str,
        handler: Callable[[Message, Context], Awaitable[Message | None]],
    ) -> None:
        """Register a handler for a specific message type."""
        self._message_handlers[message_type] = handler
    
    async def send_message(
        self,
        recipient: AgentID,
        content: Any,
        message_type: MessageType = MessageType.REQUEST,
        protocol: ProtocolType = ProtocolType.A2A,
        ctx: Context | None = None,
    ) -> Message:
        """
        Send a message to another agent.
        
        Args:
            recipient: Target agent ID
            content: Message content
            message_type: Type of message
            protocol: Protocol to use
            ctx: Execution context
            
        Returns:
            The sent message
        """
        message = Message(
            type=message_type,
            protocol=protocol,
            sender=self.id,
            recipient=recipient,
            content=content,
        )
        
        self.metrics.messages_sent += 1
        self._logger.debug(
            "message_sent",
            recipient=recipient,
            message_type=message_type.value,
        )
        
        return message
    
    async def receive_message(self, message: Message, ctx: Context | None = None) -> Message | None:
        """Receive and process an incoming message."""
        ctx = ctx or Context()
        self.metrics.messages_received += 1
        
        self._logger.debug(
            "message_received",
            sender=message.sender,
            message_type=message.type.value,
        )
        
        # Check for specific handler
        handler = self._message_handlers.get(message.type.value)
        if handler:
            return await handler(message, ctx)
        
        return await self.handle_message(message, ctx)
    
    #endregion
    
    #region Health & Metrics
    
    async def health_check(self) -> HealthStatus:
        """
        Perform health check. Override for custom health checks.
        
        Returns:
            Health status
        """
        checks = {
            "state": self.state not in (AgentState.ERROR, AgentState.OFFLINE),
            "tasks": len(self._active_tasks) <= self.config.max_concurrent_tasks,
        }
        
        metrics = {
            "active_tasks": len(self._active_tasks),
            "total_completed": self.metrics.tasks_completed,
            "total_failed": self.metrics.tasks_failed,
            "error_rate": (
                self.metrics.tasks_failed / max(self.metrics.tasks_completed, 1)
            ),
        }
        
        all_healthy = all(checks.values())
        
        return HealthStatus(
            status="healthy" if all_healthy else "degraded",
            checks=checks,
            metrics=metrics,
        )
    
    async def _health_check_loop(self) -> None:
        """Background task for periodic health checks."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.config.health_check_interval_seconds,
                )
            except asyncio.TimeoutError:
                health = await self.health_check()
                if health.status != "healthy":
                    self._logger.warning(
                        "health_check_degraded",
                        status=health.status,
                        checks=health.checks,
                    )
    
    def get_metrics(self) -> AgentMetrics:
        """Get current metrics."""
        return self.metrics
    
    #endregion
    
    #region Streaming
    
    async def stream_response(
        self,
        request: Message,
        ctx: Context,
    ) -> AsyncIterator[Message]:
        """
        Stream a response to a request. Override for streaming support.
        
        Args:
            request: The incoming request
            ctx: Execution context
            
        Yields:
            Response message chunks
        """
        # Default implementation: yield single response
        response = await self.handle_message(request, ctx)
        if response:
            yield response
    
    #endregion
