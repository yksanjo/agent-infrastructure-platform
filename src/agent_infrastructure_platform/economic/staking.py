"""Reputation staking system for economic security."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from agent_infrastructure_platform.common.types import AgentID

logger = structlog.get_logger()


@dataclass
class Stake:
    """A stake placed by an agent."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    agent_id: AgentID = ""
    
    # Stake details
    amount: Decimal = Decimal("0")
    currency: str = "credits"
    
    # What is being staked on
    stake_type: str = "reputation"  # reputation, service, dispute
    target_id: str = ""  # Agent, service, or dispute ID
    
    # Timing
    created_at: float = field(default_factory=time.time)
    locked_until: float | None = None
    
    # Status
    status: str = "active"  # active, slashed, withdrawn
    
    # Slashing
    slash_amount: Decimal = Decimal("0")
    slash_reason: str = ""


@dataclass
class SlashingEvent:
    """Record of a slashing event."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    stake_id: str = ""
    agent_id: AgentID = ""
    
    amount: Decimal = Decimal("0")
    reason: str = ""
    evidence: str = ""
    
    timestamp: float = field(default_factory=time.time)
    processed_by: str = ""  # Governance mechanism that processed


class StakingPool:
    """
    Reputation staking system for agent economic security.
    
    Agents stake tokens as collateral for:
    - Reputation guarantees
    - Service level agreements
    - Dispute resolution
    
    Features:
    - Slashing for misbehavior
    - Time-locked stakes
    - Reward distribution
    - Dispute resolution
    
    Example:
        ```python
        staking = StakingPool()
        
        # Agent stakes for reputation
        stake = await staking.stake(
            agent_id="agent-1",
            amount=Decimal("10000"),
            stake_type="reputation",
        )
        
        # Later, agent misbehaves
        await staking.slash(
            stake_id=stake.id,
            amount=Decimal("1000"),
            reason="Failed to complete task",
            evidence="task_logs_123",
        )
        
        # Agent withdraws remaining stake
        await staking.withdraw(stake.id)
        ```
    """

    def __init__(
        self,
        min_stake_amount: Decimal = Decimal("1000"),
        lock_period: float = 86400.0,  # 1 day
        slash_threshold: float = 0.1,  # 10% of stake
    ) -> None:
        self.min_stake_amount = min_stake_amount
        self.lock_period = lock_period
        self.slash_threshold = slash_threshold
        
        # Stakes
        self._stakes: dict[str, Stake] = {}
        self._agent_stakes: dict[AgentID, list[str]] = {}
        
        # Slashing history
        self._slashing_events: list[SlashingEvent] = []
        
        # Total staked
        self._total_staked: dict[str, Decimal] = {}
        
        # Rewards
        self._reward_pool: Decimal = Decimal("0")
        
        self._logger = logger
    
    async def stake(
        self,
        agent_id: AgentID,
        amount: Decimal,
        stake_type: str = "reputation",
        target_id: str = "",
        lock_period: float | None = None,
    ) -> Stake:
        """
        Create a new stake.
        
        Args:
            agent_id: Agent staking
            amount: Amount to stake
            stake_type: Type of stake
            target_id: Target of stake (optional)
            lock_period: Lock period (defaults to pool setting)
            
        Returns:
            Stake object
        """
        if amount < self.min_stake_amount:
            raise ValueError(f"Minimum stake is {self.min_stake_amount}")
        
        lock = lock_period or self.lock_period
        
        stake = Stake(
            agent_id=agent_id,
            amount=amount,
            stake_type=stake_type,
            target_id=target_id,
            locked_until=time.time() + lock,
        )
        
        self._stakes[stake.id] = stake
        
        if agent_id not in self._agent_stakes:
            self._agent_stakes[agent_id] = []
        self._agent_stakes[agent_id].append(stake.id)
        
        # Update totals
        if stake_type not in self._total_staked:
            self._total_staked[stake_type] = Decimal("0")
        self._total_staked[stake_type] += amount
        
        self._logger.info(
            "stake_created",
            stake_id=stake.id,
            agent_id=agent_id,
            amount=amount,
            stake_type=stake_type,
        )
        
        return stake
    
    async def slash(
        self,
        stake_id: str,
        amount: Decimal,
        reason: str,
        evidence: str = "",
        processed_by: str = "governance",
    ) -> bool:
        """
        Slash a stake for misbehavior.
        
        Args:
            stake_id: Stake to slash
            amount: Amount to slash
            reason: Reason for slashing
            evidence: Evidence reference
            processed_by: Entity processing the slash
            
        Returns:
            True if slashed
        """
        stake = self._stakes.get(stake_id)
        if not stake:
            return False
        
        if stake.status != "active":
            return False
        
        # Calculate actual slash amount
        available = stake.amount - stake.slash_amount
        actual_slash = min(amount, available)
        
        # Update stake
        stake.slash_amount += actual_slash
        stake.slash_reason = reason
        
        if stake.slash_amount >= stake.amount * Decimal(str(self.slash_threshold)):
            stake.status = "slashed"
        
        # Record event
        event = SlashingEvent(
            stake_id=stake_id,
            agent_id=stake.agent_id,
            amount=actual_slash,
            reason=reason,
            evidence=evidence,
            processed_by=processed_by,
        )
        self._slashing_events.append(event)
        
        # Update totals
        stake_type = stake.stake_type
        self._total_staked[stake_type] -= actual_slash
        
        # Add to reward pool
        self._reward_pool += actual_slash
        
        self._logger.warning(
            "stake_slashed",
            stake_id=stake_id,
            agent_id=stake.agent_id,
            amount=actual_slash,
            reason=reason,
        )
        
        return True
    
    async def withdraw(self, stake_id: str) -> Decimal:
        """
        Withdraw a stake.
        
        Args:
            stake_id: Stake to withdraw
            
        Returns:
            Amount withdrawn
        """
        stake = self._stakes.get(stake_id)
        if not stake:
            return Decimal("0")
        
        if stake.status != "active":
            return Decimal("0")
        
        # Check lock period
        if stake.locked_until and time.time() < stake.locked_until:
            raise ValueError("Stake is still locked")
        
        # Calculate withdrawable amount
        withdrawable = stake.amount - stake.slash_amount
        
        # Update stake
        stake.status = "withdrawn"
        
        # Update totals
        stake_type = stake.stake_type
        self._total_staked[stake_type] -= withdrawable
        
        self._logger.info(
            "stake_withdrawn",
            stake_id=stake_id,
            agent_id=stake.agent_id,
            amount=withdrawable,
        )
        
        return withdrawable
    
    async def get_stake(self, stake_id: str) -> Stake | None:
        """Get stake by ID."""
        return self._stakes.get(stake_id)
    
    async def get_agent_stakes(
        self,
        agent_id: AgentID,
        status: str | None = None,
    ) -> list[Stake]:
        """Get all stakes for an agent."""
        stake_ids = self._agent_stakes.get(agent_id, [])
        stakes = [self._stakes[sid] for sid in stake_ids if sid in self._stakes]
        
        if status:
            stakes = [s for s in stakes if s.status == status]
        
        return stakes
    
    async def get_total_staked(
        self,
        stake_type: str | None = None,
    ) -> Decimal:
        """Get total amount staked."""
        if stake_type:
            return self._total_staked.get(stake_type, Decimal("0"))
        return sum(self._total_staked.values(), Decimal("0"))
    
    async def get_slashing_history(
        self,
        agent_id: AgentID | None = None,
        limit: int = 100,
    ) -> list[SlashingEvent]:
        """Get slashing history."""
        events = self._slashing_events
        
        if agent_id:
            events = [e for e in events if e.agent_id == agent_id]
        
        return events[-limit:]
    
    async def distribute_rewards(
        self,
        eligible_agents: list[AgentID],
    ) -> dict[AgentID, Decimal]:
        """
        Distribute reward pool to eligible agents.
        
        Args:
            eligible_agents: Agents eligible for rewards
            
        Returns:
            Mapping of agent to reward amount
        """
        if not eligible_agents or self._reward_pool == 0:
            return {}
        
        reward_per_agent = self._reward_pool / len(eligible_agents)
        
        rewards = {}
        for agent_id in eligible_agents:
            rewards[agent_id] = reward_per_agent
        
        self._reward_pool = Decimal("0")
        
        self._logger.info(
            "rewards_distributed",
            eligible_agents=len(eligible_agents),
            total_rewards=self._reward_pool,
        )
        
        return rewards
    
    async def get_reputation_collateral(
        self,
        agent_id: AgentID,
    ) -> Decimal:
        """
        Get total collateral backing an agent's reputation.
        
        Args:
            agent_id: Agent to check
            
        Returns:
            Total staked amount
        """
        stakes = await self.get_agent_stakes(agent_id, status="active")
        return sum(s.amount - s.slash_amount for s in stakes)
