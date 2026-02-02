"""Shared Memory & State Infrastructure."""

from agent_infrastructure_platform.memory.backend import MemoryBackend
from agent_infrastructure_platform.memory.hybrid import HybridMemoryStore
from agent_infrastructure_platform.memory.episodic import EpisodicMemory
from agent_infrastructure_platform.memory.consensus import ConsensusManager

__all__ = [
    "MemoryBackend",
    "HybridMemoryStore",
    "EpisodicMemory",
    "ConsensusManager",
]
