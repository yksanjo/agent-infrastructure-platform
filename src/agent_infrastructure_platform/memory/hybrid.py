"""Hybrid Vector + Graph Memory Store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator
from uuid import uuid4

import structlog
from pydantic import BaseModel

from agent_infrastructure_platform.common.types import AgentID
from agent_infrastructure_platform.memory.backend import MemoryBackend

logger = structlog.get_logger()


@dataclass
class VectorEntry:
    """Entry in vector storage."""
    
    id: str
    content: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] | None = None
    agent_id: str | None = None


@dataclass  
class GraphNode:
    """Node in graph storage."""
    
    id: str
    label: str
    properties: dict[str, Any]


@dataclass
class GraphEdge:
    """Edge in graph storage."""
    
    source: str
    target: str
    relation: str
    properties: dict[str, Any] | None = None


class HybridMemoryStore:
    """
    Hybrid Vector + Graph Memory Store.
    
    Combines:
    - Vector storage for semantic similarity search
    - Graph storage for relational queries
    
    This enables:
    - "Find similar concepts" (vector search)
    - "Find related entities" (graph traversal)
    - "Find similar concepts that are related to X" (hybrid)
    
    Example:
        ```python
        memory = HybridMemoryStore()
        
        # Store with embedding
        await memory.store_vector(
            content="Machine learning is a subset of AI",
            embedding=[0.1, 0.2, ...],
            metadata={"topic": "AI"},
        )
        
        # Store relationship
        await memory.store_relation(
            source="ML",
            target="AI",
            relation="is_subset_of",
        )
        
        # Semantic search
        results = await memory.semantic_search(
            query_embedding=[0.1, 0.2, ...],
            top_k=5,
        )
        
        # Graph query
        related = await memory.get_related("AI", depth=2)
        ```
    """

    def __init__(
        self,
        vector_backend: MemoryBackend | None = None,
        graph_backend: MemoryBackend | None = None,
        embedding_dimension: int = 768,
    ) -> None:
        self.vector_backend = vector_backend or MemoryBackend()
        self.graph_backend = graph_backend or MemoryBackend()
        self.embedding_dimension = embedding_dimension
        
        # In-memory indexes (replace with proper indexes in production)
        self._vectors: dict[str, VectorEntry] = {}
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, list[GraphEdge]] = {}  # source -> edges
        self._relations: dict[str, list[GraphEdge]] = {}  # relation -> edges
        
        self._logger = logger
    
    #region Vector Operations
    
    async def store_vector(
        self,
        content: str,
        embedding: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
        agent_id: str | None = None,
        entry_id: str | None = None,
    ) -> str:
        """
        Store a vector entry.
        
        Args:
            content: Text content
            embedding: Vector embedding (generated if not provided)
            metadata: Additional metadata
            agent_id: Owning agent
            entry_id: Optional ID
            
        Returns:
            Entry ID
        """
        entry_id = entry_id or str(uuid4())
        
        entry = VectorEntry(
            id=entry_id,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
            agent_id=agent_id,
        )
        
        self._vectors[entry_id] = entry
        
        # Also store in backend
        await self.vector_backend.store(
            f"vector:{entry_id}",
            {
                "id": entry_id,
                "content": content,
                "embedding": embedding,
                "metadata": metadata,
                "agent_id": agent_id,
            },
        )
        
        self._logger.debug("vector_stored", entry_id=entry_id, agent_id=agent_id)
        
        return entry_id
    
    async def semantic_search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        agent_id: str | None = None,
        threshold: float = 0.7,
    ) -> list[tuple[VectorEntry, float]]:
        """
        Semantic search using cosine similarity.
        
        Args:
            query_embedding: Query vector
            top_k: Number of results
            agent_id: Filter by agent
            threshold: Minimum similarity score
            
        Returns:
            List of (entry, score) tuples
        """
        import math
        
        results = []
        
        for entry in self._vectors.values():
            # Filter by agent if specified
            if agent_id and entry.agent_id != agent_id:
                continue
            
            if entry.embedding is None:
                continue
            
            # Calculate cosine similarity
            dot_product = sum(a * b for a, b in zip(query_embedding, entry.embedding))
            norm_a = math.sqrt(sum(x * x for x in query_embedding))
            norm_b = math.sqrt(sum(x * x for x in entry.embedding))
            
            if norm_a == 0 or norm_b == 0:
                similarity = 0
            else:
                similarity = dot_product / (norm_a * norm_b)
            
            if similarity >= threshold:
                results.append((entry, similarity))
        
        # Sort by similarity (descending)
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]
    
    async def get_vector(self, entry_id: str) -> VectorEntry | None:
        """Get a vector entry by ID."""
        return self._vectors.get(entry_id)
    
    #endregion
    
    #region Graph Operations
    
    async def store_node(
        self,
        label: str,
        properties: dict[str, Any],
        node_id: str | None = None,
    ) -> str:
        """
        Store a graph node.
        
        Args:
            label: Node label/type
            properties: Node properties
            node_id: Optional ID
            
        Returns:
            Node ID
        """
        node_id = node_id or str(uuid4())
        
        node = GraphNode(
            id=node_id,
            label=label,
            properties=properties,
        )
        
        self._nodes[node_id] = node
        
        await self.graph_backend.store(
            f"node:{node_id}",
            {
                "id": node_id,
                "label": label,
                "properties": properties,
            },
        )
        
        self._logger.debug("node_stored", node_id=node_id, label=label)
        
        return node_id
    
    async def store_relation(
        self,
        source: str,
        target: str,
        relation: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        Store a relationship between nodes.
        
        Args:
            source: Source node ID
            target: Target node ID
            relation: Relationship type
            properties: Edge properties
        """
        edge = GraphEdge(
            source=source,
            target=target,
            relation=relation,
            properties=properties or {},
        )
        
        # Add to source's edges
        if source not in self._edges:
            self._edges[source] = []
        self._edges[source].append(edge)
        
        # Add to relation index
        if relation not in self._relations:
            self._relations[relation] = []
        self._relations[relation].append(edge)
        
        await self.graph_backend.store(
            f"edge:{source}:{target}:{relation}",
            {
                "source": source,
                "target": target,
                "relation": relation,
                "properties": properties,
            },
        )
        
        self._logger.debug("relation_stored", source=source, target=target, relation=relation)
    
    async def get_related(
        self,
        node_id: str,
        relation: str | None = None,
        depth: int = 1,
    ) -> list[GraphNode]:
        """
        Get nodes related to a given node.
        
        Args:
            node_id: Starting node
            relation: Filter by relation type
            depth: Traversal depth
            
        Returns:
            List of related nodes
        """
        visited = {node_id}
        current_level = {node_id}
        all_related = []
        
        for _ in range(depth):
            next_level = set()
            
            for node in current_level:
                edges = self._edges.get(node, [])
                
                for edge in edges:
                    if relation and edge.relation != relation:
                        continue
                    
                    target_id = edge.target
                    if target_id not in visited:
                        visited.add(target_id)
                        next_level.add(target_id)
                        
                        if target_id in self._nodes:
                            all_related.append(self._nodes[target_id])
            
            current_level = next_level
            if not current_level:
                break
        
        return all_related
    
    async def find_path(
        self,
        source: str,
        target: str,
        max_depth: int = 5,
    ) -> list[GraphEdge] | None:
        """
        Find a path between two nodes using BFS.
        
        Args:
            source: Source node ID
            target: Target node ID
            max_depth: Maximum search depth
            
        Returns:
            List of edges forming the path, or None if no path
        """
        from collections import deque
        
        queue = deque([(source, [])])
        visited = {source}
        
        while queue:
            current, path = queue.popleft()
            
            if len(path) > max_depth:
                continue
            
            if current == target and path:
                return path
            
            for edge in self._edges.get(current, []):
                if edge.target not in visited:
                    visited.add(edge.target)
                    queue.append((edge.target, path + [edge]))
        
        return None
    
    #endregion
    
    #region Hybrid Queries
    
    async def semantic_graph_search(
        self,
        query_embedding: list[float],
        start_node: str,
        top_k: int = 5,
        depth: int = 2,
    ) -> list[tuple[VectorEntry, float, list[GraphNode]]]:
        """
        Hybrid search: Find similar content within graph neighborhood.
        
        Args:
            query_embedding: Query vector
            start_node: Starting graph node
            top_k: Number of results
            depth: Graph traversal depth
            
        Returns:
            List of (entry, score, path) tuples
        """
        # Get neighborhood nodes
        neighborhood = await self.get_related(start_node, depth=depth)
        neighborhood_ids = {n.id for n in neighborhood}
        neighborhood_ids.add(start_node)
        
        # Search vectors from neighborhood
        results = []
        
        for entry_id, entry in self._vectors.items():
            # Check if entry belongs to neighborhood
            if entry.metadata and "node_id" in entry.metadata:
                if entry.metadata["node_id"] not in neighborhood_ids:
                    continue
            
            # Calculate similarity
            if entry.embedding is None:
                continue
            
            import math
            dot_product = sum(a * b for a, b in zip(query_embedding, entry.embedding))
            norm_a = math.sqrt(sum(x * x for x in query_embedding))
            norm_b = math.sqrt(sum(x * x for x in entry.embedding))
            
            if norm_a > 0 and norm_b > 0:
                similarity = dot_product / (norm_a * norm_b)
                
                # Find path from start_node to this entry's node
                if entry.metadata and "node_id" in entry.metadata:
                    path = await self.find_path(start_node, entry.metadata["node_id"])
                    results.append((entry, similarity, path or []))
        
        # Sort by similarity
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]
    
    #endregion
