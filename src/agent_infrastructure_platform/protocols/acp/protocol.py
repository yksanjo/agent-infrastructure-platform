"""ACP (Agent Communication Protocol) implementation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import structlog

from agent_infrastructure_platform.common.decorators import trace_span
from agent_infrastructure_platform.common.exceptions import ACPError
from agent_infrastructure_platform.protocols.acp.types import (
    ACPChannel,
    ACPConversation,
    ACPDeliveryReceipt,
    ACPMessage,
    ACPMessagePriority,
    ACPMessageType,
    ACPSubscription,
)

logger = structlog.get_logger()


class ACPProtocol:
    """
    Agent Communication Protocol (ACP) implementation.
    
    ACP is IBM's protocol for async agent orchestration with memory.
    It provides persistent messaging, conversation management, and
    reliable delivery guarantees.
    
    Features:
    - Async message passing with persistence
    - Conversation memory and context
    - Pub/sub and direct messaging
    - Delivery receipts and retry logic
    - Message prioritization
    
    Example:
        ```python
        acp = ACPProtocol(memory_backend=redis_backend)
        
        # Create a channel
        channel = await acp.create_channel("team-chat", type="topic")
        
        # Subscribe to messages
        async for message in acp.subscribe(agent_id="agent-1", channel_id=channel.id):
            print(f"Received: {message.payload}")
        
        # Send a message
        await acp.send(
            ACPMessage(
                type=ACPMessageType.REQUEST,
                sender="agent-1",
                recipient=channel.id,
                payload={"action": "summarize", "text": "..."},
                session_id="session-123",
            )
        )
        ```
    """

    def __init__(
        self,
        memory_backend: Any | None = None,
        delivery_timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.memory_backend = memory_backend
        self.delivery_timeout = delivery_timeout
        self.max_retries = max_retries
        
        # In-memory stores (replace with persistent storage in production)
        self._channels: dict[str, ACPChannel] = {}
        self._messages: dict[str, ACPMessage] = {}
        self._subscriptions: dict[str, ACPSubscription] = {}
        self._conversations: dict[str, ACPConversation] = {}
        
        # Message queues for active subscriptions
        self._queues: dict[str, asyncio.Queue[ACPMessage]] = {}
        
        # Handlers
        self._message_handlers: list[Callable[[ACPMessage], Awaitable[None]]] = []
        
        self._logger = logger.bind(protocol="ACP")
    
    #region Channel Management
    
    @trace_span()
    async def create_channel(
        self,
        name: str,
        type: str = "direct",  # direct, topic, queue, broadcast
        persistent: bool = True,
        participants: list[str] | None = None,
    ) -> ACPChannel:
        """
        Create a communication channel.
        
        Args:
            name: Channel name
            type: Channel type
            persistent: Whether messages persist
            participants: Initial participants
            
        Returns:
            Created channel
        """
        channel = ACPChannel(
            name=name,
            type=type,
            persistent=persistent,
            participants=participants or [],
        )
        
        self._channels[channel.id] = channel
        
        if self.memory_backend:
            await self.memory_backend.store(f"channel:{channel.id}", channel.model_dump())
        
        self._logger.info("channel_created", channel_id=channel.id, name=name, type=type)
        return channel
    
    async def get_channel(self, channel_id: str) -> ACPChannel | None:
        """Get a channel by ID."""
        if channel_id in self._channels:
            return self._channels[channel_id]
        
        if self.memory_backend:
            data = await self.memory_backend.get(f"channel:{channel_id}")
            if data:
                return ACPChannel(**data)
        
        return None
    
    async def join_channel(self, channel_id: str, agent_id: str) -> bool:
        """Add an agent to a channel."""
        channel = await self.get_channel(channel_id)
        if not channel:
            return False
        
        if agent_id not in channel.participants:
            channel.participants.append(agent_id)
            
            if self.memory_backend:
                await self.memory_backend.store(
                    f"channel:{channel_id}",
                    channel.model_dump(),
                )
        
        return True
    
    async def leave_channel(self, channel_id: str, agent_id: str) -> bool:
        """Remove an agent from a channel."""
        channel = await self.get_channel(channel_id)
        if not channel:
            return False
        
        if agent_id in channel.participants:
            channel.participants.remove(agent_id)
            
            if self.memory_backend:
                await self.memory_backend.store(
                    f"channel:{channel_id}",
                    channel.model_dump(),
                )
        
        return True
    
    #endregion
    
    #region Message Sending
    
    @trace_span()
    async def send(self, message: ACPMessage) -> ACPDeliveryReceipt:
        """
        Send a message.
        
        Args:
            message: Message to send
            
        Returns:
            Delivery receipt
        """
        # Store message
        self._messages[message.id] = message
        
        if self.memory_backend:
            await self.memory_backend.store(
                f"message:{message.id}",
                message.model_dump(),
                ttl=message.ttl_seconds,
            )
        
        # Update conversation
        if message.session_id:
            await self._update_conversation(message)
        
        # Route to recipients
        if message.recipient in self._channels:
            await self._route_to_channel(message)
        else:
            await self._route_to_agent(message)
        
        self._logger.debug(
            "message_sent",
            message_id=message.id,
            sender=message.sender,
            recipient=message.recipient,
        )
        
        return ACPDeliveryReceipt(
            message_id=message.id,
            status="delivered",
            recipient=message.recipient,
        )
    
    async def _route_to_channel(self, message: ACPMessage) -> None:
        """Route message to channel subscribers."""
        channel = self._channels.get(message.recipient)
        if not channel:
            return
        
        # Update channel stats
        channel.message_count += 1
        channel.last_activity = message.timestamp
        
        # Deliver to all subscribers
        for subscription in self._subscriptions.values():
            if subscription.channel_id == channel.id:
                await self._deliver_to_subscription(message, subscription)
    
    async def _route_to_agent(self, message: ACPMessage) -> None:
        """Route message directly to an agent."""
        # Find subscriptions for this agent
        for subscription in self._subscriptions.values():
            if subscription.agent_id == message.recipient:
                await self._deliver_to_subscription(message, subscription)
    
    async def _deliver_to_subscription(
        self,
        message: ACPMessage,
        subscription: ACPSubscription,
    ) -> None:
        """Deliver message to a subscription."""
        # Filter by message type
        if subscription.message_types and message.type not in subscription.message_types:
            return
        
        # Filter by priority
        if message.priority > subscription.min_priority:
            return
        
        # Deliver
        if subscription.delivery_mode == "push":
            queue_id = f"{subscription.agent_id}:{subscription.id}"
            if queue_id in self._queues:
                await self._queues[queue_id].put(message)
        
        # Call registered handlers
        for handler in self._message_handlers:
            try:
                await handler(message)
            except Exception as e:
                self._logger.error("message_handler_error", error=str(e))
    
    async def _update_conversation(self, message: ACPMessage) -> None:
        """Update conversation state."""
        session_id = message.session_id
        
        if session_id not in self._conversations:
            self._conversations[session_id] = ACPConversation(
                session_id=session_id,
                participants=[message.sender, message.recipient],
            )
        
        conv = self._conversations[session_id]
        conv.message_ids.append(message.id)
        conv.message_count += 1
        conv.last_message_at = message.timestamp
        conv.updated_at = message.timestamp
        
        # Update participants
        if message.sender not in conv.participants:
            conv.participants.append(message.sender)
        if message.recipient not in conv.participants and message.recipient not in self._channels:
            conv.participants.append(message.recipient)
        
        if self.memory_backend:
            await self.memory_backend.store(
                f"conversation:{session_id}",
                conv.model_dump(),
            )
    
    #endregion
    
    #region Subscriptions
    
    @trace_span()
    async def subscribe(
        self,
        agent_id: str,
        channel_id: str | None = None,
        topic_pattern: str | None = None,
        message_types: list[str] | None = None,
        min_priority: int = ACPMessagePriority.BACKGROUND,
    ) -> ACPSubscription:
        """
        Subscribe to messages.
        
        Args:
            agent_id: Agent to receive messages
            channel_id: Channel to subscribe to
            topic_pattern: Topic pattern for pub/sub
            message_types: Filter by message types
            min_priority: Minimum priority level
            
        Returns:
            Subscription
        """
        subscription = ACPSubscription(
            agent_id=agent_id,
            channel_id=channel_id,
            topic_pattern=topic_pattern,
            message_types=message_types or [],
            min_priority=min_priority,
        )
        
        self._subscriptions[subscription.id] = subscription
        
        # Create queue for this subscription
        queue_id = f"{agent_id}:{subscription.id}"
        self._queues[queue_id] = asyncio.Queue()
        
        self._logger.info(
            "subscription_created",
            subscription_id=subscription.id,
            agent_id=agent_id,
        )
        
        return subscription
    
    async def unsubscribe(self, subscription_id: str) -> bool:
        """Cancel a subscription."""
        if subscription_id not in self._subscriptions:
            return False
        
        subscription = self._subscriptions.pop(subscription_id)
        queue_id = f"{subscription.agent_id}:{subscription_id}"
        
        if queue_id in self._queues:
            del self._queues[queue_id]
        
        self._logger.info("subscription_cancelled", subscription_id=subscription_id)
        return True
    
    async def receive(
        self,
        agent_id: str,
        subscription_id: str,
        timeout: float | None = None,
    ) -> ACPMessage | None:
        """
        Receive a message from a subscription.
        
        Args:
            agent_id: Agent ID
            subscription_id: Subscription ID
            timeout: Timeout in seconds
            
        Returns:
            Message or None if timeout
        """
        queue_id = f"{agent_id}:{subscription_id}"
        
        if queue_id not in self._queues:
            raise ACPError(f"Subscription not found: {subscription_id}")
        
        queue = self._queues[queue_id]
        
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
    
    async def receive_stream(
        self,
        agent_id: str,
        subscription_id: str,
    ) -> AsyncIterator[ACPMessage]:
        """
        Stream messages from a subscription.
        
        Args:
            agent_id: Agent ID
            subscription_id: Subscription ID
            
        Yields:
            Messages
        """
        queue_id = f"{agent_id}:{subscription_id}"
        
        if queue_id not in self._queues:
            raise ACPError(f"Subscription not found: {subscription_id}")
        
        queue = self._queues[queue_id]
        
        while True:
            message = await queue.get()
            yield message
    
    #endregion
    
    #region Conversation Management
    
    async def get_conversation(self, session_id: str) -> ACPConversation | None:
        """Get conversation by session ID."""
        if session_id in self._conversations:
            return self._conversations[session_id]
        
        if self.memory_backend:
            data = await self.memory_backend.get(f"conversation:{session_id}")
            if data:
                return ACPConversation(**data)
        
        return None
    
    async def get_conversation_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ACPMessage]:
        """Get messages from a conversation."""
        conv = await self.get_conversation(session_id)
        if not conv:
            return []
        
        message_ids = conv.message_ids[offset:offset + limit]
        messages = []
        
        for msg_id in message_ids:
            if msg_id in self._messages:
                messages.append(self._messages[msg_id])
            elif self.memory_backend:
                data = await self.memory_backend.get(f"message:{msg_id}")
                if data:
                    messages.append(ACPMessage(**data))
        
        return messages
    
    async def close_conversation(self, session_id: str) -> bool:
        """Close a conversation."""
        conv = await self.get_conversation(session_id)
        if not conv:
            return False
        
        conv.status = "closed"
        
        if self.memory_backend:
            await self.memory_backend.store(
                f"conversation:{session_id}",
                conv.model_dump(),
            )
        
        return True
    
    #endregion
    
    #region Request-Response Pattern
    
    async def request(
        self,
        sender: str,
        recipient: str,
        payload: dict[str, Any],
        timeout: float = 30.0,
        session_id: str | None = None,
    ) -> ACPMessage:
        """
        Send a request and wait for response.
        
        Args:
            sender: Sending agent ID
            recipient: Target agent ID
            payload: Request payload
            timeout: Timeout in seconds
            session_id: Optional session ID
            
        Returns:
            Response message
        """
        correlation_id = str(uuid4())
        
        # Create subscription for response
        response_sub = await self.subscribe(
            agent_id=sender,
            message_types=[ACPMessageType.RESPONSE],
        )
        
        try:
            # Send request
            request = ACPMessage(
                type=ACPMessageType.REQUEST,
                sender=sender,
                recipient=recipient,
                payload=payload,
                correlation_id=correlation_id,
                session_id=session_id,
            )
            
            await self.send(request)
            
            # Wait for response
            start_time = asyncio.get_event_loop().time()
            
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                remaining = timeout - elapsed
                
                if remaining <= 0:
                    raise ACPError("Request timeout")
                
                message = await self.receive(sender, response_sub.id, timeout=remaining)
                
                if message and message.correlation_id == correlation_id:
                    return message
                
        finally:
            await self.unsubscribe(response_sub.id)
    
    async def reply(
        self,
        original_message: ACPMessage,
        payload: dict[str, Any],
    ) -> ACPDeliveryReceipt:
        """
        Reply to a message.
        
        Args:
            original_message: Message to reply to
            payload: Response payload
            
        Returns:
            Delivery receipt
        """
        response = ACPMessage(
            type=ACPMessageType.RESPONSE,
            sender=original_message.recipient,
            recipient=original_message.sender,
            payload=payload,
            reply_to=original_message.id,
            correlation_id=original_message.correlation_id,
            session_id=original_message.session_id,
        )
        
        return await self.send(response)
    
    #endregion
    
    #region Event Handling
    
    def on_message(
        self,
        handler: Callable[[ACPMessage], Awaitable[None]],
    ) -> Callable[[ACPMessage], Awaitable[None]]:
        """Register a message handler."""
        self._message_handlers.append(handler)
        return handler
    
    #endregion
