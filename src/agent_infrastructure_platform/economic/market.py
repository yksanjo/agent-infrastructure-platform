"""Resource market for agent-to-agent resource trading."""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from agent_infrastructure_platform.common.types import AgentID, Task

logger = structlog.get_logger()


@dataclass
class Bid:
    """Bid for a resource or task."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    agent_id: AgentID = ""
    
    # What is being bid on
    resource_type: str = ""  # compute, storage, bandwidth, capability
    resource_id: str = ""  # Specific resource identifier
    
    # Bid details
    price: Decimal = Decimal("0")  # Price per unit
    quantity: int = 1
    duration: float = 3600.0  # Duration in seconds
    
    # Requirements
    min_reputation: float = 0.0
    required_capabilities: list[str] = field(default_factory=list)
    
    # Timing
    timestamp: float = field(default_factory=time.time)
    expires_at: float | None = None
    
    # Status
    status: str = "active"  # active, matched, cancelled, expired


@dataclass
class Ask:
    """Ask (offer) for a resource or task."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    agent_id: AgentID = ""
    
    # What is being offered
    resource_type: str = ""
    resource_id: str = ""
    
    # Ask details
    price: Decimal = Decimal("0")  # Minimum price per unit
    quantity: int = 1
    duration: float = 3600.0
    
    # Capabilities provided
    capabilities: list[str] = field(default_factory=list)
    reputation_score: float = 0.0
    
    # Timing
    timestamp: float = field(default_factory=time.time)
    expires_at: float | None = None
    
    # Status
    status: str = "active"


@dataclass
class Trade:
    """Completed trade."""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    bid_id: str = ""
    ask_id: str = ""
    
    buyer: AgentID = ""
    seller: AgentID = ""
    
    resource_type: str = ""
    quantity: int = 0
    price: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    
    timestamp: float = field(default_factory=time.time)


class ResourceMarket:
    """
    Market-based resource allocation between agents.
    
    Features:
    - Continuous double auction
    - Reputation-weighted matching
    - Automatic price discovery
    - Multi-resource trading
    
    Example:
        ```python
        market = ResourceMarket()
        
        # Agent offers compute
        ask = await market.ask(
            agent_id="agent-1",
            resource_type="compute",
            price=Decimal("0.01"),  # per second
            quantity=10,  # 10 cores
            capabilities=["gpu", "cuda"],
        )
        
        # Another agent bids for compute
        bid = await market.bid(
            agent_id="agent-2",
            resource_type="compute",
            price=Decimal("0.015"),
            quantity=4,
            required_capabilities=["gpu"],
        )
        
        # Market matches orders
        trades = await market.match_orders()
        ```
    """

    def __init__(
        self,
        matching_interval: float = 5.0,
        min_price_increment: Decimal = Decimal("0.001"),
    ) -> None:
        self.matching_interval = matching_interval
        self.min_price_increment = min_price_increment
        
        # Order books
        self._bids: dict[str, Bid] = {}
        self._asks: dict[str, Ask] = {}
        
        # Indexed by resource type
        self._bids_by_resource: dict[str, list[str]] = {}
        self._asks_by_resource: dict[str, list[str]] = {}
        
        # Trade history
        self._trades: list[Trade] = []
        
        # Price history
        self._price_history: dict[str, list[tuple[float, Decimal]]] = {}
        
        self._logger = logger
    
    async def bid(
        self,
        agent_id: AgentID,
        resource_type: str,
        price: Decimal,
        quantity: int = 1,
        duration: float = 3600.0,
        min_reputation: float = 0.0,
        required_capabilities: list[str] | None = None,
        expires_in: float = 300.0,
    ) -> Bid:
        """
        Place a bid for resources.
        
        Args:
            agent_id: Bidding agent
            resource_type: Type of resource
            price: Maximum price per unit
            quantity: Quantity needed
            duration: Duration needed
            min_reputation: Minimum seller reputation
            required_capabilities: Required capabilities
            expires_in: Bid expiration time
            
        Returns:
            Bid object
        """
        bid = Bid(
            agent_id=agent_id,
            resource_type=resource_type,
            price=price,
            quantity=quantity,
            duration=duration,
            min_reputation=min_reputation,
            required_capabilities=required_capabilities or [],
            expires_at=time.time() + expires_in,
        )
        
        self._bids[bid.id] = bid
        
        if resource_type not in self._bids_by_resource:
            self._bids_by_resource[resource_type] = []
        self._bids_by_resource[resource_type].append(bid.id)
        
        self._logger.info(
            "bid_placed",
            bid_id=bid.id,
            agent_id=agent_id,
            resource_type=resource_type,
            price=price,
            quantity=quantity,
        )
        
        return bid
    
    async def ask(
        self,
        agent_id: AgentID,
        resource_type: str,
        price: Decimal,
        quantity: int = 1,
        duration: float = 3600.0,
        capabilities: list[str] | None = None,
        reputation_score: float = 0.0,
        expires_in: float = 300.0,
    ) -> Ask:
        """
        Place an ask (offer) for resources.
        
        Args:
            agent_id: Offering agent
            resource_type: Type of resource
            price: Minimum price per unit
            quantity: Quantity available
            duration: Duration available
            capabilities: Capabilities provided
            reputation_score: Agent's reputation score
            expires_in: Ask expiration time
            
        Returns:
            Ask object
        """
        ask = Ask(
            agent_id=agent_id,
            resource_type=resource_type,
            price=price,
            quantity=quantity,
            duration=duration,
            capabilities=capabilities or [],
            reputation_score=reputation_score,
            expires_at=time.time() + expires_in,
        )
        
        self._asks[ask.id] = ask
        
        if resource_type not in self._asks_by_resource:
            self._asks_by_resource[resource_type] = []
        self._asks_by_resource[resource_type].append(ask.id)
        
        self._logger.info(
            "ask_placed",
            ask_id=ask.id,
            agent_id=agent_id,
            resource_type=resource_type,
            price=price,
            quantity=quantity,
        )
        
        return ask
    
    async def cancel_bid(self, bid_id: str) -> bool:
        """Cancel a bid."""
        bid = self._bids.get(bid_id)
        if bid and bid.status == "active":
            bid.status = "cancelled"
            return True
        return False
    
    async def cancel_ask(self, ask_id: str) -> bool:
        """Cancel an ask."""
        ask = self._asks.get(ask_id)
        if ask and ask.status == "active":
            ask.status = "cancelled"
            return True
        return False
    
    async def match_orders(self) -> list[Trade]:
        """
        Match bids and asks.
        
        Returns:
            List of completed trades
        """
        trades = []
        
        for resource_type in set(self._bids_by_resource.keys()) | set(self._asks_by_resource.keys()):
            resource_trades = await self._match_resource(resource_type)
            trades.extend(resource_trades)
        
        return trades
    
    async def _match_resource(self, resource_type: str) -> list[Trade]:
        """Match orders for a specific resource."""
        trades = []
        
        # Get active bids and asks
        bids = [
            self._bids[bid_id] for bid_id in self._bids_by_resource.get(resource_type, [])
            if self._bids[bid_id].status == "active" and not self._is_expired(self._bids[bid_id])
        ]
        
        asks = [
            self._asks[ask_id] for ask_id in self._asks_by_resource.get(resource_type, [])
            if self._asks[ask_id].status == "active" and not self._is_expired(self._asks[ask_id])
        ]
        
        if not bids or not asks:
            return trades
        
        # Sort bids by price (descending) and asks by price (ascending)
        bids.sort(key=lambda b: b.price, reverse=True)
        asks.sort(key=lambda a: a.price)
        
        # Match orders
        for bid in bids:
            for ask in list(asks):  # Copy to modify during iteration
                if bid.status != "active" or ask.status != "active":
                    continue
                
                # Check if prices match
                if bid.price < ask.price:
                    continue
                
                # Check reputation requirement
                if ask.reputation_score < bid.min_reputation:
                    continue
                
                # Check capability requirements
                if not all(cap in ask.capabilities for cap in bid.required_capabilities):
                    continue
                
                # Calculate trade quantity
                trade_quantity = min(bid.quantity, ask.quantity)
                
                # Use bid price (buyer pays what they offered)
                trade_price = bid.price
                total = trade_price * trade_quantity
                
                # Create trade
                trade = Trade(
                    bid_id=bid.id,
                    ask_id=ask.id,
                    buyer=bid.agent_id,
                    seller=ask.agent_id,
                    resource_type=resource_type,
                    quantity=trade_quantity,
                    price=trade_price,
                    total=total,
                )
                
                trades.append(trade)
                self._trades.append(trade)
                
                # Update orders
                bid.quantity -= trade_quantity
                ask.quantity -= trade_quantity
                
                if bid.quantity == 0:
                    bid.status = "matched"
                
                if ask.quantity == 0:
                    ask.status = "matched"
                    asks.remove(ask)
                
                self._logger.info(
                    "trade_executed",
                    trade_id=trade.id,
                    buyer=bid.agent_id,
                    seller=ask.agent_id,
                    resource_type=resource_type,
                    quantity=trade_quantity,
                    price=trade_price,
                )
        
        # Update price history
        if trades:
            avg_price = sum(t.price for t in trades) / len(trades)
            if resource_type not in self._price_history:
                self._price_history[resource_type] = []
            self._price_history[resource_type].append((time.time(), avg_price))
        
        return trades
    
    def _is_expired(self, order: Bid | Ask) -> bool:
        """Check if an order is expired."""
        if order.expires_at is None:
            return False
        return time.time() > order.expires_at
    
    async def get_price(self, resource_type: str) -> Decimal | None:
        """Get current market price for a resource."""
        history = self._price_history.get(resource_type, [])
        if history:
            return history[-1][1]
        return None
    
    async def get_order_book(
        self,
        resource_type: str,
    ) -> tuple[list[Bid], list[Ask]]:
        """Get current order book for a resource."""
        bids = [
            self._bids[bid_id] for bid_id in self._bids_by_resource.get(resource_type, [])
            if self._bids[bid_id].status == "active"
        ]
        asks = [
            self._asks[ask_id] for ask_id in self._asks_by_resource.get(resource_type, [])
            if self._asks[ask_id].status == "active"
        ]
        
        return bids, asks
    
    async def get_trade_history(
        self,
        resource_type: str | None = None,
        limit: int = 100,
    ) -> list[Trade]:
        """Get trade history."""
        trades = self._trades
        
        if resource_type:
            trades = [t for t in trades if t.resource_type == resource_type]
        
        return trades[-limit:]
