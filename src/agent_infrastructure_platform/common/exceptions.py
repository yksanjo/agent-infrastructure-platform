"""Exception hierarchy for the Agent Infrastructure Platform."""

from __future__ import annotations

from typing import Any


class AIPError(Exception):
    """Base exception for all AIP errors."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}
        self.cause = cause

    def __str__(self) -> str:
        if self.details:
            return f"[{self.code}] {self.message} - Details: {self.details}"
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "type": self.__class__.__name__,
            }
        }


# Protocol Errors
class ProtocolError(AIPError):
    """Base class for protocol-related errors."""

    pass


class MCPError(ProtocolError):
    """Model Context Protocol error."""

    pass


class A2AError(ProtocolError):
    """Agent-to-Agent protocol error."""

    pass


class ACPError(ProtocolError):
    """Agent Communication Protocol error."""

    pass


class ANPError(ProtocolError):
    """Agent Network Protocol error."""

    pass


class ProtocolNegotiationError(ProtocolError):
    """Failed to negotiate protocol version or capabilities."""

    pass


class MessageValidationError(ProtocolError):
    """Message failed validation."""

    pass


class TimeoutError(ProtocolError):
    """Operation timed out."""

    pass


# Identity Errors
class IdentityError(AIPError):
    """Base class for identity-related errors."""

    pass


class AuthenticationError(IdentityError):
    """Failed to authenticate agent or user."""

    pass


class AuthorizationError(IdentityError):
    """Agent lacks required permissions."""

    pass


class IdentityNotFoundError(IdentityError):
    """Requested identity not found."""

    pass


class CredentialError(IdentityError):
    """Invalid or expired credentials."""

    pass


class ReputationError(IdentityError):
    """Agent reputation check failed."""

    pass


# Memory Errors
class MemoryError(AIPError):
    """Base class for memory-related errors."""

    pass


class MemoryNotFoundError(MemoryError):
    """Requested memory not found."""

    pass


class MemoryStorageError(MemoryError):
    """Failed to store or retrieve memory."""

    pass


class MemoryQuotaExceeded(MemoryError):
    """Agent has exceeded memory quota."""

    pass


class ConsensusError(MemoryError):
    """Failed to reach consensus on shared state."""

    pass


# Orchestration Errors
class OrchestrationError(AIPError):
    """Base class for orchestration-related errors."""

    pass


class TaskNotFoundError(OrchestrationError):
    """Requested task not found."""

    pass


class TaskExecutionError(OrchestrationError):
    """Failed to execute task."""

    pass


class TaskCancelledError(OrchestrationError):
    """Task was cancelled."""

    pass


class AgentNotFoundError(OrchestrationError):
    """Requested agent not found."""

    pass


class AgentUnavailableError(OrchestrationError):
    """Agent is currently unavailable."""

    pass


class CircuitBreakerError(OrchestrationError):
    """Circuit breaker is open."""

    pass


class ResourceExhaustedError(OrchestrationError):
    """Required resources are exhausted."""

    pass


# Governance Errors
class GovernanceError(AIPError):
    """Base class for governance-related errors."""

    pass


class PolicyViolation(GovernanceError):
    """Agent action violated policy."""

    pass


class PolicyNotFoundError(GovernanceError):
    """Requested policy not found."""

    pass


class AuditError(GovernanceError):
    """Failed to record audit log."""

    pass


class KillSwitchActivated(GovernanceError):
    """Kill switch has been activated for an agent or swarm."""

    pass


# Compute Errors
class ComputeError(AIPError):
    """Base class for compute-related errors."""

    pass


class ExecutionError(ComputeError):
    """Failed to execute agent code."""

    pass


class EnvironmentError(ComputeError):
    """Execution environment error."""

    pass


class ResourceLimitExceeded(ComputeError):
    """Exceeded resource limits (CPU, memory, etc.)."""

    pass


# Economic Errors
class EconomicError(AIPError):
    """Base class for economic layer errors."""

    pass


class PaymentError(EconomicError):
    """Payment processing error."""

    pass


class InsufficientFundsError(EconomicError):
    """Agent has insufficient funds for operation."""

    pass


class MarketError(EconomicError):
    """Resource market error."""

    pass


# Validation Errors
class ValidationError(AIPError):
    """Input validation error."""

    pass


class SchemaValidationError(ValidationError):
    """JSON schema validation error."""

    pass


# Configuration Errors
class ConfigurationError(AIPError):
    """Configuration error."""

    pass


# Network Errors
class NetworkError(AIPError):
    """Network communication error."""

    pass


class ConnectionError(NetworkError):
    """Failed to establish connection."""

    pass


class RetryExhaustedError(NetworkError):
    """All retry attempts exhausted."""

    pass
