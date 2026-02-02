"""Agent Card implementation for self-describing agent capabilities."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from agent_infrastructure_platform.common.types import AgentID, Capability, CapabilityCategory

logger = structlog.get_logger()


class AgentEndpoint(BaseModel):
    """Endpoint for agent communication."""

    model_config = ConfigDict(frozen=True)

    protocol: str  # mcp, a2a, acp, anp
    url: str
    priority: int = 1  # Lower is higher priority
    health_check_url: str | None = None


class AgentCapability(BaseModel):
    """Capability with protocol-specific details."""

    model_config = ConfigDict(frozen=True)

    capability: Capability
    endpoints: list[AgentEndpoint] = Field(default_factory=list)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    rate_limit: int | None = None  # requests per minute
    cost_per_request: float | None = None  # in credits/tokens


class AgentCredential(BaseModel):
    """Credential attesting to agent identity or capabilities."""

    model_config = ConfigDict(frozen=True)

    type: str  # x509, jwt, did, etc.
    issuer: str
    issued_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    claims: dict[str, Any] = Field(default_factory=dict)
    proof: str | None = None  # Signature or proof


class AgentCard(BaseModel):
    """
    Agent Card - Self-describing capabilities, endpoints, and authentication.
    
    This is the core identity document for agents in the AIP ecosystem.
    It combines ideas from A2A Agent Cards with verifiable credentials.
    
    Example:
        ```python
        card = AgentCard(
            name="document-processor",
            owner="org:acme-corp",
            capabilities=[
                AgentCapability(
                    capability=Capability(
                        name="document-parsing",
                        category=CapabilityCategory.TOOL,
                    ),
                    endpoints=[
                        AgentEndpoint(protocol="a2a", url="https://agent.acme.com/a2a"),
                    ],
                ),
            ],
        )
        
        # Sign the card
        card = identity_manager.sign_card(card, private_key)
        
        # Verify the card
        assert identity_manager.verify_card(card)
        ```
    """

    model_config = ConfigDict(frozen=False)

    # Identity
    id: AgentID = Field(default_factory=lambda: AgentID(f"agent-{uuid4().hex[:12]}"))
    name: str
    version: str = "1.0.0"
    
    # Ownership
    owner: str  # org:xxx, did:xxx, or user:xxx
    
    # Description
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    
    # Capabilities
    capabilities: list[AgentCapability] = Field(default_factory=list)
    
    # Credentials
    credentials: list[AgentCredential] = Field(default_factory=list)
    
    # Authentication
    public_key: str | None = None
    authentication_methods: list[str] = Field(default_factory=lambda: ["signature"])
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    
    # Status
    status: str = "active"  # active, inactive, suspended, revoked
    
    # Verification
    proof: str | None = None  # Signature of the card
    
    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or len(v) < 2:
            raise ValueError("Agent name must be at least 2 characters")
        return v.lower().replace(" ", "-")
    
    def has_capability(self, name: str) -> bool:
        """Check if agent has a specific capability."""
        return any(cap.capability.name == name for cap in self.capabilities)
    
    def get_capability(self, name: str) -> AgentCapability | None:
        """Get a specific capability."""
        for cap in self.capabilities:
            if cap.capability.name == name:
                return cap
        return None
    
    def get_endpoints(self, protocol: str | None = None) -> list[AgentEndpoint]:
        """Get endpoints, optionally filtered by protocol."""
        endpoints = []
        for cap in self.capabilities:
            for ep in cap.endpoints:
                if protocol is None or ep.protocol == protocol:
                    endpoints.append(ep)
        return sorted(endpoints, key=lambda e: e.priority)
    
    def is_valid(self) -> bool:
        """Check if the card is currently valid."""
        if self.status != "active":
            return False
        
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        
        for cred in self.credentials:
            if datetime.utcnow() > cred.expires_at:
                return False
        
        return True
    
    def to_signing_payload(self) -> str:
        """Get the payload that should be signed for verification."""
        # Create a copy without the proof
        card_copy = self.model_copy()
        card_copy.proof = None
        return card_copy.model_dump_json(sort_keys=True)
    
    def update(self) -> None:
        """Update the modified timestamp."""
        self.updated_at = datetime.utcnow()
    
    def add_capability(self, capability: AgentCapability) -> None:
        """Add a capability to the card."""
        self.capabilities.append(capability)
        self.update()
    
    def remove_capability(self, name: str) -> bool:
        """Remove a capability from the card."""
        for i, cap in enumerate(self.capabilities):
            if cap.capability.name == name:
                self.capabilities.pop(i)
                self.update()
                return True
        return False


class AgentCardBuilder:
    """Builder for creating Agent Cards."""
    
    def __init__(self, name: str, owner: str) -> None:
        self.card = AgentCard(name=name, owner=owner)
        self._logger = logger.bind(builder="AgentCardBuilder")
    
    def with_description(self, description: str) -> AgentCardBuilder:
        self.card.description = description
        return self
    
    def with_tag(self, tag: str) -> AgentCardBuilder:
        if tag not in self.card.tags:
            self.card.tags.append(tag)
        return self
    
    def with_capability(
        self,
        name: str,
        category: CapabilityCategory,
        endpoints: list[AgentEndpoint] | None = None,
    ) -> AgentCardBuilder:
        capability = AgentCapability(
            capability=Capability(name=name, category=category),
            endpoints=endpoints or [],
        )
        self.card.capabilities.append(capability)
        return self
    
    def with_endpoint(
        self,
        capability_name: str,
        protocol: str,
        url: str,
        priority: int = 1,
    ) -> AgentCardBuilder:
        endpoint = AgentEndpoint(protocol=protocol, url=url, priority=priority)
        
        for cap in self.card.capabilities:
            if cap.capability.name == capability_name:
                cap.endpoints.append(endpoint)
                break
        else:
            # Add new capability with this endpoint
            self.with_capability(
                name=capability_name,
                category=CapabilityCategory.TOOL,
                endpoints=[endpoint],
            )
        
        return self
    
    def with_expiry(self, days: int = 365) -> AgentCardBuilder:
        self.card.expires_at = datetime.utcnow() + timedelta(days=days)
        return self
    
    def with_public_key(self, public_key: str) -> AgentCardBuilder:
        self.card.public_key = public_key
        return self
    
    def build(self) -> AgentCard:
        """Build the Agent Card."""
        self._logger.info(
            "agent_card_built",
            agent_id=self.card.id,
            name=self.card.name,
            capabilities=len(self.card.capabilities),
        )
        return self.card
