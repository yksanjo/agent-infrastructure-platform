"""ANP (Agent Network Protocol) implementation for agent discovery."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent_infrastructure_platform.common.decorators import retry_with_backoff, trace_span
from agent_infrastructure_platform.common.exceptions import ANPError
from agent_infrastructure_platform.common.types import AgentID, Capability, JSON

logger = structlog.get_logger()


class AgentRegistryEntry(BaseModel):
    """Entry in the agent registry."""

    model_config = ConfigDict(frozen=False)

    agent_id: AgentID
    name: str
    description: str = ""
    version: str = "1.0.0"
    
    # Endpoints
    url: str
    protocols: list[str] = Field(default_factory=list)
    
    # Capabilities
    capabilities: list[Capability] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    
    # Identity
    public_key: str | None = None
    credentials: list[str] = Field(default_factory=list)
    
    # Metadata
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    # Status
    status: str = "active"  # active, inactive, suspended
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    health_score: float = 1.0  # 0-1
    reputation_score: float = 1.0  # 0-1
    
    # Registration
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None


class AgentQuery(BaseModel):
    """Query for agent discovery."""

    model_config = ConfigDict(frozen=True)

    # Capability filters
    required_capabilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    
    # Protocol filters
    supported_protocols: list[str] = Field(default_factory=list)
    
    # Metadata filters
    tags: list[str] = Field(default_factory=list)
    status: str | None = "active"
    
    # Reputation filters
    min_health_score: float = 0.0
    min_reputation_score: float = 0.0
    
    # Pagination
    page: int = 1
    page_size: int = 20


class DiscoveryResult(BaseModel):
    """Result of agent discovery."""

    model_config = ConfigDict(frozen=True)

    agents: list[AgentRegistryEntry]
    total: int
    page: int
    page_size: int
    has_more: bool


class ANPProtocol:
    """
    Agent Network Protocol (ANP) implementation.
    
    ANP provides agent discovery and identity resolution.
    It enables agents to find each other based on capabilities,
    skills, and reputation.
    
    Can operate as:
    - Client: Query remote registries
    - Server: Host a registry
    - P2P: Distributed discovery
    
    Example (Registry Server):
        ```python
        anp = ANPProtocol()
        
        @anp.on_register
        async def validate_registration(entry: AgentRegistryEntry):
            # Validate before allowing registration
            return True
        
        await anp.start_registry(host="0.0.0.0", port=8000)
        ```
    
    Example (Discovery Client):
        ```python
        anp = ANPProtocol()
        
        # Search for agents
        results = await anp.discover(
            registry_url="http://registry.example.com",
            query=AgentQuery(
                required_capabilities=["text-generation"],
                min_reputation_score=0.8,
            ),
        )
        
        for agent in results.agents:
            print(f"Found: {agent.name} at {agent.url}")
        ```
    """

    def __init__(
        self,
        registry_url: str | None = None,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self.registry_url = registry_url
        self.cache_ttl_seconds = cache_ttl_seconds
        
        # Local registry (when running as server)
        self._registry: dict[AgentID, AgentRegistryEntry] = {}
        self._capability_index: dict[str, set[AgentID]] = {}
        self._skill_index: dict[str, set[AgentID]] = {}
        
        # Cache for remote queries
        self._cache: dict[str, tuple[DiscoveryResult, datetime]] = {}
        
        # HTTP client
        self._client: httpx.AsyncClient | None = None
        
        # Validation handlers
        self._register_validators: list[callable] = []
        
        self._logger = logger.bind(protocol="ANP")
    
    async def __aenter__(self) -> ANPProtocol:
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.disconnect()
    
    async def connect(self) -> None:
        """Initialize HTTP client."""
        self._client = httpx.AsyncClient(timeout=30.0)
    
    async func disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _ensure_connected(self) -> httpx.AsyncClient:
        """Ensure client is connected."""
        if not self._client:
            raise ANPError("Client not connected. Use 'async with' or call connect()")
        return self._client
    
    #region Registry Operations (Server)
    
    @trace_span()
    async def register(self, entry: AgentRegistryEntry) -> bool:
        """
        Register an agent in the local registry.
        
        Args:
            entry: Agent registry entry
            
        Returns:
            True if registration successful
        """
        # Run validators
        for validator in self._register_validators:
            if not await validator(entry):
                self._logger.warning(
                    "registration_rejected",
                    agent_id=entry.agent_id,
                )
                return False
        
        # Store entry
        self._registry[entry.agent_id] = entry
        
        # Update indexes
        for cap in entry.capabilities:
            if cap.name not in self._capability_index:
                self._capability_index[cap.name] = set()
            self._capability_index[cap.name].add(entry.agent_id)
        
        for skill in entry.skills:
            if skill not in self._skill_index:
                self._skill_index[skill] = set()
            self._skill_index[skill].add(entry.agent_id)
        
        self._logger.info(
            "agent_registered",
            agent_id=entry.agent_id,
            name=entry.name,
            capabilities=len(entry.capabilities),
        )
        
        return True
    
    @trace_span()
    async def unregister(self, agent_id: AgentID) -> bool:
        """
        Unregister an agent.
        
        Args:
            agent_id: Agent to unregister
            
        Returns:
            True if unregistered, False if not found
        """
        if agent_id not in self._registry:
            return False
        
        entry = self._registry.pop(agent_id)
        
        # Update indexes
        for cap in entry.capabilities:
            if cap.name in self._capability_index:
                self._capability_index[cap.name].discard(agent_id)
        
        for skill in entry.skills:
            if skill in self._skill_index:
                self._skill_index[skill].discard(agent_id)
        
        self._logger.info("agent_unregistered", agent_id=agent_id)
        return True
    
    @trace_span()
    async def heartbeat(self, agent_id: AgentID) -> bool:
        """
        Update agent's last seen timestamp.
        
        Args:
            agent_id: Agent ID
            
        Returns:
            True if agent found and updated
        """
        if agent_id not in self._registry:
            return False
        
        entry = self._registry[agent_id]
        entry.last_seen = datetime.utcnow()
        
        return True
    
    @trace_span()
    async def query(self, query: AgentQuery) -> DiscoveryResult:
        """
        Query the local registry.
        
        Args:
            query: Search query
            
        Returns:
            Discovery results
        """
        results: list[AgentRegistryEntry] = []
        
        # Start with all active agents or filter by status
        candidates = [
            entry for entry in self._registry.values()
            if query.status is None or entry.status == query.status
        ]
        
        for entry in candidates:
            # Check capability requirements
            entry_caps = {cap.name for cap in entry.capabilities}
            if not all(cap in entry_caps for cap in query.required_capabilities):
                continue
            
            # Check skill requirements
            if not all(skill in entry.skills for skill in query.required_skills):
                continue
            
            # Check protocol requirements
            if query.supported_protocols:
                if not all(proto in entry.protocols for proto in query.supported_protocols):
                    continue
            
            # Check tags
            if query.tags:
                if not any(tag in entry.tags for tag in query.tags):
                    continue
            
            # Check reputation
            if entry.health_score < query.min_health_score:
                continue
            if entry.reputation_score < query.min_reputation_score:
                continue
            
            results.append(entry)
        
        # Sort by reputation (highest first)
        results.sort(key=lambda e: e.reputation_score, reverse=True)
        
        # Paginate
        total = len(results)
        start = (query.page - 1) * query.page_size
        end = start + query.page_size
        page_results = results[start:end]
        
        return DiscoveryResult(
            agents=page_results,
            total=total,
            page=query.page,
            page_size=query.page_size,
            has_more=end < total,
        )
    
    async def get_agent(self, agent_id: AgentID) -> AgentRegistryEntry | None:
        """Get a specific agent by ID."""
        return self._registry.get(agent_id)
    
    #endregion
    
    #region Discovery (Client)
    
    @trace_span()
    @retry_with_backoff(max_attempts=3, exceptions=(httpx.HTTPError,))
    async def discover(
        self,
        query: AgentQuery | None = None,
        registry_url: str | None = None,
        use_cache: bool = True,
    ) -> DiscoveryResult:
        """
        Discover agents from a remote registry.
        
        Args:
            query: Search query
            registry_url: Registry URL (defaults to configured registry)
            use_cache: Whether to use cached results
            
        Returns:
            Discovery results
        """
        url = registry_url or self.registry_url
        if not url:
            raise ANPError("No registry URL configured")
        
        query = query or AgentQuery()
        
        # Check cache
        cache_key = f"{url}:{query.model_dump_json()}"
        if use_cache and cache_key in self._cache:
            result, cached_at = self._cache[cache_key]
            age = (datetime.utcnow() - cached_at).total_seconds()
            if age < self.cache_ttl_seconds:
                self._logger.debug("discovery_cache_hit", age_seconds=age)
                return result
        
        # Query remote registry
        client = self._ensure_connected()
        
        response = await client.post(
            f"{url}/anp/discover",
            json=query.model_dump(),
        )
        response.raise_for_status()
        
        result = DiscoveryResult(**response.json())
        
        # Update cache
        if use_cache:
            self._cache[cache_key] = (result, datetime.utcnow())
        
        self._logger.info(
            "discovery_completed",
            registry=url,
            total=result.total,
            returned=len(result.agents),
        )
        
        return result
    
    @trace_span()
    async def find_agent_by_capability(
        self,
        capability: str,
        min_reputation: float = 0.5,
        registry_url: str | None = None,
    ) -> AgentRegistryEntry | None:
        """
        Find the best agent for a specific capability.
        
        Args:
            capability: Required capability
            min_reputation: Minimum reputation score
            registry_url: Registry URL
            
        Returns:
            Best matching agent or None
        """
        results = await self.discover(
            query=AgentQuery(
                required_capabilities=[capability],
                min_reputation_score=min_reputation,
                page_size=1,
            ),
            registry_url=registry_url,
        )
        
        if results.agents:
            return results.agents[0]
        return None
    
    @trace_span()
    async def find_agents_by_skill(
        self,
        skill: str,
        limit: int = 10,
        registry_url: str | None = None,
    ) -> list[AgentRegistryEntry]:
        """
        Find agents with a specific skill.
        
        Args:
            skill: Required skill
            limit: Maximum results
            registry_url: Registry URL
            
        Returns:
            Matching agents
        """
        results = await self.discover(
            query=AgentQuery(
                required_skills=[skill],
                page_size=limit,
            ),
            registry_url=registry_url,
        )
        
        return results.agents
    
    #endregion
    
    #region Registration (Client)
    
    @trace_span()
    @retry_with_backoff(max_attempts=3, exceptions=(httpx.HTTPError,))
    async def register_with_registry(
        self,
        entry: AgentRegistryEntry,
        registry_url: str | None = None,
    ) -> bool:
        """
        Register with a remote registry.
        
        Args:
            entry: Agent registry entry
            registry_url: Registry URL
            
        Returns:
            True if registration successful
        """
        url = registry_url or self.registry_url
        if not url:
            raise ANPError("No registry URL configured")
        
        client = self._ensure_connected()
        
        response = await client.post(
            f"{url}/anp/register",
            json=entry.model_dump(),
        )
        response.raise_for_status()
        
        result = response.json()
        success = result.get("success", False)
        
        if success:
            self._logger.info(
                "registered_with_registry",
                agent_id=entry.agent_id,
                registry=url,
            )
        else:
            self._logger.warning(
                "registration_failed",
                agent_id=entry.agent_id,
                registry=url,
                reason=result.get("reason"),
            )
        
        return success
    
    @trace_span()
    async def send_heartbeat(self, agent_id: AgentID, registry_url: str | None = None) -> bool:
        """
        Send heartbeat to registry.
        
        Args:
            agent_id: Agent ID
            registry_url: Registry URL
            
        Returns:
            True if heartbeat acknowledged
        """
        url = registry_url or self.registry_url
        if not url:
            raise ANPError("No registry URL configured")
        
        client = self._ensure_connected()
        
        try:
            response = await client.post(
                f"{url}/anp/heartbeat",
                json={"agent_id": agent_id},
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            self._logger.error("heartbeat_failed", error=str(e))
            return False
    
    #endregion
    
    #region Validation
    
    def on_register(
        self,
        validator: callable,
    ) -> callable:
        """Register a validation handler for new registrations."""
        self._register_validators.append(validator)
        return validator
    
    #endregion
    
    #region Registry Server
    
    def get_registry_app(self) -> Any:
        """Get FastAPI app for registry server."""
        from fastapi import FastAPI, HTTPException
        
        app = FastAPI(title="ANP Registry")
        
        @app.post("/anp/register")
        async def register_endpoint(entry: AgentRegistryEntry) -> dict[str, Any]:
            success = await self.register(entry)
            if not success:
                raise HTTPException(status_code=400, detail="Registration rejected")
            return {"success": True, "agent_id": entry.agent_id}
        
        @app.post("/anp/unregister")
        async def unregister_endpoint(agent_id: AgentID) -> dict[str, Any]:
            success = await self.unregister(agent_id)
            return {"success": success}
        
        @app.post("/anp/discover")
        async def discover_endpoint(query: AgentQuery) -> DiscoveryResult:
            return await self.query(query)
        
        @app.get("/anp/agent/{agent_id}")
        async def get_agent_endpoint(agent_id: AgentID) -> AgentRegistryEntry:
            entry = await self.get_agent(agent_id)
            if not entry:
                raise HTTPException(status_code=404, detail="Agent not found")
            return entry
        
        @app.post("/anp/heartbeat")
        async def heartbeat_endpoint(data: dict[str, str]) -> dict[str, Any]:
            agent_id = data.get("agent_id")
            if not agent_id:
                raise HTTPException(status_code=400, detail="agent_id required")
            success = await self.heartbeat(AgentID(agent_id))
            return {"success": success}
        
        return app
    
    async def start_registry(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """Start the registry server."""
        import uvicorn
        
        app = self.get_registry_app()
        
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
    
    #endregion
