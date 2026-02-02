"""Swarm Coordination for agent collectives."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import structlog

from agent_infrastructure_platform.common.types import AgentID, Task

logger = structlog.get_logger()


@dataclass
class SwarmConfig:
    """Configuration for a swarm."""
    
    name: str
    coordinator_id: AgentID
    
    # Consensus settings
    consensus_type: str = "majority"  # majority, unanimous, leader
    vote_timeout: float = 30.0
    
    # Membership
    min_agents: int = 1
    max_agents: int = 100
    
    # Task allocation
    allocation_strategy: str = "round_robin"  # round_robin, capability, bid


@dataclass
class SwarmVote:
    """A vote in swarm decision-making."""
    
    proposal_id: str
    voter: AgentID
    vote: bool
    reason: str = ""
    timestamp: float = field(default_factory=lambda: __import__('time').time())


class SwarmCoordinator:
    """
    Coordinates a swarm of agents.
    
    Features:
    - Dynamic membership
    - Consensus-based decisions
    - Task allocation
    - Leader election
    
    Example:
        ```python
        swarm = SwarmCoordinator(
            SwarmConfig(
                name="research-swarm",
                coordinator_id=leader_agent.id,
            )
        )
        
        # Add agents
        await swarm.join(agent_1)
        await swarm.join(agent_2)
        
        # Propose action
        result = await swarm.propose(
            action="accept_task",
            proposal={"task_id": "123", "reward": 100},
        )
        
        if result["consensus"]:
            # Execute
            await swarm.distribute_task(task)
        ```
    """

    def __init__(self, config: SwarmConfig) -> None:
        self.config = config
        self.id = f"swarm-{uuid4().hex[:12]}"
        
        # Members
        self._members: dict[AgentID, dict[str, Any]] = {}
        self._member_tasks: dict[AgentID, asyncio.Task] = {}
        
        # Consensus
        self._active_proposals: dict[str, dict[str, Any]] = {}
        self._votes: dict[str, list[SwarmVote]] = {}
        
        # Task allocation
        self._task_queue: asyncio.Queue[Task] = asyncio.Queue()
        self._allocated_tasks: dict[str, AgentID] = {}
        self._round_robin_index = 0
        
        # Callbacks
        self._on_join: list[Callable[[AgentID], Awaitable[None]]] = []
        self._on_leave: list[Callable[[AgentID], Awaitable[None]]] = []
        
        self._logger = logger.bind(swarm_id=self.id, swarm_name=config.name)
    
    async def join(
        self,
        agent_id: AgentID,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Add an agent to the swarm.
        
        Args:
            agent_id: Agent to add
            capabilities: Agent capabilities
            metadata: Additional metadata
            
        Returns:
            True if joined successfully
        """
        if len(self._members) >= self.config.max_agents:
            self._logger.warning("swarm_full", agent_id=agent_id)
            return False
        
        self._members[agent_id] = {
            "capabilities": capabilities or [],
            "metadata": metadata or {},
            "joined_at": asyncio.get_event_loop().time(),
            "task_count": 0,
        }
        
        self._logger.info("agent_joined", agent_id=agent_id, members=len(self._members))
        
        # Notify callbacks
        for callback in self._on_join:
            try:
                await callback(agent_id)
            except Exception as e:
                self._logger.error("join_callback_error", error=str(e))
        
        return True
    
    async def leave(self, agent_id: AgentID) -> bool:
        """Remove an agent from the swarm."""
        if agent_id not in self._members:
            return False
        
        del self._members[agent_id]
        
        if agent_id in self._member_tasks:
            self._member_tasks[agent_id].cancel()
            del self._member_tasks[agent_id]
        
        self._logger.info("agent_left", agent_id=agent_id, members=len(self._members))
        
        # Notify callbacks
        for callback in self._on_leave:
            try:
                await callback(agent_id)
            except Exception as e:
                self._logger.error("leave_callback_error", error=str(e))
        
        return True
    
    async def propose(
        self,
        action: str,
        proposal: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Propose an action to the swarm.
        
        Args:
            action: Action type
            proposal: Proposal details
            timeout: Voting timeout
            
        Returns:
            Consensus result
        """
        proposal_id = f"prop-{uuid4().hex[:8]}"
        timeout = timeout or self.config.vote_timeout
        
        self._active_proposals[proposal_id] = {
            "action": action,
            "proposal": proposal,
            "started_at": asyncio.get_event_loop().time(),
        }
        self._votes[proposal_id] = []
        
        self._logger.info(
            "proposal_created",
            proposal_id=proposal_id,
            action=action,
        )
        
        # Wait for votes
        await asyncio.sleep(timeout)
        
        # Count votes
        votes = self._votes.get(proposal_id, [])
        yes_votes = sum(1 for v in votes if v.vote)
        no_votes = len(votes) - yes_votes
        
        # Determine consensus
        consensus = False
        if self.config.consensus_type == "unanimous":
            consensus = yes_votes == len(self._members) and no_votes == 0
        elif self.config.consensus_type == "majority":
            consensus = yes_votes > len(self._members) / 2
        elif self.config.consensus_type == "leader":
            # Leader decides
            consensus = yes_votes >= 1  # Simplified
        
        result = {
            "proposal_id": proposal_id,
            "consensus": consensus,
            "yes_votes": yes_votes,
            "no_votes": no_votes,
            "total_members": len(self._members),
        }
        
        # Cleanup
        del self._active_proposals[proposal_id]
        del self._votes[proposal_id]
        
        return result
    
    async def vote(
        self,
        proposal_id: str,
        agent_id: AgentID,
        vote: bool,
        reason: str = "",
    ) -> bool:
        """Cast a vote on a proposal."""
        if proposal_id not in self._active_proposals:
            return False
        
        if agent_id not in self._members:
            return False
        
        swarm_vote = SwarmVote(
            proposal_id=proposal_id,
            voter=agent_id,
            vote=vote,
            reason=reason,
        )
        
        self._votes[proposal_id].append(swarm_vote)
        
        return True
    
    async def distribute_task(self, task: Task) -> AgentID | None:
        """
        Distribute a task to a swarm member.
        
        Args:
            task: Task to distribute
            
        Returns:
            Assigned agent ID or None
        """
        if not self._members:
            return None
        
        agent_id: AgentID | None = None
        
        if self.config.allocation_strategy == "round_robin":
            # Round-robin allocation
            members = list(self._members.keys())
            agent_id = members[self._round_robin_index % len(members)]
            self._round_robin_index += 1
        
        elif self.config.allocation_strategy == "capability":
            # Find agent with required capabilities
            required = [c.name for c in task.required_capabilities]
            for aid, info in self._members.items():
                if all(cap in info["capabilities"] for cap in required):
                    agent_id = aid
                    break
        
        elif self.config.allocation_strategy == "bid":
            # Placeholder for auction-based allocation
            agent_id = list(self._members.keys())[0]
        
        if agent_id:
            self._members[agent_id]["task_count"] += 1
            self._allocated_tasks[task.id] = agent_id
            
            self._logger.info(
                "task_distributed",
                task_id=task.id,
                agent_id=agent_id,
            )
        
        return agent_id
    
    def get_members(self) -> list[AgentID]:
        """Get list of swarm members."""
        return list(self._members.keys())
    
    def get_status(self) -> dict[str, Any]:
        """Get swarm status."""
        return {
            "id": self.id,
            "name": self.config.name,
            "members": len(self._members),
            "member_ids": list(self._members.keys()),
            "active_proposals": len(self._active_proposals),
            "task_queue_size": self._task_queue.qsize(),
            "allocated_tasks": len(self._allocated_tasks),
        }
    
    def on_join(self, callback: Callable[[AgentID], Awaitable[None]]) -> None:
        """Register a callback for when an agent joins."""
        self._on_join.append(callback)
    
    def on_leave(self, callback: Callable[[AgentID], Awaitable[None]]) -> None:
        """Register a callback for when an agent leaves."""
        self._on_leave.append(callback)
