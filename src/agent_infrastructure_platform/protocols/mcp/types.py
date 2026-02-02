"""Types for the Model Context Protocol (MCP)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_infrastructure_platform.common.types import JSON, AgentID, Message, Resource, Tool


class MCPRequest(BaseModel):
    """Base class for MCP requests."""

    model_config = ConfigDict(frozen=True)

    method: str
    params: JSON = None
    request_id: str = Field(default_factory=lambda: f"req-{id(object())}")


class MCPResponse(BaseModel):
    """Base class for MCP responses."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    result: JSON = None
    error: MCPError | None = None


class MCPError(BaseModel):
    """MCP error response."""

    code: int
    message: str
    data: JSON = None


# Resource methods
class MCPResourceRequest(MCPRequest):
    """Request to access a resource."""

    method: Literal["resources/read", "resources/list", "resources/subscribe"] = "resources/read"
    uri: str = ""


class MCPResourceResponse(MCPResponse):
    """Response containing resource data."""

    contents: list[MCPResourceContent] = Field(default_factory=list)


class MCPResourceContent(BaseModel):
    """Resource content wrapper."""

    uri: str
    mime_type: str = "application/octet-stream"
    text: str | None = None
    blob: bytes | None = None

    model_config = ConfigDict(frozen=True)


# Tool methods
class MCPToolRequest(MCPRequest):
    """Request to invoke a tool."""

    method: Literal["tools/list", "tools/call"] = "tools/call"
    name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPToolResponse(MCPResponse):
    """Response from tool invocation."""

    content: list[MCPToolContent] = Field(default_factory=list)
    is_error: bool = False


class MCPToolContent(BaseModel):
    """Tool result content."""

    type: Literal["text", "image", "resource"] = "text"
    text: str | None = None
    data: bytes | None = None  # For images
    mime_type: str | None = None
    resource: MCPResourceContent | None = None

    model_config = ConfigDict(frozen=True)


# Prompt methods
class MCPPromptRequest(MCPRequest):
    """Request to get a prompt."""

    method: Literal["prompts/list", "prompts/get"] = "prompts/get"
    name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPPromptResponse(MCPResponse):
    """Response containing prompt messages."""

    description: str = ""
    messages: list[MCPPromptMessage] = Field(default_factory=list)


class MCPPromptMessage(BaseModel):
    """A message in a prompt template."""

    role: Literal["user", "assistant", "system"] = "user"
    content: MCPTextContent | MCPImageContent | MCPResourceContent

    model_config = ConfigDict(frozen=True)


class MCPTextContent(BaseModel):
    """Text content."""

    type: Literal["text"] = "text"
    text: str

    model_config = ConfigDict(frozen=True)


class MCPImageContent(BaseModel):
    """Image content."""

    type: Literal["image"] = "image"
    data: bytes
    mime_type: str = "image/png"

    model_config = ConfigDict(frozen=True)


# Server capabilities
class MCPServerCapabilities(BaseModel):
    """Capabilities advertised by an MCP server."""

    resources: bool = False
    tools: bool = False
    prompts: bool = False
    logging: bool = False
    experimental: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


class MCPServerInfo(BaseModel):
    """Information about an MCP server."""

    name: str
    version: str
    capabilities: MCPServerCapabilities = Field(default_factory=MCPServerCapabilities)

    model_config = ConfigDict(frozen=True)


# Sampling (for server-initiated LLM requests)
class MCPSamplingRequest(MCPRequest):
    """Request for LLM sampling (server -> client)."""

    method: Literal["sampling/createMessage"] = "sampling/createMessage"
    messages: list[MCPPromptMessage] = Field(default_factory=list)
    model_preferences: MCPModelPreferences | None = None
    system_prompt: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.7


class MCPModelPreferences(BaseModel):
    """Model preferences for sampling."""

    hints: list[MCPModelHint] = Field(default_factory=list)
    cost_priority: float = 0.5  # 0-1
    speed_priority: float = 0.5  # 0-1
    intelligence_priority: float = 0.5  # 0-1

    model_config = ConfigDict(frozen=True)


class MCPModelHint(BaseModel):
    """Hint for model selection."""

    name: str | None = None

    model_config = ConfigDict(frozen=True)


class MCPSamplingResponse(MCPResponse):
    """Response from sampling request."""

    model: str = ""
    stop_reason: Literal["endTurn", "stopSequence", "maxTokens"] = "endTurn"
    role: Literal["user", "assistant"] = "assistant"
    content: MCPTextContent | MCPImageContent


# Progress notifications
class MCPProgressNotification(BaseModel):
    """Progress update notification."""

    method: Literal["notifications/progress"] = "notifications/progress"
    progress_token: str
    progress: float  # 0-100
    total: float | None = None

    model_config = ConfigDict(frozen=True)


# Root resources
class MCPRoot(BaseModel):
    """A root resource available to the agent."""

    uri: str
    name: str | None = None

    model_config = ConfigDict(frozen=True)


class MCPRootsList(BaseModel):
    """List of root resources."""

    roots: list[MCPRoot] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)
