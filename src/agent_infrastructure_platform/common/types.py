"""Core type definitions for the Agent Infrastructure Platform."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Literal,
    NewType,
    NotRequired,
    TypedDict,
)
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Primitive Types
AgentID = NewType("AgentID", str)
TaskID = NewType("TaskID", str)
MessageID = NewType("MessageID", str)
SessionID = NewType("SessionID", str)
NamespaceID = NewType("NamespaceID", str)
Timestamp = NewType("Timestamp", datetime)
JSON = dict[str, Any] | list[Any] | str | int | float | bool | None


class TaskStatus(StrEnum):
    """Task lifecycle states."""

    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class MessageType(StrEnum):
    """Message types for inter-agent communication."""

    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    EVENT = "event"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


class ProtocolType(StrEnum):
    """Supported communication protocols."""

    MCP = "mcp"
    A2A = "a2a"
    ACP = "acp"
    ANP = "anp"


class CapabilityCategory(StrEnum):
    """Categories of agent capabilities."""

    COGNITIVE = "cognitive"  # LLM, reasoning, planning
    TOOL = "tool"  # External tool usage
    DATA = "data"  # Data access and storage
    COMMUNICATION = "communication"  # Protocol support
    COMPUTE = "compute"  # Execution environments
    SECURITY = "security"  # Cryptographic operations


class Capability(BaseModel):
    """A capability that an agent can possess."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Unique capability identifier")
    category: CapabilityCategory
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    requires_auth: bool = False
    rate_limit: int | None = None  # requests per minute

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or "/" in v or " " in v:
            raise ValueError("Capability name must be non-empty and not contain '/' or spaces")
        return v.lower()


class ResourceType(StrEnum):
    """Types of resources agents can access."""

    FILE = "file"
    DATABASE = "database"
    API = "api"
    MEMORY = "memory"
    COMPUTE = "compute"
    NETWORK = "network"


class Resource(BaseModel):
    """A resource that can be accessed via MCP."""

    model_config = ConfigDict(frozen=True)

    uri: str = Field(..., description="Unique resource identifier (URI)")
    type: ResourceType
    name: str
    description: str = ""
    mime_type: str = "application/octet-stream"
    metadata: dict[str, Any] = Field(default_factory=dict)
    size: int | None = None

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, v: str) -> str:
        if not v.startswith(("file://", "db://", "api://", "memory://", "compute://")):
            raise ValueError("URI must use a supported scheme")
        return v


class Tool(BaseModel):
    """A tool that can be invoked via MCP."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_params: list[str] = Field(default_factory=list)
    returns: dict[str, Any] | None = None
    examples: list[dict[str, Any]] = Field(default_factory=list)


class TaskPriority(Enum):
    """Task priority levels."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class Task(BaseModel):
    """A unit of work to be executed by an agent or agent team."""

    model_config = ConfigDict(frozen=False)

    id: TaskID = Field(default_factory=lambda: TaskID(str(UUID.uuid4())))
    parent_id: TaskID | None = None
    session_id: SessionID | None = None

    # Task definition
    name: str
    description: str = ""
    goal: str
    priority: TaskPriority = TaskPriority.NORMAL
    deadline: datetime | None = None
    max_retries: int = 3
    timeout_seconds: float = 300.0

    # Execution state
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Assignment
    assigned_to: AgentID | None = None
    required_capabilities: list[Capability] = Field(default_factory=list)

    # Context and results
    input_data: JSON = None
    output_data: JSON = None
    context: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)  # URIs to artifacts

    # Metadata
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Cost tracking
    estimated_cost: Decimal | None = None
    actual_cost: Decimal | None = None


class Message(BaseModel):
    """A message exchanged between agents."""

    model_config = ConfigDict(frozen=True)

    id: MessageID = Field(default_factory=lambda: MessageID(str(UUID.uuid4())))
    type: MessageType
    protocol: ProtocolType

    # Routing
    sender: AgentID
    recipient: AgentID
    reply_to: MessageID | None = None
    session_id: SessionID | None = None

    # Content
    content: JSON
    content_type: str = "application/json"
    encoding: str = "utf-8"

    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ttl_seconds: int | None = None  # Time-to-live
    priority: int = 5  # 1-10, lower is higher priority

    # Security
    signature: str | None = None
    encryption: str | None = None  # Algorithm used

    # Tracing
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None


class Context(BaseModel):
    """Execution context passed through agent operations."""

    model_config = ConfigDict(frozen=False)

    # Identity
    caller: AgentID | None = None
    session_id: SessionID | None = None

    # Security
    auth_token: str | None = None
    permissions: list[str] = Field(default_factory=list)
    clearance_level: int = 0

    # Tracing
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None

    # Request metadata
    request_id: str | None = None
    correlation_id: str | None = None

    # Environment
    environment: str = "production"
    region: str | None = None
    version: str | None = None

    # Custom context
    baggage: dict[str, str] = Field(default_factory=dict)

    def with_agent(self, agent_id: AgentID) -> Context:
        """Create a new context with the specified agent as caller."""
        new_ctx = self.model_copy()
        new_ctx.caller = agent_id
        return new_ctx

    def with_trace(self, trace_id: str, span_id: str) -> Context:
        """Create a new context with updated trace info."""
        new_ctx = self.model_copy()
        new_ctx.trace_id = trace_id
        new_ctx.span_id = span_id
        new_ctx.parent_span_id = self.span_id
        return new_ctx


class AgentState(Enum):
    """Agent lifecycle states."""

    INITIALIZING = "initializing"
    IDLE = "idle"
    BUSY = "busy"
    PAUSED = "paused"
    SHUTTING_DOWN = "shutting_down"
    OFFLINE = "offline"
    ERROR = "error"


class HealthStatus(BaseModel):
    """Health check information for an agent or service."""

    status: Literal["healthy", "degraded", "unhealthy", "unknown"]
    last_check: datetime = Field(default_factory=datetime.utcnow)
    checks: dict[str, bool] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    message: str = ""


class PaginationParams(BaseModel):
    """Standard pagination parameters."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=1000)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginatedResult[T](BaseModel):
    """Generic paginated result wrapper."""

    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool

    @classmethod
    def create(
        cls, items: list[T], total: int, params: PaginationParams
    ) -> PaginatedResult[T]:
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            has_more=params.offset + len(items) < total,
        )


# Type aliases for common function signatures
AgentHandler = Callable[[Message, Context], Awaitable[Message | None]]
TaskHandler = Callable[[Task, Context], Awaitable[Task]]
StreamingHandler = Callable[[Message, Context], AsyncIterator[Message]]
Middleware = Callable[[Message, Context, AgentHandler], Awaitable[Message | None]]
