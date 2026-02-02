"""Task Orchestrator for multi-agent workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

import structlog

from agent_infrastructure_platform.common.types import (
    AgentID,
    Context,
    Task,
    TaskPriority,
    TaskStatus,
)
from agent_infrastructure_platform.orchestration.circuit_breaker import CircuitBreaker

logger = structlog.get_logger()


@dataclass
class TaskPlan:
    """A plan for executing a complex task."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    tasks: list[Task] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)  # task_id -> dependencies
    parallel_groups: list[list[str]] = field(default_factory=list)  # Groups that can run in parallel


@dataclass
class ExecutionResult:
    """Result of task execution."""
    
    task_id: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    retry_count: int = 0


class Orchestrator:
    """
    Hierarchical orchestrator for multi-agent task execution.
    
    Features:
    - Task decomposition and planning
    - Dependency management
    - Parallel execution
    - Retry logic with circuit breakers
    - Resource allocation
    
    Example:
        ```python
        orchestrator = Orchestrator()
        
        # Register agents
        orchestrator.register_agent(agent_1, ["text-generation"])
        orchestrator.register_agent(agent_2, ["summarization"])
        
        # Create execution plan
        plan = await orchestrator.create_plan(
            goal="Write a blog post about AI",
            required_capabilities=["text-generation", "summarization"],
        )
        
        # Execute
        results = await orchestrator.execute(plan)
        ```
    """

    def __init__(
        self,
        max_concurrent_tasks: int = 100,
        default_timeout: float = 300.0,
        enable_circuit_breaker: bool = True,
    ) -> None:
        self.max_concurrent_tasks = max_concurrent_tasks
        self.default_timeout = default_timeout
        self.enable_circuit_breaker = enable_circuit_breaker
        
        # Agent registry
        self._agents: dict[AgentID, Any] = {}  # AgentID -> Agent instance
        self._agent_capabilities: dict[AgentID, list[str]] = {}
        self._agent_health: dict[AgentID, bool] = {}
        
        # Task tracking
        self._active_tasks: dict[str, Task] = {}
        self._task_results: dict[str, ExecutionResult] = {}
        
        # Circuit breakers
        self._circuit_breakers: dict[AgentID, CircuitBreaker] = {}
        
        # Semaphore for concurrency control
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        
        self._logger = logger
    
    def register_agent(
        self,
        agent: Any,
        capabilities: list[str],
    ) -> None:
        """
        Register an agent with the orchestrator.
        
        Args:
            agent: Agent instance
            capabilities: List of capability names
        """
        agent_id = getattr(agent, "id", str(uuid4()))
        self._agents[agent_id] = agent
        self._agent_capabilities[agent_id] = capabilities
        self._agent_health[agent_id] = True
        
        if self.enable_circuit_breaker:
            self._circuit_breakers[agent_id] = CircuitBreaker()
        
        self._logger.info(
            "agent_registered",
            agent_id=agent_id,
            capabilities=capabilities,
        )
    
    def unregister_agent(self, agent_id: AgentID) -> bool:
        """Unregister an agent."""
        if agent_id in self._agents:
            del self._agents[agent_id]
            del self._agent_capabilities[agent_id]
            del self._agent_health[agent_id]
            
            if agent_id in self._circuit_breakers:
                del self._circuit_breakers[agent_id]
            
            return True
        return False
    
    def find_agents_for_task(self, required_capabilities: list[str]) -> list[AgentID]:
        """
        Find agents that can handle required capabilities.
        
        Returns agents sorted by health and circuit breaker state.
        """
        candidates = []
        
        for agent_id, capabilities in self._agent_capabilities.items():
            # Check if agent has all required capabilities
            if not all(cap in capabilities for cap in required_capabilities):
                continue
            
            # Check health
            if not self._agent_health.get(agent_id, True):
                continue
            
            # Check circuit breaker
            if self.enable_circuit_breaker:
                cb = self._circuit_breakers.get(agent_id)
                if cb and not cb.can_execute():
                    continue
            
            candidates.append(agent_id)
        
        return candidates
    
    async def create_plan(
        self,
        goal: str,
        required_capabilities: list[str],
        max_steps: int = 10,
    ) -> TaskPlan:
        """
        Create an execution plan for a goal.
        
        In a production system, this would use an LLM or planner
        to decompose the goal into subtasks.
        """
        # Simplified planning: create linear sequence
        plan = TaskPlan(name=f"Plan for: {goal[:50]}")
        
        # Create tasks for each capability
        for i, capability in enumerate(required_capabilities):
            task = Task(
                id=f"task-{i}-{uuid4().hex[:8]}",
                name=f"Execute {capability}",
                goal=f"Use {capability} capability",
                required_capabilities=[{"name": capability, "category": "tool", "version": "1.0.0"}],
            )
            plan.tasks.append(task)
            
            # Add dependency on previous task
            if i > 0:
                plan.dependencies[task.id] = [plan.tasks[i-1].id]
        
        return plan
    
    async def execute(
        self,
        plan: TaskPlan,
        context: Context | None = None,
        on_progress: Callable[[str, ExecutionResult], Awaitable[None]] | None = None,
    ) -> dict[str, ExecutionResult]:
        """
        Execute a task plan.
        
        Args:
            plan: Execution plan
            context: Execution context
            on_progress: Callback for progress updates
            
        Returns:
            Mapping of task_id to result
        """
        context = context or Context()
        results: dict[str, ExecutionResult] = {}
        completed: set[str] = set()
        failed: set[str] = set()
        
        self._logger.info(
            "plan_execution_started",
            plan_id=plan.id,
            task_count=len(plan.tasks),
        )
        
        # Build dependency graph
        dependents: dict[str, list[str]] = {}  # task_id -> tasks that depend on it
        for task_id, deps in plan.dependencies.items():
            for dep in deps:
                if dep not in dependents:
                    dependents[dep] = []
                dependents[dep].append(task_id)
        
        # Track pending dependencies
        pending_deps: dict[str, set[str]] = {
            task.id: set(plan.dependencies.get(task.id, []))
            for task in plan.tasks
        }
        
        # Execute tasks as dependencies are satisfied
        while len(completed) + len(failed) < len(plan.tasks):
            # Find tasks ready to execute
            ready = [
                task for task in plan.tasks
                if task.id not in completed and task.id not in failed
                and not pending_deps.get(task.id, set())
            ]
            
            if not ready:
                # Check for deadlock
                remaining = [
                    task for task in plan.tasks
                    if task.id not in completed and task.id not in failed
                ]
                if remaining:
                    self._logger.error("dependency_deadlock", remaining=[t.id for t in remaining])
                    for task in remaining:
                        failed.add(task.id)
                        results[task.id] = ExecutionResult(
                            task_id=task.id,
                            success=False,
                            error="Dependency deadlock",
                        )
                break
            
            # Execute ready tasks in parallel
            tasks_to_run = ready[:self.max_concurrent_tasks]
            coros = [self._execute_task(task, context) for task in tasks_to_run]
            task_results = await asyncio.gather(*coros, return_exceptions=True)
            
            # Process results
            for task, result in zip(tasks_to_run, task_results):
                if isinstance(result, Exception):
                    result = ExecutionResult(
                        task_id=task.id,
                        success=False,
                        error=str(result),
                    )
                
                results[task.id] = result
                
                if result.success:
                    completed.add(task.id)
                else:
                    failed.add(task.id)
                
                # Notify progress
                if on_progress:
                    await on_progress(task.id, result)
                
                # Update dependencies for dependent tasks
                for dependent in dependents.get(task.id, []):
                    if task.id in pending_deps.get(dependent, set()):
                        pending_deps[dependent].remove(task.id)
        
        self._logger.info(
            "plan_execution_completed",
            plan_id=plan.id,
            completed=len(completed),
            failed=len(failed),
        )
        
        return results
    
    async def _execute_task(
        self,
        task: Task,
        context: Context,
    ) -> ExecutionResult:
        """Execute a single task."""
        start_time = asyncio.get_event_loop().time()
        
        async with self._semaphore:
            # Find capable agent
            required_caps = [c.name for c in task.required_capabilities]
            candidates = self.find_agents_for_task(required_caps)
            
            if not candidates:
                return ExecutionResult(
                    task_id=task.id,
                    success=False,
                    error=f"No agent found for capabilities: {required_caps}",
                )
            
            # Try agents until one succeeds
            for agent_id in candidates:
                agent = self._agents[agent_id]
                cb = self._circuit_breakers.get(agent_id)
                
                try:
                    # Check circuit breaker
                    if cb and not cb.can_execute():
                        continue
                    
                    # Execute
                    self._active_tasks[task.id] = task
                    
                    if hasattr(agent, 'execute_task'):
                        result_task = await asyncio.wait_for(
                            agent.execute_task(task, context),
                            timeout=self.default_timeout,
                        )
                        success = result_task.status == TaskStatus.COMPLETED
                        output = result_task.output_data
                    else:
                        # Fallback: call agent directly
                        output = await agent(task.input_data)
                        success = True
                    
                    del self._active_tasks[task.id]
                    
                    duration = (asyncio.get_event_loop().time() - start_time) * 1000
                    
                    # Record success in circuit breaker
                    if cb:
                        cb.record_success()
                    
                    return ExecutionResult(
                        task_id=task.id,
                        success=success,
                        output=output,
                        duration_ms=duration,
                    )
                    
                except Exception as e:
                    self._logger.error(
                        "task_execution_failed",
                        task_id=task.id,
                        agent_id=agent_id,
                        error=str(e),
                    )
                    
                    # Record failure in circuit breaker
                    if cb:
                        cb.record_failure()
                    
                    continue
            
            # All agents failed
            duration = (asyncio.get_event_loop().time() - start_time) * 1000
            return ExecutionResult(
                task_id=task.id,
                success=False,
                error="All agents failed to execute task",
                duration_ms=duration,
                retry_count=len(candidates),
            )
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel an active task."""
        if task_id in self._active_tasks:
            task = self._active_tasks[task_id]
            task.status = TaskStatus.CANCELLED
            return True
        return False
    
    def get_status(self) -> dict[str, Any]:
        """Get orchestrator status."""
        return {
            "registered_agents": len(self._agents),
            "active_tasks": len(self._active_tasks),
            "healthy_agents": sum(1 for h in self._agent_health.values() if h),
            "circuit_breakers": {
                agent_id: cb.state.value
                for agent_id, cb in self._circuit_breakers.items()
            },
        }
