"""Types for the Agent Communication Protocol (ACP)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ACPMessagePriority(int):
    """Message priority levels."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class ACPMessageType(str):
    """ACP message types."""

    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    COMMAND = "command"
    QUERY = "query"
    STREAM = "stream"


class ACPMessage(BaseModel):
    """ACP message with async support and memory persistence."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str  # ACPMessageType
    
    # Addressing
    sender: str  # Agent ID
    recipient: str  # Agent ID or topic
    reply_to: str | None = None  # Message ID to reply to
    correlation_id: str | None = None  # For request-response correlation
    
    # Content
    payload: dict[str, Any]
    content_type: str = "application/json"
    encoding: str = "utf-8"
    
    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    priority: int = ACPMessagePriority.NORMAL
    ttl_seconds: int | None = None  # Time to live
    
    # Memory context
    session_id: str | None = None
    memory_context: dict[str, Any] = Field(default_factory=dict)
    
    # Security
    signature: str | None = None
    encryption_key_id: str | None = None
    
    # Delivery tracking
    delivery_count: int = 0
    max_delivery_attempts: int = 3


class ACPChannel(BaseModel):
    """Communication channel between agents."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    type: Literal["direct", "topic", "queue", "broadcast"] = "direct"
    
    # Participants
    participants: list[str] = Field(default_factory=list)  # Agent IDs
    
    # Configuration
    persistent: bool = True
    ordered: bool = True
    ttl_seconds: int | None = None
    
    # State
    created_at: datetime = Field(default_factory=datetime.utcnow)
    message_count: int = 0
    last_activity: datetime | None = None


class ACPSubscription(BaseModel):
    """Subscription to a channel or topic."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    channel_id: str | None = None
    topic_pattern: str | None = None  # For pub/sub
    
    # Filter
    message_types: list[str] = Field(default_factory=list)
    min_priority: int = ACPMessagePriority.BACKGROUND
    
    # Delivery
    delivery_mode: Literal["push", "pull"] = "push"
    callback_url: str | None = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ACPDeliveryReceipt(BaseModel):
    """Receipt for message delivery."""

    model_config = ConfigDict(frozen=True)

    message_id: str
    status: Literal["delivered", "read", "failed", "expired"]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    recipient: str | None = None
    error: str | None = None


class ACPConversation(BaseModel):
    """Conversation state with memory."""

    model_config = ConfigDict(frozen=False)

    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    
    # Participants
    participants: list[str] = Field(default_factory=list)
    
    # Messages (summary for large conversations)
    message_ids: list[str] = Field(default_factory=list)
    message_count: int = 0
    
    # Context
    context: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    
    # State
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_message_at: datetime | None = None
    status: Literal["active", "paused", "closed"] = "active"
