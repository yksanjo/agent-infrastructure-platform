"""Episodic Memory for per-agent interaction history."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent_infrastructure_platform.common.types import AgentID, Message, SessionID
from agent_infrastructure_platform.memory.backend import MemoryBackend

logger = structlog.get_logger()


class Episode(BaseModel):
    """A single episode in agent memory."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Content
    content: str
    embedding: list[float] | None = None
    
    # Context
    session_id: SessionID | None = None
    agent_id: AgentID | None = None
    
    # Metadata
    importance: float = 1.0  # 0-1, for memory consolidation
    category: str = "interaction"  # interaction, fact, reflection
    tags: list[str] = Field(default_factory=list)
    
    # Links
    related_episodes: list[str] = Field(default_factory=list)  # Episode IDs


class EpisodicMemory:
    """
    Episodic memory that survives agent restarts.
    
    Stores:
    - Conversations and interactions
    - Task execution history
    - Learned facts and insights
    
    Features:
    - Importance-based retention
    - Semantic search
    - Memory consolidation (summarization)
    """

    def __init__(
        self,
        backend: MemoryBackend | None = None,
        max_episodes: int = 10000,
        consolidation_threshold: int = 1000,
    ) -> None:
        self.backend = backend or MemoryBackend()
        self.max_episodes = max_episodes
        self.consolidation_threshold = consolidation_threshold
        
        self._logger = logger
    
    async def add_episode(
        self,
        content: str,
        agent_id: AgentID | None = None,
        session_id: SessionID | None = None,
        importance: float = 1.0,
        category: str = "interaction",
        embedding: list[float] | None = None,
        tags: list[str] | None = None,
    ) -> Episode:
        """Add a new episode to memory."""
        episode = Episode(
            content=content,
            agent_id=agent_id,
            session_id=session_id,
            importance=importance,
            category=category,
            embedding=embedding,
            tags=tags or [],
        )
        
        await self.backend.store(
            f"episode:{episode.id}",
            episode.model_dump(),
        )
        
        # Index by agent
        if agent_id:
            agent_episodes = await self.backend.get(f"agent_episodes:{agent_id}") or []
            agent_episodes.append(episode.id)
            await self.backend.store(f"agent_episodes:{agent_id}", agent_episodes)
        
        # Index by session
        if session_id:
            session_episodes = await self.backend.get(f"session_episodes:{session_id}") or []
            session_episodes.append(episode.id)
            await self.backend.store(f"session_episodes:{session_id}", session_episodes)
        
        self._logger.debug("episode_added", episode_id=episode.id, agent_id=agent_id)
        
        return episode
    
    async def get_episodes(
        self,
        agent_id: AgentID | None = None,
        session_id: SessionID | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[Episode]:
        """Retrieve episodes matching criteria."""
        episode_ids = []
        
        if agent_id:
            episode_ids = await self.backend.get(f"agent_episodes:{agent_id}") or []
        elif session_id:
            episode_ids = await self.backend.get(f"session_episodes:{session_id}") or []
        else:
            # Get all episodes (inefficient for large datasets)
            async for key, _ in self.backend.scan("episode:*"):
                episode_ids.append(key.split(":")[1])
        
        episodes = []
        for eid in episode_ids[:limit]:
            data = await self.backend.get(f"episode:{eid}")
            if data:
                episode = Episode(**data)
                if category is None or episode.category == category:
                    episodes.append(episode)
        
        # Sort by timestamp (newest first)
        episodes.sort(key=lambda e: e.timestamp, reverse=True)
        
        return episodes
    
    async def search(
        self,
        query_embedding: list[float],
        agent_id: AgentID | None = None,
        top_k: int = 5,
    ) -> list[tuple[Episode, float]]:
        """Semantic search through episodes."""
        episodes = await self.get_episodes(agent_id=agent_id, limit=self.max_episodes)
        
        import math
        
        results = []
        for episode in episodes:
            if episode.embedding is None:
                continue
            
            dot_product = sum(a * b for a, b in zip(query_embedding, episode.embedding))
            norm_a = math.sqrt(sum(x * x for x in query_embedding))
            norm_b = math.sqrt(sum(x * x for x in episode.embedding))
            
            if norm_a > 0 and norm_b > 0:
                similarity = dot_product / (norm_a * norm_b)
                results.append((episode, similarity))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
    
    async def consolidate(self, agent_id: AgentID) -> Episode | None:
        """
        Consolidate old episodes into a summary.
        
        Called when episode count exceeds threshold.
        """
        episodes = await self.get_episodes(agent_id=agent_id, limit=1000)
        
        if len(episodes) < self.consolidation_threshold:
            return None
        
        # Find oldest low-importance episodes
        to_consolidate = [
            e for e in episodes
            if e.importance < 0.5
        ][:100]
        
        if not to_consolidate:
            return None
        
        # Create summary (in production, use LLM for summarization)
        summary_content = f"Consolidated {len(to_consolidate)} episodes: " + \
            "; ".join(e.content[:50] + "..." for e in to_consolidate[:5])
        
        summary = await self.add_episode(
            content=summary_content,
            agent_id=agent_id,
            importance=0.8,
            category="consolidation",
        )
        
        # Remove consolidated episodes
        for episode in to_consolidate:
            await self.backend.delete(f"episode:{episode.id}")
        
        self._logger.info(
            "memory_consolidated",
            agent_id=agent_id,
            consolidated_count=len(to_consolidate),
        )
        
        return summary
