"""MCP Server implementation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel

from agent_infrastructure_platform.common.decorators import trace_span
from agent_infrastructure_platform.common.types import AgentID, JSON, Resource, Tool
from agent_infrastructure_platform.protocols.mcp.types import (
    MCPError,
    MCPRequest,
    MCPResourceContent,
    MCPResourceRequest,
    MCPResourceResponse,
    MCPResponse,
    MCPServerCapabilities,
    MCPServerInfo,
    MCPToolContent,
    MCPToolRequest,
    MCPToolResponse,
)

logger = structlog.get_logger()


class MCPServer:
    """
    Model Context Protocol (MCP) Server implementation.
    
    MCP servers provide resources, tools, and prompts to agents via a standardized protocol.
    This is Anthropic's protocol for agent-tool/data interaction.
    
    Example:
        ```python
        server = MCPServer(
            name="my-mcp-server",
            capabilities=MCPServerCapabilities(resources=True, tools=True),
        )
        
        @server.resource("docs://api")
        async def get_api_docs() -> str:
            return "API documentation..."
        
        @server.tool("search")
        async def search(query: str) -> dict:
            return {"results": [...]}
        
        await server.start()
        ```
    """

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        capabilities: MCPServerCapabilities | None = None,
        host: str = "0.0.0.0",
        port: int = 8000,
    ) -> None:
        self.info = MCPServerInfo(
            name=name,
            version=version,
            capabilities=capabilities or MCPServerCapabilities(),
        )
        self.host = host
        self.port = port
        
        # Resource handlers: uri -> handler function
        self._resources: dict[str, Callable[[], Awaitable[str | bytes]]] = {}
        self._resource_metadata: dict[str, dict[str, Any]] = {}
        
        # Tool handlers: name -> handler function
        self._tools: dict[str, Callable[..., Awaitable[JSON]]] = {}
        self._tool_schemas: dict[str, Tool] = {}
        
        # Prompt handlers: name -> handler function
        self._prompts: dict[str, Callable[..., Awaitable[str]]] = {}
        
        # Active connections
        self._clients: set[AgentID] = set()
        
        # FastAPI app
        self._app = FastAPI(title=name, version=version)
        self._setup_routes()
        
        self._logger = logger.bind(server_name=name)
    
    def _setup_routes(self) -> None:
        """Set up FastAPI routes."""
        
        @self._app.get("/mcp/info")
        async def get_info() -> MCPServerInfo:
            """Get server information and capabilities."""
            return self.info
        
        @self._app.get("/mcp/resources")
        async def list_resources() -> dict[str, Any]:
            """List available resources."""
            return {
                "resources": [
                    {
                        "uri": uri,
                        "name": meta.get("name", uri),
                        "mime_type": meta.get("mime_type", "text/plain"),
                        "description": meta.get("description", ""),
                    }
                    for uri, meta in self._resource_metadata.items()
                ]
            }
        
        @self._app.post("/mcp/resources/read")
        async def read_resource(request: MCPResourceRequest) -> MCPResourceResponse:
            """Read a resource by URI."""
            return await self._handle_resource_request(request)
        
        @self._app.get("/mcp/tools")
        async def list_tools() -> dict[str, Any]:
            """List available tools."""
            return {
                "tools": [
                    {
                        "name": name,
                        "description": schema.description,
                        "parameters": schema.parameters,
                    }
                    for name, schema in self._tool_schemas.items()
                ]
            }
        
        @self._app.post("/mcp/tools/call")
        async def call_tool(request: MCPToolRequest) -> MCPToolResponse:
            """Call a tool."""
            return await self._handle_tool_request(request)
        
        @self._app.get("/mcp/prompts")
        async def list_prompts() -> dict[str, Any]:
            """List available prompts."""
            return {"prompts": list(self._prompts.keys())}
        
        @self._app.websocket("/mcp/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            """WebSocket endpoint for real-time communication."""
            await self._handle_websocket(websocket)
    
    #region Resource Registration
    
    def resource(
        self,
        uri: str,
        *,
        name: str | None = None,
        description: str = "",
        mime_type: str = "text/plain",
    ) -> Callable[[Callable[[], Awaitable[str | bytes]]], Callable[[], Awaitable[str | bytes]]]:
        """
        Decorator to register a resource handler.
        
        Args:
            uri: Resource URI (e.g., "docs://api", "config://settings")
            name: Human-readable name
            description: Resource description
            mime_type: MIME type of the resource
        """

        def decorator(handler: Callable[[], Awaitable[str | bytes]]) -> Callable[[], Awaitable[str | bytes]]:
            self._resources[uri] = handler
            self._resource_metadata[uri] = {
                "name": name or uri,
                "description": description,
                "mime_type": mime_type,
            }
            self._logger.debug("resource_registered", uri=uri)
            return handler

        return decorator
    
    def register_resource(
        self,
        uri: str,
        handler: Callable[[], Awaitable[str | bytes]],
        *,
        name: str | None = None,
        description: str = "",
        mime_type: str = "text/plain",
    ) -> None:
        """Programmatically register a resource handler."""
        self._resources[uri] = handler
        self._resource_metadata[uri] = {
            "name": name or uri,
            "description": description,
            "mime_type": mime_type,
        }
    
    #endregion
    
    #region Tool Registration
    
    def tool(
        self,
        name: str,
        *,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> Callable[[Callable[..., Awaitable[JSON]]], Callable[..., Awaitable[JSON]]]:
        """
        Decorator to register a tool handler.
        
        Args:
            name: Tool name
            description: Tool description
            parameters: JSON schema for tool parameters
        """

        def decorator(handler: Callable[..., Awaitable[JSON]]) -> Callable[..., Awaitable[JSON]]:
            self._tools[name] = handler
            self._tool_schemas[name] = Tool(
                name=name,
                description=description,
                parameters=parameters or {"type": "object", "properties": {}},
            )
            self._logger.debug("tool_registered", name=name)
            return handler

        return decorator
    
    def register_tool(
        self,
        name: str,
        handler: Callable[..., Awaitable[JSON]],
        *,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Programmatically register a tool handler."""
        self._tools[name] = handler
        self._tool_schemas[name] = Tool(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
        )
    
    #endregion
    
    #region Prompt Registration
    
    def prompt(
        self,
        name: str,
    ) -> Callable[[Callable[..., Awaitable[str]]], Callable[..., Awaitable[str]]]:
        """
        Decorator to register a prompt template.
        
        Args:
            name: Prompt name
        """

        def decorator(handler: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
            self._prompts[name] = handler
            self._logger.debug("prompt_registered", name=name)
            return handler

        return decorator
    
    #endregion
    
    #region Request Handlers
    
    @trace_span()
    async def _handle_resource_request(self, request: MCPResourceRequest) -> MCPResourceResponse:
        """Handle a resource read request."""
        uri = request.uri
        
        if uri not in self._resources:
            return MCPResourceResponse(
                request_id=request.request_id,
                error=MCPError(
                    code=-32602,
                    message=f"Resource not found: {uri}",
                ),
            )
        
        try:
            handler = self._resources[uri]
            data = await handler()
            meta = self._resource_metadata[uri]
            
            content = MCPResourceContent(
                uri=uri,
                mime_type=meta.get("mime_type", "text/plain"),
                text=data if isinstance(data, str) else None,
                blob=data if isinstance(data, bytes) else None,
            )
            
            return MCPResourceResponse(
                request_id=request.request_id,
                contents=[content],
            )
            
        except Exception as e:
            self._logger.error("resource_handler_error", uri=uri, error=str(e))
            return MCPResourceResponse(
                request_id=request.request_id,
                error=MCPError(
                    code=-32603,
                    message=f"Error reading resource: {str(e)}",
                ),
            )
    
    @trace_span()
    async def _handle_tool_request(self, request: MCPToolRequest) -> MCPToolResponse:
        """Handle a tool call request."""
        name = request.name
        
        if name not in self._tools:
            return MCPToolResponse(
                request_id=request.request_id,
                error=MCPError(
                    code=-32601,
                    message=f"Tool not found: {name}",
                ),
                is_error=True,
            )
        
        try:
            handler = self._tools[name]
            result = await handler(**request.arguments)
            
            # Convert result to content
            if isinstance(result, str):
                content = [MCPToolContent(type="text", text=result)]
            elif isinstance(result, dict):
                import json
                content = [MCPToolContent(type="text", text=json.dumps(result))]
            elif isinstance(result, list):
                import json
                content = [MCPToolContent(type="text", text=json.dumps(result))]
            else:
                content = [MCPToolContent(type="text", text=str(result))]
            
            return MCPToolResponse(
                request_id=request.request_id,
                content=content,
            )
            
        except Exception as e:
            self._logger.error("tool_handler_error", name=name, error=str(e))
            return MCPToolResponse(
                request_id=request.request_id,
                error=MCPError(
                    code=-32603,
                    message=f"Error calling tool: {str(e)}",
                ),
                is_error=True,
            )
    
    #endregion
    
    #region WebSocket
    
    async def _handle_websocket(self, websocket: WebSocket) -> None:
        """Handle WebSocket connections."""
        await websocket.accept()
        self._logger.info("websocket_connected")
        
        try:
            while True:
                # Receive message
                data = await websocket.receive_json()
                request = MCPRequest(**data)
                
                # Process based on method
                if request.method == "resources/read":
                    resource_req = MCPResourceRequest(**data)
                    response = await self._handle_resource_request(resource_req)
                elif request.method == "tools/call":
                    tool_req = MCPToolRequest(**data)
                    response = await self._handle_tool_request(tool_req)
                else:
                    response = MCPResponse(
                        request_id=request.request_id,
                        error=MCPError(
                            code=-32601,
                            message=f"Method not found: {request.method}",
                        ),
                    )
                
                # Send response
                await websocket.send_json(response.model_dump())
                
        except Exception as e:
            self._logger.error("websocket_error", error=str(e))
        finally:
            self._logger.info("websocket_disconnected")
    
    #endregion
    
    #region Server Lifecycle
    
    async def start(self) -> None:
        """Start the MCP server."""
        import uvicorn
        
        self._logger.info(
            "mcp_server_starting",
            host=self.host,
            port=self.port,
            resources=len(self._resources),
            tools=len(self._tools),
        )
        
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    def get_app(self) -> FastAPI:
        """Get the FastAPI application for external serving."""
        return self._app
    
    #endregion
