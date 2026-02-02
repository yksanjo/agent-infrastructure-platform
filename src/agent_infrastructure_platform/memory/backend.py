"""Memory backend interface for agent storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class MemoryBackend(ABC):
    """
    Abstract base class for memory backends.
    
    Implementations include:
    - RedisMemory: Redis-based key-value storage
    - QdrantMemory: Vector database for semantic search
    - Neo4jMemory: Graph database for relational queries
    - HybridMemory: Combined vector + graph storage
    """

    @abstractmethod
    async def store(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        namespace: str | None = None,
    ) -> bool:
        """
        Store a value.
        
        Args:
            key: Storage key
            value: Value to store
            ttl: Time-to-live in seconds
            namespace: Optional namespace
            
        Returns:
            True if stored successfully
        """
        pass

    @abstractmethod
    async def get(
        self,
        key: str,
        namespace: str | None = None,
    ) -> Any | None:
        """
        Retrieve a value.
        
        Args:
            key: Storage key
            namespace: Optional namespace
            
        Returns:
            Stored value or None
        """
        pass

    @abstractmethod
    async def delete(
        self,
        key: str,
        namespace: str | None = None,
    ) -> bool:
        """
        Delete a value.
        
        Args:
            key: Storage key
            namespace: Optional namespace
            
        Returns:
            True if deleted
        """
        pass

    @abstractmethod
    async def exists(
        self,
        key: str,
        namespace: str | None = None,
    ) -> bool:
        """Check if key exists."""
        pass

    @abstractmethod
    async def scan(
        self,
        pattern: str,
        namespace: str | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """
        Scan keys matching pattern.
        
        Args:
            pattern: Key pattern (e.g., "user:*")
            namespace: Optional namespace
            
        Yields:
            (key, value) tuples
        """
        pass

    @abstractmethod
    async def clear(self, namespace: str | None = None) -> bool:
        """Clear all data in namespace."""
        pass


class InMemoryBackend(MemoryBackend):
    """In-memory implementation for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}  # namespace -> {key: value}
        self._ttl: dict[str, dict[str, float]] = {}  # namespace -> {key: expiry}

    def _get_ns(self, namespace: str | None) -> dict[str, Any]:
        """Get or create namespace."""
        ns = namespace or "default"
        if ns not in self._data:
            self._data[ns] = {}
            self._ttl[ns] = {}
        return self._data[ns]

    async def store(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        namespace: str | None = None,
    ) -> bool:
        import time
        ns = self._get_ns(namespace)
        ns[key] = value
        
        if ttl:
            self._ttl[namespace or "default"][key] = time.time() + ttl
        
        return True

    async def get(
        self,
        key: str,
        namespace: str | None = None,
    ) -> Any | None:
        import time
        ns = namespace or "default"
        
        # Check TTL
        if ns in self._ttl and key in self._ttl[ns]:
            if time.time() > self._ttl[ns][key]:
                await self.delete(key, namespace)
                return None
        
        data_ns = self._get_ns(namespace)
        return data_ns.get(key)

    async def delete(
        self,
        key: str,
        namespace: str | None = None,
    ) -> bool:
        ns = namespace or "default"
        
        if ns in self._data and key in self._data[ns]:
            del self._data[ns][key]
            if ns in self._ttl and key in self._ttl[ns]:
                del self._ttl[ns][key]
            return True
        return False

    async def exists(
        self,
        key: str,
        namespace: str | None = None,
    ) -> bool:
        return await self.get(key, namespace) is not None

    async def scan(
        self,
        pattern: str,
        namespace: str | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        import fnmatch
        ns = self._get_ns(namespace)
        
        for key, value in ns.items():
            if fnmatch.fnmatch(key, pattern):
                yield (key, value)

    async def clear(self, namespace: str | None = None) -> bool:
        ns = namespace or "default"
        
        if ns in self._data:
            self._data[ns] = {}
        if ns in self._ttl:
            self._ttl[ns] = {}
        
        return True
