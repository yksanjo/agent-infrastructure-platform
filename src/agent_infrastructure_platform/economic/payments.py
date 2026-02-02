"""Micropayment system for agent-to-agent transactions."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from agent_infrastructure_platform.common.types import AgentID

logger = structlog.get_logger()


@dataclass
class Payment:
    """A single payment."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    sender: AgentID = ""
    recipient: AgentID = ""
    amount: Decimal = Decimal("0")
    currency: str = "credits"
    
    # Metadata
    timestamp: float = field(default_factory=time.time)
    description: str = ""
    service_id: str = ""  # For service payments
    
    # State
    status: str = "pending"  # pending, completed, failed, refunded
    
    # Verification
    signature: str = ""
    
    def compute_hash(self) -> str:
        """Compute payment hash."""
        data = f"{self.id}:{self.sender}:{self.recipient}:{self.amount}:{self.timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()


@dataclass
class PaymentChannel:
    """State channel for off-chain micropayments."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    agent_a: AgentID = ""
    agent_b: AgentID = ""
    
    # Balances
    balance_a: Decimal = Decimal("0")
    balance_b: Decimal = Decimal("0")
    total_deposited: Decimal = Decimal("0")
    
    # State
    nonce: int = 0  # Monotonically increasing
    is_open: bool = True
    
    # Timing
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    
    # Latest signed state
    latest_state: dict[str, Any] = field(default_factory=dict)
    
    def deposit(self, agent: AgentID, amount: Decimal) -> bool:
        """Deposit funds into channel."""
        if not self.is_open:
            return False
        
        if agent == self.agent_a:
            self.balance_a += amount
        elif agent == self.agent_b:
            self.balance_b += amount
        else:
            return False
        
        self.total_deposited += amount
        return True
    
    def transfer(
        self,
        from_agent: AgentID,
        to_agent: AgentID,
        amount: Decimal,
    ) -> bool:
        """Transfer within channel (off-chain)."""
        if not self.is_open:
            return False
        
        # Check balances
        if from_agent == self.agent_a:
            if self.balance_a < amount:
                return False
            self.balance_a -= amount
            self.balance_b += amount
        elif from_agent == self.agent_b:
            if self.balance_b < amount:
                return False
            self.balance_b -= amount
            self.balance_a += amount
        else:
            return False
        
        self.nonce += 1
        return True
    
    def close(self) -> dict[str, Decimal]:
        """Close channel and return final balances."""
        self.is_open = False
        return {
            self.agent_a: self.balance_a,
            self.agent_b: self.balance_b,
        }


class PaymentProcessor:
    """
    Process micropayments between agents.
    
    Features:
    - State channels for off-chain payments
    - On-chain settlement
    - Multi-currency support
    - Automatic routing
    
    Example:
        ```python
        processor = PaymentProcessor()
        
        # Open payment channel
        channel = await processor.open_channel(
            agent_a="agent-1",
            agent_b="agent-2",
            deposit_a=Decimal("1000"),
            deposit_b=Decimal("1000"),
        )
        
        # Make off-chain payment
        success = channel.transfer(
            from_agent="agent-1",
            to_agent="agent-2",
            amount=Decimal("10"),
        )
        
        # Close and settle
        final_balances = channel.close()
        await processor.settle(channel)
        ```
    """

    def __init__(
        self,
        settlement_interval: float = 3600.0,  # 1 hour
        min_channel_deposit: Decimal = Decimal("100"),
    ) -> None:
        self.settlement_interval = settlement_interval
        self.min_channel_deposit = min_channel_deposit
        
        # Active channels
        self._channels: dict[str, PaymentChannel] = {}
        self._agent_channels: dict[AgentID, list[str]] = {}
        
        # Pending settlements
        self._pending_settlements: list[PaymentChannel] = []
        
        # Transaction history
        self._transactions: list[Payment] = []
        
        # Agent balances (on-chain)
        self._balances: dict[AgentID, Decimal] = {}
        
        self._logger = logger
    
    async def open_channel(
        self,
        agent_a: AgentID,
        agent_b: AgentID,
        deposit_a: Decimal = Decimal("0"),
        deposit_b: Decimal = Decimal("0"),
    ) -> PaymentChannel:
        """
        Open a payment channel between two agents.
        
        Args:
            agent_a: First agent
            agent_b: Second agent
            deposit_a: Initial deposit from agent_a
            deposit_b: Initial deposit from agent_b
            
        Returns:
            Payment channel
        """
        # Check minimum deposits
        if deposit_a < self.min_channel_deposit or deposit_b < self.min_channel_deposit:
            raise ValueError(f"Minimum deposit is {self.min_channel_deposit}")
        
        # Create channel
        channel = PaymentChannel(
            agent_a=agent_a,
            agent_b=agent_b,
            balance_a=deposit_a,
            balance_b=deposit_b,
            total_deposited=deposit_a + deposit_b,
        )
        
        # Update balances
        self._balances[agent_a] = self._balances.get(agent_a, Decimal("0")) - deposit_a
        self._balances[agent_b] = self._balances.get(agent_b, Decimal("0")) - deposit_b
        
        # Store channel
        self._channels[channel.id] = channel
        
        if agent_a not in self._agent_channels:
            self._agent_channels[agent_a] = []
        self._agent_channels[agent_a].append(channel.id)
        
        if agent_b not in self._agent_channels:
            self._agent_channels[agent_b] = []
        self._agent_channels[agent_b].append(channel.id)
        
        self._logger.info(
            "channel_opened",
            channel_id=channel.id,
            agent_a=agent_a,
            agent_b=agent_b,
            total_deposited=channel.total_deposited,
        )
        
        return channel
    
    async def close_channel(
        self,
        channel_id: str,
        final_state: dict[str, Any] | None = None,
    ) -> dict[str, Decimal]:
        """
        Close a payment channel and settle balances.
        
        Args:
            channel_id: Channel to close
            final_state: Final signed state (optional)
            
        Returns:
            Final balances
        """
        channel = self._channels.get(channel_id)
        if not channel:
            raise ValueError(f"Channel not found: {channel_id}")
        
        # Apply final state if provided
        if final_state:
            channel.balance_a = Decimal(str(final_state.get("balance_a", channel.balance_a)))
            channel.balance_b = Decimal(str(final_state.get("balance_b", channel.balance_b)))
            channel.nonce = final_state.get("nonce", channel.nonce)
        
        # Close channel
        final_balances = channel.close()
        
        # Settle on-chain
        self._balances[channel.agent_a] = self._balances.get(channel.agent_a, Decimal("0")) + channel.balance_a
        self._balances[channel.agent_b] = self._balances.get(channel.agent_b, Decimal("0")) + channel.balance_b
        
        self._logger.info(
            "channel_closed",
            channel_id=channel_id,
            final_balance_a=channel.balance_a,
            final_balance_b=channel.balance_b,
        )
        
        return final_balances
    
    async def pay(
        self,
        sender: AgentID,
        recipient: AgentID,
        amount: Decimal,
        description: str = "",
        service_id: str = "",
    ) -> Payment:
        """
        Make a payment (on-chain).
        
        Args:
            sender: Paying agent
            recipient: Receiving agent
            amount: Amount to pay
            description: Payment description
            service_id: Associated service
            
        Returns:
            Payment record
        """
        # Check balance
        if self._balances.get(sender, Decimal("0")) < amount:
            raise ValueError(f"Insufficient balance: {sender}")
        
        # Create payment
        payment = Payment(
            sender=sender,
            recipient=recipient,
            amount=amount,
            description=description,
            service_id=service_id,
            status="completed",
        )
        
        # Update balances
        self._balances[sender] -= amount
        self._balances[recipient] = self._balances.get(recipient, Decimal("0")) + amount
        
        # Record
        self._transactions.append(payment)
        
        self._logger.info(
            "payment_completed",
            payment_id=payment.id,
            sender=sender,
            recipient=recipient,
            amount=amount,
        )
        
        return payment
    
    async def get_balance(self, agent_id: AgentID) -> Decimal:
        """Get agent's on-chain balance."""
        return self._balances.get(agent_id, Decimal("0"))
    
    async def deposit(self, agent_id: AgentID, amount: Decimal) -> bool:
        """Deposit funds to agent's account."""
        self._balances[agent_id] = self._balances.get(agent_id, Decimal("0")) + amount
        
        self._logger.info("deposit", agent_id=agent_id, amount=amount)
        return True
    
    async def withdraw(self, agent_id: AgentID, amount: Decimal) -> bool:
        """Withdraw funds from agent's account."""
        if self._balances.get(agent_id, Decimal("0")) < amount:
            return False
        
        self._balances[agent_id] -= amount
        
        self._logger.info("withdrawal", agent_id=agent_id, amount=amount)
        return True
    
    def get_channel(self, channel_id: str) -> PaymentChannel | None:
        """Get channel by ID."""
        return self._channels.get(channel_id)
    
    def get_agent_channels(self, agent_id: AgentID) -> list[PaymentChannel]:
        """Get all channels for an agent."""
        channel_ids = self._agent_channels.get(agent_id, [])
        return [self._channels[cid] for cid in channel_ids if cid in self._channels]
    
    async def get_transaction_history(
        self,
        agent_id: AgentID | None = None,
        limit: int = 100,
    ) -> list[Payment]:
        """Get transaction history."""
        transactions = self._transactions
        
        if agent_id:
            transactions = [
                t for t in transactions
                if t.sender == agent_id or t.recipient == agent_id
            ]
        
        return transactions[-limit:]
