"""
Agent Infrastructure Platform (AIP)

The operating system for the trillion-agent economy.
Provides universal protocols, identity, memory, and governance for multi-agent systems.
"""

__version__ = "0.1.0"
__all__ = [
    "Agent",
    "AgentCard",
    "MCPClient",
    "MCPServer",
    "A2AProtocol",
    "ACPProtocol",
    "ANPProtocol",
    "MemoryBackend",
    "Orchestrator",
    "PolicyEngine",
    "IdentityManager",
]

from agent_infrastructure_platform.common.agent import Agent
from agent_infrastructure_platform.identity.agent_card import AgentCard
from agent_infrastructure_platform.protocols.mcp.client import MCPClient
from agent_infrastructure_platform.protocols.mcp.server import MCPServer
from agent_infrastructure_platform.protocols.a2a.protocol import A2AProtocol
from agent_infrastructure_platform.protocols.acp.protocol import ACPProtocol
from agent_infrastructure_platform.protocols.anp.protocol import ANPProtocol
from agent_infrastructure_platform.memory.backend import MemoryBackend
from agent_infrastructure_platform.orchestration.orchestrator import Orchestrator
from agent_infrastructure_platform.governance.policy import PolicyEngine
from agent_infrastructure_platform.identity.manager import IdentityManager
