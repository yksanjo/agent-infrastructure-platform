"""Policy Engine for agent governance."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

import structlog

from agent_infrastructure_platform.common.types import AgentID, Context, Task

logger = structlog.get_logger()


class PolicyAction(Enum):
    """Actions to take when policy is violated."""

    ALLOW = auto()
    WARN = auto()
    DENY = auto()
    AUDIT = auto()
    QUARANTINE = auto()


class PolicyScope(Enum):
    """Scope of policy application."""

    GLOBAL = auto()
    AGENT = auto()
    TASK = auto()
    CAPABILITY = auto()


@dataclass
class Policy:
    """A policy rule."""

    id: str
    name: str
    description: str = ""
    scope: PolicyScope = PolicyScope.GLOBAL
    target_agents: list[str] = field(default_factory=list)  # Agent IDs or patterns
    
    # Conditions
    condition: str = "true"  # Expression to evaluate
    
    # Action
    action: PolicyAction = PolicyAction.DENY
    
    # Metadata
    priority: int = 100  # Lower = higher priority
    enabled: bool = True
    created_at: float = field(default_factory=time.time)


class PolicyEngine:
    """
    Policy-as-code engine for agent governance.
    
    Enforces constraints on agent actions with sub-10ms evaluation.
    
    Example:
        ```python
        engine = PolicyEngine()
        
        # Register policies
        engine.register_policy(Policy(
            id="no-external-api",
            name="No External APIs",
            description="Prevent agents from calling external APIs",
            scope=PolicyScope.CAPABILITY,
            condition="capability.name == 'external-api-call'",
            action=PolicyAction.DENY,
            priority=10,
        ))
        
        # Evaluate action
        result = await engine.evaluate(
            agent_id="agent-1",
            action="capability",
            context={"capability": {"name": "external-api-call"}},
        )
        
        if result.decision == PolicyAction.DENY:
            raise PolicyViolation(result.reason)
        ```
    """

    def __init__(self, max_evaluation_ms: float = 10.0) -> None:
        self.max_evaluation_ms = max_evaluation_ms
        self._policies: dict[str, Policy] = {}
        self._compiled_conditions: dict[str, Callable] = {}
        
        # Stats
        self._evaluation_count = 0
        self._violation_count = 0
        
        self._logger = logger
    
    def register_policy(self, policy: Policy) -> None:
        """
        Register a policy.
        
        Args:
            policy: Policy to register
        """
        self._policies[policy.id] = policy
        
        # Compile condition
        if policy.condition != "true":
            self._compiled_conditions[policy.id] = self._compile_condition(policy.condition)
        
        self._logger.info(
            "policy_registered",
            policy_id=policy.id,
            name=policy.name,
            action=policy.action.name,
        )
    
    def unregister_policy(self, policy_id: str) -> bool:
        """Unregister a policy."""
        if policy_id in self._policies:
            del self._policies[policy_id]
            if policy_id in self._compiled_conditions:
                del self._compiled_conditions[policy_id]
            return True
        return False
    
    def _compile_condition(self, condition: str) -> Callable:
        """
        Compile a condition expression to a callable.
        
        Supports simple expressions like:
        - "capability.name == 'x'"
        - "resource.type in ['file', 'memory']"
        - "agent.reputation < 0.5"
        """
        # Simple condition parser
        # In production, use a proper expression evaluator
        
        def evaluator(context: dict[str, Any]) -> bool:
            try:
                # Replace context variables
                expr = condition
                for key, value in context.items():
                    if isinstance(value, (str, int, float, bool)):
                        expr = expr.replace(f"{key}", repr(value))
                    elif isinstance(value, dict):
                        for subkey, subval in value.items():
                            path = f"{key}.{subkey}"
                            if path in expr:
                                expr = expr.replace(path, repr(subval))
                
                # Evaluate
                return eval(expr, {"__builtins__": {}}, {})
            except Exception as e:
                logger.error("condition_evaluation_error", error=str(e), condition=condition)
                return False
        
        return evaluator
    
    async def evaluate(
        self,
        agent_id: AgentID,
        action: str,
        context: dict[str, Any],
        ctx: Context | None = None,
    ) -> PolicyEvaluationResult:
        """
        Evaluate policies against an action.
        
        Args:
            agent_id: Acting agent
            action: Action being performed
            context: Action context
            ctx: Execution context
            
        Returns:
            Evaluation result
        """
        start_time = time.perf_counter()
        
        self._evaluation_count += 1
        
        # Sort policies by priority
        sorted_policies = sorted(
            (p for p in self._policies.values() if p.enabled),
            key=lambda p: p.priority,
        )
        
        for policy in sorted_policies:
            # Check scope
            if policy.scope == PolicyScope.AGENT:
                if not self._matches_agent(policy, agent_id):
                    continue
            
            # Evaluate condition
            condition_result = self._evaluate_condition(policy, context)
            
            if condition_result:
                # Policy matched
                if policy.action in (PolicyAction.DENY, PolicyAction.QUARANTINE):
                    self._violation_count += 1
                
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                
                return PolicyEvaluationResult(
                    decision=policy.action,
                    policy_id=policy.id,
                    policy_name=policy.name,
                    reason=f"Policy '{policy.name}' matched",
                    evaluation_time_ms=elapsed_ms,
                )
        
        # No policy matched, allow
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        return PolicyEvaluationResult(
            decision=PolicyAction.ALLOW,
            policy_id=None,
            policy_name=None,
            reason="No policy matched",
            evaluation_time_ms=elapsed_ms,
        )
    
    def _matches_agent(self, policy: Policy, agent_id: AgentID) -> bool:
        """Check if policy applies to agent."""
        if not policy.target_agents:
            return True
        
        for pattern in policy.target_agents:
            if pattern == agent_id:
                return True
            # Support wildcards
            if "*" in pattern:
                regex = pattern.replace("*", ".*")
                if re.match(regex, agent_id):
                    return True
        
        return False
    
    def _evaluate_condition(self, policy: Policy, context: dict[str, Any]) -> bool:
        """Evaluate policy condition."""
        if policy.condition == "true":
            return True
        
        evaluator = self._compiled_conditions.get(policy.id)
        if evaluator:
            return evaluator(context)
        
        return False
    
    def get_stats(self) -> dict[str, Any]:
        """Get engine statistics."""
        return {
            "registered_policies": len(self._policies),
            "evaluation_count": self._evaluation_count,
            "violation_count": self._violation_count,
            "violation_rate": (
                self._violation_count / max(self._evaluation_count, 1)
            ),
        }


@dataclass
class PolicyEvaluationResult:
    """Result of policy evaluation."""

    decision: PolicyAction
    policy_id: str | None
    policy_name: str | None
    reason: str
    evaluation_time_ms: float
    
    @property
    def allowed(self) -> bool:
        """Whether the action is allowed."""
        return self.decision == PolicyAction.ALLOW
