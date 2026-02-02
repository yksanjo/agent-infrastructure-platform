"""MCP Client implementation."""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from pydantic import BaseModel

from agent_infrastructure_platform.common.decorators import retry_with_backoff, trace_span
from agent_infrastructure_platform.common.exceptions import MCPError
from agent_infrastructure_platform.common.types import JSON
from agent_infrastructure_platform.protocols.mcp.types import (
    MCPError as MCPErrorResponse,
    MCPRequest,
    MCPResourceRequest,
    MCPResourceResponse,
    MCPToolRequest,
    MCPToolResponse,
    MCPServerInfo,
)

logger = structlog.get_logger()


class MCPClient:
    """
    Model Context Protocol (MCP) Client implementation.
    
    MCP clients connect to MCP servers to access resources and invoke tools.
    
    Example:
        ```python
        client = MCPClient("http://localhost:8000")
        
        # List resources
        resources = await client.list_resources()
        
        # Read a resource
        content = await client.read_resource("docs://api")
        
        # Call a tool
        result = await client.call_tool("search", {"query": "python"})
        ```
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = headers or {}
        
        self._client: httpx.AsyncClient | None = None
        self._server_info: MCPServerInfo | None = None
        self._logger = logger.bind(client_url=base_url)
    
    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.disconnect()
    
    async def connect(self) -> None:
        """Connect to the MCP server."""
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self.headers,
        )
        
        # Fetch server info
        self._server_info = await self.get_server_info()
        self._logger.info(
            "mcp_client_connected",
            server_name=self._server_info.name,
            version=self._server_info.version,
        )
    
    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._logger.info("mcp_client_disconnected")
    
    def _ensure_connected(self) -> httpx.AsyncClient:
        """Ensure client is connected."""
        if not self._client:
            raise MCPError("Client not connected. Use 'async with' or call connect()")
        return self._client
    
    @trace_span()
    async def get_server_info(self) -> MCPServerInfo:
        """Get server information and capabilities."""
        client = self._ensure_connected()
        response = await client.get(f"{self.base_url}/mcp/info")
        response.raise_for_status()
        return MCPServerInfo(**response.json())
    
    @trace_span()
    @retry_with_backoff(max_attempts=3, exceptions=(httpx.HTTPError,))
    async def list_resources(self) -> list[dict[str, Any]]:
        """List available resources from the server."""
        client = self._ensure_connected()
        response = await client.get(f"{self.base_url}/mcp/resources")
        response.raise_for_status()
        data = response.json()
        return data.get("resources", [])
    
    @trace_span()
    @retry_with_backoff(max_attempts=3, exceptions=(httpx.HTTPError,))
    async def read_resource(self, uri: str) -> MCPResourceResponse:
        """
        Read a resource by URI.
        
        Args:
            uri: Resource URI
            
        Returns:
            Resource response
        """
        client = self._ensure_connected()
        
        request = MCPResourceRequest(
            method="resources/read",
            uri=uri,
        )
        
        response = await client.post(
            f"{self.base_url}/mcp/resources/read",
            json=request.model_dump(),
        )
        response.raise_for_status()
        
        return MCPResourceResponse(**response.json())
    
    @trace_span()
    @retry_with_backoff(max_attempts=3, exceptions=(httpx.HTTPError,))
    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the server."""
        client = self._ensure_connected()
        response = await client.get(f"{self.base_url}/mcp/tools")
        response.raise_for_status()
        data = response.json()
        return data.get("tools", [])
    
    @trace_span()
    @retry_with_backoff(max_attempts=3, exceptions=(httpx.HTTPError,))
    async def call_tool(self, name: str, arguments: JSON = None) -> MCPToolResponse:
        """
        Call a tool on the server.
        
        Args:
            name: Tool name
            arguments: Tool arguments
            
        Returns:
            Tool response
        """
        client = self._ensure_connected()
        
        request = MCPToolRequest(
            method="tools/call",
            name=name,
            arguments=arguments or {},
        )
        
        response = await client.post(
            f"{self.base_url}/mcp/tools/call",
            json=request.model_dump(),
        )
        response.raise_for_status()
        
        return MCPToolResponse(**response.json())
    
    @trace_span()
    @retry_with_backoff(max_attempts=3, exceptions=(httpx.HTTPError,))
    async def list_prompts(self) -> list[str]:
        """List available prompts from the server."""
        client = self._ensure_connected()
        response = await client.get(f"{self.base_url}/mcp/prompts")
        response.raise_for_status()
        data = response.json()
        return data.get("prompts", [])
    
    async def read_resource_text(self, uri: str) -> str:
        """
        Convenience method to read a resource and return text content.
        
        Args:
            uri: Resource URI
            
        Returns:
            Text content of the resource
        """
        response = await self.read_resource(uri)
        
        if response.error:
            raise MCPError(f"Error reading resource: {response.error.message}")
        
        if not response.contents:
            raise MCPError("Resource returned empty content")
        
        content = response.contents[0]
        if content.text is not None:
            return content.text
        elif content.blob is not None:
            return content.blob.decode("utf-8")
        else:
            raise MCPError("Resource has no content")
    
    async def call_tool_json(self, name: str, arguments: JSON = None) -> JSON:
        """
        Convenience method to call a tool and return JSON result.
        
        Args:
            name: Tool name
            arguments: Tool arguments
            
        Returns:
            Parsed JSON result
        """
        import json
        
        response = await self.call_tool(name, arguments)
        
        if response.error:
            raise MCPError(f"Error calling tool: {response.error.message}")
        
        if response.is_error:
            raise MCPError("Tool returned error status")
        
        if not response.content:
            return None
        
        text_content = response.content[0].text
        if text_content:
            try:
                return json.loads(text_content)
            except json.JSONDecodeError:
                return text_content
        
        return None
