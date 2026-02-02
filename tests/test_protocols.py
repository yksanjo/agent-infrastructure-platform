"""Tests for communication protocols."""

import pytest
import asyncio

from agent_infrastructure_platform.protocols.mcp.types import (
    MCPRequest,
    MCPResourceRequest,
    MCPToolRequest,
    MCPServerCapabilities,
)
from agent_infrastructure_platform.protocols.a2a.types import (
    AgentCard,
    Skill,
    Task,
    TaskState,
    TaskStatus,
    Message,
    TextPart,
)
from agent_infrastructure_platform.protocols.acp.types import (
    ACPMessage,
    ACPMessageType,
    ACPMessagePriority,
)


class TestMCPProtocol:
    """Test MCP protocol types."""

    def test_mcp_request_creation(self):
        """Test creating MCP requests."""
        request = MCPRequest(
            method="tools/list",
            params={},
        )
        assert request.method == "tools/list"
        assert request.request_id is not None

    def test_resource_request(self):
        """Test resource request."""
        request = MCPResourceRequest(
            method="resources/read",
            uri="docs://api",
        )
        assert request.uri == "docs://api"

    def test_tool_request(self):
        """Test tool request."""
        request = MCPToolRequest(
            method="tools/call",
            name="search",
            arguments={"query": "test"},
        )
        assert request.name == "search"
        assert request.arguments["query"] == "test"

    def test_server_capabilities(self):
        """Test server capabilities."""
        caps = MCPServerCapabilities(
            resources=True,
            tools=True,
            prompts=False,
        )
        assert caps.resources is True
        assert caps.tools is True
        assert caps.prompts is False


class TestA2AProtocol:
    """Test A2A protocol types."""

    def test_agent_card_creation(self):
        """Test creating agent cards."""
        card = AgentCard(
            name="test-agent",
            url="http://localhost:8000",
            skills=[
                Skill(id="summarize", name="Text Summarization"),
            ],
        )
        assert card.name == "test-agent"
        assert len(card.skills) == 1

    def test_task_creation(self):
        """Test creating tasks."""
        task = Task(
            status=TaskStatus(state=TaskState.SUBMITTED),
        )
        assert task.status.state == TaskState.SUBMITTED
        assert task.id is not None

    def test_message_creation(self):
        """Test creating messages."""
        message = Message(
            role="user",
            parts=[TextPart(text="Hello")],
        )
        assert message.role == "user"
        assert len(message.parts) == 1


class TestACPProtocol:
    """Test ACP protocol types."""

    def test_acp_message_creation(self):
        """Test creating ACP messages."""
        message = ACPMessage(
            type=ACPMessageType.REQUEST,
            sender="agent-1",
            recipient="agent-2",
            payload={"action": "do_something"},
        )
        assert message.type == ACPMessageType.REQUEST
        assert message.sender == "agent-1"
        assert message.recipient == "agent-2"

    def test_message_priority(self):
        """Test message priorities."""
        message = ACPMessage(
            type=ACPMessageType.REQUEST,
            sender="agent-1",
            recipient="agent-2",
            payload={},
            priority=ACPMessagePriority.HIGH,
        )
        assert message.priority == ACPMessagePriority.HIGH


@pytest.mark.asyncio
class TestMCPClientServer:
    """Test MCP client-server interaction."""

    async def test_mcp_server_creation(self):
        """Test creating MCP server."""
        from agent_infrastructure_platform.protocols.mcp.server import MCPServer
        from agent_infrastructure_platform.protocols.mcp.types import MCPServerCapabilities
        
        server = MCPServer(
            name="test-server",
            capabilities=MCPServerCapabilities(tools=True),
        )
        assert server.info.name == "test-server"
        assert server.info.capabilities.tools is True

    async def test_resource_registration(self):
        """Test registering resources."""
        from agent_infrastructure_platform.protocols.mcp.server import MCPServer
        from agent_infrastructure_platform.protocols.mcp.types import MCPServerCapabilities
        
        server = MCPServer(name="test-server")
        
        @server.resource("test://data")
        async def get_data():
            return "test data"
        
        assert "test://data" in server._resources


@pytest.mark.asyncio
class TestA2AProtocolIntegration:
    """Test A2A protocol integration."""

    async def test_a2a_protocol_creation(self):
        """Test creating A2A protocol."""
        from agent_infrastructure_platform.protocols.a2a.protocol import A2AProtocol
        from agent_infrastructure_platform.protocols.a2a.types import AgentCard
        
        card = AgentCard(name="test-agent", url="http://localhost:8000")
        a2a = A2AProtocol(agent_card=card)
        
        assert a2a.agent_card.name == "test-agent"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
