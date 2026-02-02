"""Types for the Agent-to-Agent (A2A) Protocol."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from agent_infrastructure_platform.common.types import AgentID, JSON


class Skill(BaseModel):
    """A skill advertised by an agent."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    input_modes: list[str] = Field(default_factory=lambda: ["text"])
    output_modes: list[str] = Field(default_factory=lambda: ["text"])


class AgentProvider(BaseModel):
    """Organization providing the agent."""

    model_config = ConfigDict(frozen=True)

    organization: str
    url: HttpUrl | None = None


class AgentAuthentication(BaseModel):
    """Authentication scheme for the agent."""

    model_config = ConfigDict(frozen=True)

    schemes: list[str] = Field(default_factory=list)
    credentials: str | None = None  # OAuth token, API key reference, etc.


class AgentCapabilities(BaseModel):
    """Capabilities supported by the agent."""

    model_config = ConfigDict(frozen=True)

    streaming: bool = False
    push_notifications: bool = False
    state_transition_history: bool = False


class AgentCard(BaseModel):
    """
    Agent Card - Self-describing agent capabilities and endpoints.
    
    This is the core of the A2A protocol. Agents advertise their
    capabilities through Agent Cards that other agents can discover.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    name: str
    description: str = ""
    url: HttpUrl  # Base URL for agent endpoints
    
    # Provider
    provider: AgentProvider | None = None
    
    # Version
    version: str = "1.0.0"
    documentation_url: HttpUrl | None = None
    
    # Capabilities
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    
    # Authentication
    authentication: AgentAuthentication = Field(default_factory=AgentAuthentication)
    
    # Skills
    skills: list[Skill] = Field(default_factory=list)
    
    # Default input/output modes
    default_input_modes: list[str] = Field(default_factory=lambda: ["text"])
    default_output_modes: list[str] = Field(default_factory=lambda: ["text"])


def generate_agent_card_id() -> str:
    """Generate a unique agent card ID."""
    return f"agent-{uuid4().hex[:12]}"


# Task types for A2A
class TaskState(str):
    """Task states in A2A protocol."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TextPart(BaseModel):
    """Text content part."""

    type: Literal["text"] = "text"
    text: str

    model_config = ConfigDict(frozen=True)


class FileContent(BaseModel):
    """File content metadata."""

    name: str | None = None
    mime_type: str | None = None
    bytes: bytes | None = None
    uri: str | None = None

    model_config = ConfigDict(frozen=True)


class FilePart(BaseModel):
    """File content part."""

    type: Literal["file"] = "file"
    file: FileContent

    model_config = ConfigDict(frozen=True)


class DataPart(BaseModel):
    """Structured data part."""

    type: Literal["data"] = "data"
    data: JSON

    model_config = ConfigDict(frozen=True)


Part = TextPart | FilePart | DataPart


class Message(BaseModel):
    """A message in a task conversation."""

    role: Literal["user", "agent"]
    parts: list[Part]
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


class Artifact(BaseModel):
    """Output artifact from a task."""

    name: str | None = None
    description: str | None = None
    parts: list[Part]
    metadata: dict[str, Any] = Field(default_factory=dict)
    append: bool | None = None  # For streaming updates
    last_chunk: bool | None = None  # Last chunk of a streaming artifact

    model_config = ConfigDict(frozen=True)


class TaskStatus(BaseModel):
    """Current status of a task."""

    state: str  # TaskState
    message: Message | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(frozen=True)


class Task(BaseModel):
    """An A2A task."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str | None = None
    status: TaskStatus
    artifacts: list[Artifact] = Field(default_factory=list)
    history: list[TaskStatus] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=False)


# RPC Request/Response types
class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request."""

    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: JSON = None
    id: str | int | None = Field(default_factory=lambda: str(uuid4()))


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 error."""

    code: int
    message: str
    data: JSON = None


class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 response."""

    jsonrpc: Literal["2.0"] = "2.0"
    result: JSON = None
    error: JSONRPCError | None = None
    id: str | int | None = None


# A2A specific methods
class TaskSendParams(BaseModel):
    """Parameters for tasks/send method."""

    id: str | None = None
    session_id: str | None = None
    message: Message
    push_notification: PushNotificationConfig | None = None
    history_length: int | None = None  # Number of history entries to include
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskQueryParams(BaseModel):
    """Parameters for tasks/get method."""

    id: str
    history_length: int | None = None


class TaskCancelParams(BaseModel):
    """Parameters for tasks/cancel method."""

    id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PushNotificationConfig(BaseModel):
    """Configuration for push notifications."""

    url: str
    token: str | None = None
    authentication: dict[str, Any] | None = None


class SendTaskRequest(JSONRPCRequest):
    """Request to send a task."""

    method: Literal["tasks/send"] = "tasks/send"
    params: TaskSendParams


class SendTaskResponse(JSONRPCResponse):
    """Response from tasks/send."""

    result: Task | None = None


class GetTaskRequest(JSONRPCRequest):
    """Request to get a task."""

    method: Literal["tasks/get"] = "tasks/get"
    params: TaskQueryParams


class GetTaskResponse(JSONRPCResponse):
    """Response from tasks/get."""

    result: Task | None = None


class CancelTaskRequest(JSONRPCRequest):
    """Request to cancel a task."""

    method: Literal["tasks/cancel"] = "tasks/cancel"
    params: TaskCancelParams


class CancelTaskResponse(JSONRPCResponse):
    """Response from tasks/cancel."""

    result: Task | None = None


class SetTaskPushNotificationRequest(JSONRPCRequest):
    """Request to set push notification config."""

    method: Literal["tasks/pushNotification/set"] = "tasks/pushNotification/set"
    params: TaskPushNotificationParams


class TaskPushNotificationParams(BaseModel):
    """Parameters for push notification config."""

    id: str
    push_notification: PushNotificationConfig


class SetTaskPushNotificationResponse(JSONRPCResponse):
    """Response from tasks/pushNotification/set."""

    result: PushNotificationConfig | None = None


class GetTaskPushNotificationRequest(JSONRPCRequest):
    """Request to get push notification config."""

    method: Literal["tasks/pushNotification/get"] = "tasks/pushNotification/get"
    params: TaskQueryParams


class GetTaskPushNotificationResponse(JSONRPCResponse):
    """Response from tasks/pushNotification/get."""

    result: PushNotificationConfig | None = None


# Streaming types
class TaskStatusUpdateEvent(BaseModel):
    """Task status update for streaming."""

    id: str  # Task ID
    status: TaskStatus
    final: bool = False  # True if this is the final update


class TaskArtifactUpdateEvent(BaseModel):
    """Task artifact update for streaming."""

    id: str  # Task ID
    artifact: Artifact


class SendTaskStreamingRequest(JSONRPCRequest):
    """Request for streaming task updates."""

    method: Literal["tasks/sendSubscribe"] = "tasks/sendSubscribe"
    params: TaskSendParams


# Error codes (JSON-RPC standard + A2A specific)
class ErrorCode:
    """Error codes for A2A protocol."""

    # Standard JSON-RPC errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    
    # A2A specific errors
    TASK_NOT_FOUND = -32001
    TASK_NOT_CANCELABLE = -32002
    PUSH_NOTIFICATION_NOT_SUPPORTED = -32003
    UNAUTHORIZED = -32004
    RATE_LIMIT_EXCEEDED = -32005
    
    @classmethod
    def get_message(cls, code: int) -> str:
        """Get default message for error code."""
        messages = {
            cls.PARSE_ERROR: "Parse error",
            cls.INVALID_REQUEST: "Invalid request",
            cls.METHOD_NOT_FOUND: "Method not found",
            cls.INVALID_PARAMS: "Invalid parameters",
            cls.INTERNAL_ERROR: "Internal error",
            cls.TASK_NOT_FOUND: "Task not found",
            cls.TASK_NOT_CANCELABLE: "Task cannot be canceled",
            cls.PUSH_NOTIFICATION_NOT_SUPPORTED: "Push notifications not supported",
            cls.UNAUTHORIZED: "Unauthorized",
            cls.RATE_LIMIT_EXCEEDED: "Rate limit exceeded",
        }
        return messages.get(code, "Unknown error")
