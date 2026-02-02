"""A2A Protocol implementation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import structlog
from fastapi import FastAPI, HTTPException, WebSocket

from agent_infrastructure_platform.common.decorators import retry_with_backoff, trace_span
from agent_infrastructure_platform.common.exceptions import A2AError
from agent_infrastructure_platform.protocols.a2a.types import (
    AgentCard,
    CancelTaskRequest,
    CancelTaskResponse,
    ErrorCode,
    GetTaskRequest,
    GetTaskResponse,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    SendTaskRequest,
    SendTaskResponse,
    SendTaskStreamingRequest,
    SetTaskPushNotificationRequest,
    SetTaskPushNotificationResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskQueryParams,
    TaskSendParams,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

logger = structlog.get_logger()


class A2AProtocol:
    """
    Agent-to-Agent (A2A) Protocol implementation.
    
    A2A is Google's protocol for direct agent negotiation and delegation.
    It enables agents to discover each other, send tasks, and receive updates.
    
    This class can act as both client and server.
    
    Example (Server):
        ```python
        agent_card = AgentCard(
            name="my-agent",
            url="http://localhost:8000",
            skills=[Skill(id="summarize", name="Text Summarization")],
        )
        
        a2a = A2AProtocol(agent_card)
        
        @a2a.on_task
        async def handle_task(task: Task) -> Task:
            # Process task
            task.status.state = TaskState.COMPLETED
            return task
        
        await a2a.start_server()
        ```
    
    Example (Client):
        ```python
        a2a = A2AProtocol()
        
        # Discover agent
        card = await a2a.discover_agent("http://localhost:8000")
        
        # Send task
        task = await a2a.send_task(
            agent_url="http://localhost:8000",
            message=Message(role="user", parts=[TextPart(text="Hello!")]),
        )
        ```
    """

    def __init__(
        self,
        agent_card: AgentCard | None = None,
        host: str = "0.0.0.0",
        port: int = 8000,
    ) -> None:
        self.agent_card = agent_card
        self.host = host
        self.port = port
        
        # Task handlers
        self._task_handler: Callable[[Task], Awaitable[Task]] | None = None
        self._tasks: dict[str, Task] = {}
        
        # Streaming subscribers
        self._streaming_clients: dict[str, list[WebSocket]] = {}
        
        # HTTP client for outgoing requests
        self._client: httpx.AsyncClient | None = None
        
        # FastAPI app for server mode
        self._app: FastAPI | None = None
        if agent_card:
            self._setup_server()
        
        self._logger = logger.bind(
            agent_name=agent_card.name if agent_card else "client",
        )
    
    def _setup_server(self) -> None:
        """Set up FastAPI server."""
        self._app = FastAPI(title=self.agent_card.name, version=self.agent_card.version)
        
        @self._app.get("/.well-known/agent.json")
        async def get_agent_card() -> AgentCard:
            """Serve agent card (A2A discovery endpoint)."""
            return self.agent_card
        
        @self._app.post("/")
        async def handle_rpc(request: JSONRPCRequest) -> JSONRPCResponse:
            """Handle JSON-RPC requests."""
            return await self._handle_request(request)
        
        @self._app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            """WebSocket for streaming updates."""
            await self._handle_streaming_websocket(websocket)
    
    #region Server Mode
    
    def on_task[
        T
    ](self, handler: Callable[[Task], Awaitable[T]]) -> Callable[[Task], Awaitable[T]]:
        """Decorator to register a task handler."""
        self._task_handler = handler
        return handler
    
    def register_task_handler(
        self,
        handler: Callable[[Task], Awaitable[Task]],
    ) -> None:
        """Programmatically register a task handler."""
        self._task_handler = handler
    
    async def _handle_request(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """Route JSON-RPC request to appropriate handler."""
        try:
            if request.method == "tasks/send":
                req = SendTaskRequest(**request.model_dump())
                return await self._handle_send_task(req)
            
            elif request.method == "tasks/get":
                req = GetTaskRequest(**request.model_dump())
                return await self._handle_get_task(req)
            
            elif request.method == "tasks/cancel":
                req = CancelTaskRequest(**request.model_dump())
                return await self._handle_cancel_task(req)
            
            elif request.method == "tasks/sendSubscribe":
                # Streaming is handled via WebSocket
                return JSONRPCResponse(
                    id=request.id,
                    error=JSONRPCError(
                        code=ErrorCode.METHOD_NOT_FOUND,
                        message="Use WebSocket for streaming",
                    ),
                )
            
            else:
                return JSONRPCResponse(
                    id=request.id,
                    error=JSONRPCError(
                        code=ErrorCode.METHOD_NOT_FOUND,
                        message=f"Method not found: {request.method}",
                    ),
                )
                
        except Exception as e:
            self._logger.error("request_handler_error", error=str(e))
            return JSONRPCResponse(
                id=request.id,
                error=JSONRPCError(
                    code=ErrorCode.INTERNAL_ERROR,
                    message=str(e),
                ),
            )
    
    @trace_span()
    async def _handle_send_task(self, request: SendTaskRequest) -> SendTaskResponse:
        """Handle tasks/send request."""
        if not self._task_handler:
            return SendTaskResponse(
                id=request.id,
                error=JSONRPCError(
                    code=ErrorCode.INTERNAL_ERROR,
                    message="No task handler registered",
                ),
            )
        
        params = request.params
        
        # Create or get existing task
        if params.id and params.id in self._tasks:
            task = self._tasks[params.id]
            # Append message to existing task
            task.history.append(task.status)
        else:
            task = Task(
                id=params.id or f"task-{len(self._tasks)}",
                session_id=params.session_id,
                status=TaskStatus(state=TaskState.SUBMITTED),
                metadata=params.metadata,
            )
        
        # Update with new message
        task.status = TaskStatus(
            state=TaskState.WORKING,
            message=params.message,
        )
        self._tasks[task.id] = task
        
        self._logger.info("task_received", task_id=task.id)
        
        try:
            # Process task
            task = await self._task_handler(task)
            return SendTaskResponse(id=request.id, result=task)
        except Exception as e:
            self._logger.error("task_handler_error", task_id=task.id, error=str(e))
            task.status = TaskStatus(state=TaskState.FAILED)
            return SendTaskResponse(
                id=request.id,
                result=task,
                error=JSONRPCError(
                    code=ErrorCode.INTERNAL_ERROR,
                    message=str(e),
                ),
            )
    
    @trace_span()
    async def _handle_get_task(self, request: GetTaskRequest) -> GetTaskResponse:
        """Handle tasks/get request."""
        task_id = request.params.id
        
        if task_id not in self._tasks:
            return GetTaskResponse(
                id=request.id,
                error=JSONRPCError(
                    code=ErrorCode.TASK_NOT_FOUND,
                    message=f"Task not found: {task_id}",
                ),
            )
        
        task = self._tasks[task_id]
        
        # Trim history if requested
        if request.params.history_length is not None:
            task = task.model_copy()
            task.history = task.history[-request.params.history_length:]
        
        return GetTaskResponse(id=request.id, result=task)
    
    @trace_span()
    async def _handle_cancel_task(self, request: CancelTaskRequest) -> CancelTaskResponse:
        """Handle tasks/cancel request."""
        task_id = request.params.id
        
        if task_id not in self._tasks:
            return CancelTaskResponse(
                id=request.id,
                error=JSONRPCError(
                    code=ErrorCode.TASK_NOT_FOUND,
                    message=f"Task not found: {task_id}",
                ),
            )
        
        task = self._tasks[task_id]
        
        if task.status.state in (TaskState.COMPLETED, TaskState.CANCELED, TaskState.FAILED):
            return CancelTaskResponse(
                id=request.id,
                error=JSONRPCError(
                    code=ErrorCode.TASK_NOT_CANCELABLE,
                    message=f"Task is already {task.status.state}",
                ),
            )
        
        task.status = TaskStatus(state=TaskState.CANCELED)
        task.history.append(task.status)
        
        return CancelTaskResponse(id=request.id, result=task)
    
    async def _handle_streaming_websocket(self, websocket: WebSocket) -> None:
        """Handle WebSocket connections for streaming."""
        await websocket.accept()
        self._logger.info("streaming_client_connected")
        
        try:
            while True:
                data = await websocket.receive_json()
                request = JSONRPCRequest(**data)
                
                if request.method == "tasks/sendSubscribe":
                    # Subscribe to task updates
                    params = TaskSendParams(**request.params)
                    task_id = params.id or f"task-{len(self._tasks)}"
                    
                    if task_id not in self._streaming_clients:
                        self._streaming_clients[task_id] = []
                    self._streaming_clients[task_id].append(websocket)
                    
                    # Send initial task
                    task = Task(
                        id=task_id,
                        session_id=params.session_id,
                        status=TaskStatus(state=TaskState.SUBMITTED),
                    )
                    self._tasks[task_id] = task
                    
                    # Process task (should emit updates)
                    if self._task_handler:
                        task = await self._task_handler(task)
                
        except Exception as e:
            self._logger.error("websocket_error", error=str(e))
        finally:
            # Remove from all subscription lists
            for clients in self._streaming_clients.values():
                if websocket in clients:
                    clients.remove(websocket)
            self._logger.info("streaming_client_disconnected")
    
    async def _emit_status_update(self, task: Task, final: bool = False) -> None:
        """Emit status update to streaming clients."""
        if task.id not in self._streaming_clients:
            return
        
        event = TaskStatusUpdateEvent(
            id=task.id,
            status=task.status,
            final=final,
        )
        
        disconnected = []
        for ws in self._streaming_clients[task.id]:
            try:
                await ws.send_json(event.model_dump())
            except Exception:
                disconnected.append(ws)
        
        # Clean up disconnected clients
        for ws in disconnected:
            self._streaming_clients[task.id].remove(ws)
    
    #endregion
    
    #region Client Mode
    
    async def __aenter__(self) -> A2AProtocol:
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.disconnect()
    
    async def connect(self) -> None:
        """Initialize HTTP client for outgoing requests."""
        self._client = httpx.AsyncClient(timeout=60.0)
    
    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _ensure_connected(self) -> httpx.AsyncClient:
        """Ensure client is connected."""
        if not self._client:
            raise A2AError("Client not connected. Use 'async with' or call connect()")
        return self._client
    
    @trace_span()
    @retry_with_backoff(max_attempts=3, exceptions=(httpx.HTTPError,))
    async def discover_agent(self, url: str) -> AgentCard:
        """
        Discover an agent by fetching its Agent Card.
        
        Args:
            url: Agent URL
            
        Returns:
            Agent Card
        """
        client = self._ensure_connected()
        
        # Try well-known endpoint
        discovery_url = f"{url.rstrip('/')}/.well-known/agent.json"
        response = await client.get(discovery_url)
        response.raise_for_status()
        
        return AgentCard(**response.json())
    
    @trace_span()
    @retry_with_backoff(max_attempts=3, exceptions=(httpx.HTTPError,))
    async def send_task(
        self,
        agent_url: str,
        message: Any,  # Message type
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> Task:
        """
        Send a task to an agent.
        
        Args:
            agent_url: Target agent URL
            message: Message to send
            task_id: Optional task ID
            session_id: Optional session ID
            
        Returns:
            Task result
        """
        client = self._ensure_connected()
        
        params = TaskSendParams(
            id=task_id,
            session_id=session_id,
            message=message,
        )
        
        request = SendTaskRequest(params=params)
        
        response = await client.post(
            agent_url,
            json=request.model_dump(),
        )
        response.raise_for_status()
        
        result = SendTaskResponse(**response.json())
        
        if result.error:
            raise A2AError(f"Task failed: {result.error.message}")
        
        return result.result
    
    @trace_span()
    async def get_task(
        self,
        agent_url: str,
        task_id: str,
        history_length: int | None = None,
    ) -> Task:
        """
        Get task status and history.
        
        Args:
            agent_url: Target agent URL
            task_id: Task ID
            history_length: Number of history entries to include
            
        Returns:
            Task
        """
        client = self._ensure_connected()
        
        params = TaskQueryParams(
            id=task_id,
            history_length=history_length,
        )
        
        request = GetTaskRequest(params=params)
        
        response = await client.post(
            agent_url,
            json=request.model_dump(),
        )
        response.raise_for_status()
        
        result = GetTaskResponse(**response.json())
        
        if result.error:
            raise A2AError(f"Get task failed: {result.error.message}")
        
        return result.result
    
    @trace_span()
    async def cancel_task(self, agent_url: str, task_id: str) -> Task:
        """
        Cancel a task.
        
        Args:
            agent_url: Target agent URL
            task_id: Task ID
            
        Returns:
            Updated task
        """
        client = self._ensure_connected()
        
        from agent_infrastructure_platform.protocols.a2a.types import TaskCancelParams
        params = TaskCancelParams(id=task_id)
        
        request = CancelTaskRequest(params=params)
        
        response = await client.post(
            agent_url,
            json=request.model_dump(),
        )
        response.raise_for_status()
        
        result = CancelTaskResponse(**response.json())
        
        if result.error:
            raise A2AError(f"Cancel task failed: {result.error.message}")
        
        return result.result
    
    #endregion
    
    #region Server Lifecycle
    
    async def start_server(self) -> None:
        """Start the A2A server."""
        import uvicorn
        
        if not self._app:
            raise A2AError("No agent card provided. Cannot start server.")
        
        self._logger.info("a2a_server_starting", host=self.host, port=self.port)
        
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    def get_app(self) -> FastAPI | None:
        """Get the FastAPI application for external serving."""
        return self._app
    
    #endregion
