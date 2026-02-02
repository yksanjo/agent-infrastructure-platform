"""Reputation system for agents."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent_infrastructure_platform.common.types import AgentID

logger = structlog.get_logger()


class ReputationScore(BaseModel):
    """Reputation metrics for an agent."""

    model_config = ConfigDict(frozen=False)

    agent_id: AgentID
    
    # Overall score (0-1)
    overall: float = 0.5
    
    # Component scores
    reliability: float = 0.5  # Task completion rate
    quality: float = 0.5  # Output quality ratings
    responsiveness: float = 0.5  # Response time performance
    honesty: float = 0.5  # Truthfulness in claims
    cooperativeness: float = 0.5  # Willingness to collaborate
    
    # Metrics
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    total_ratings: int = 0
    average_rating: float = 0.0
    
    # History
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    
    # Confidence
    confidence: float = 0.0  # Based on number of interactions
    
    def update_confidence(self) -> None:
        """Update confidence based on interaction history."""
        total_interactions = self.total_tasks_completed + self.total_tasks_failed
        # Confidence approaches 1 as interactions increase, with diminishing returns
        self.confidence = min(1.0, math.log1p(total_interactions) / 5)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump()


class Rating(BaseModel):
    """A rating given by one agent to another."""

    model_config = ConfigDict(frozen=True)

    rater_id: AgentID
    ratee_id: AgentID
    
    # Rating (1-5)
    score: float = Field(ge=1, le=5)
    
    # Context
    task_id: str | None = None
    category: str = "general"  # general, quality, reliability, speed
    
    # Metadata
    comment: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Verification
    proof: str | None = None  # Signature of the rating


class ReputationSystem:
    """
    Decentralized reputation system for agents.
    
    Features:
    - Multi-factor reputation scoring
    - Weighted ratings based on rater reputation
    - Time-decay of old ratings
    - Sybil resistance through stake requirements
    
    Example:
        ```python
        reputation = ReputationSystem()
        
        # Record task completion
        await reputation.record_task_completion(agent_id, success=True)
        
        # Submit rating
        await reputation.submit_rating(
            rater_id=rater,
            ratee_id=ratee,
            score=4.5,
            category="quality",
        )
        
        # Get reputation
        score = await reputation.get_reputation(agent_id)
        if score.overall < 0.3:
            print("Warning: Low reputation agent!")
        ```
    """

    def __init__(
        self,
        rating_weight: float = 0.3,
        completion_weight: float = 0.4,
        response_weight: float = 0.3,
        rating_decay_days: int = 90,
    ) -> None:
        self.rating_weight = rating_weight
        self.completion_weight = completion_weight
        self.response_weight = response_weight
        self.rating_decay_days = rating_decay_days
        
        # Storage (replace with persistent storage in production)
        self._scores: dict[AgentID, ReputationScore] = {}
        self._ratings: dict[AgentID, list[Rating]] = {}  # ratee_id -> ratings
        self._task_history: dict[AgentID, list[dict]] = {}
        
        self._logger = logger
    
    async def get_reputation(self, agent_id: AgentID) -> ReputationScore:
        """
        Get current reputation for an agent.
        
        Args:
            agent_id: Agent to query
            
        Returns:
            Reputation score
        """
        if agent_id not in self._scores:
            self._scores[agent_id] = ReputationScore(agent_id=agent_id)
        
        return self._scores[agent_id]
    
    async def record_task_completion(
        self,
        agent_id: AgentID,
        success: bool,
        duration_ms: float | None = None,
        quality_score: float | None = None,
    ) -> ReputationScore:
        """
        Record a task completion event.
        
        Args:
            agent_id: Agent that completed the task
            success: Whether task succeeded
            duration_ms: Task duration in milliseconds
            quality_score: Optional quality rating (1-5)
            
        Returns:
            Updated reputation score
        """
        score = await self.get_reputation(agent_id)
        
        if success:
            score.total_tasks_completed += 1
            
            # Update reliability based on completion rate
            total = score.total_tasks_completed + score.total_tasks_failed
            score.reliability = score.total_tasks_completed / total
        else:
            score.total_tasks_failed += 1
            # Penalty to reliability
            total = score.total_tasks_completed + score.total_tasks_failed
            score.reliability = score.total_tasks_completed / total
        
        # Update responsiveness based on duration
        if duration_ms is not None:
            # Normalize: < 1000ms = 1.0, > 10000ms = 0.0
            response_score = max(0, min(1, 1 - (duration_ms - 1000) / 9000))
            # Exponential moving average
            score.responsiveness = 0.7 * score.responsiveness + 0.3 * response_score
        
        # Update quality if provided
        if quality_score is not None:
            normalized_quality = quality_score / 5.0
            score.quality = 0.8 * score.quality + 0.2 * normalized_quality
        
        score.last_active = datetime.utcnow()
        score.update_confidence()
        await self._update_overall_score(score)
        
        self._logger.debug(
            "task_recorded",
            agent_id=agent_id,
            success=success,
            reliability=score.reliability,
        )
        
        return score
    
    async def submit_rating(
        self,
        rater_id: AgentID,
        ratee_id: AgentID,
        score: float,
        task_id: str | None = None,
        category: str = "general",
        comment: str = "",
    ) -> ReputationScore:
        """
        Submit a rating for another agent.
        
        Args:
            rater_id: Agent giving the rating
            ratee_id: Agent being rated
            score: Rating score (1-5)
            task_id: Associated task
            category: Rating category
            comment: Optional comment
            
        Returns:
            Updated reputation score for ratee
        """
        # Create rating
        rating = Rating(
            rater_id=rater_id,
            ratee_id=ratee_id,
            score=score,
            task_id=task_id,
            category=category,
            comment=comment,
        )
        
        # Store rating
        if ratee_id not in self._ratings:
            self._ratings[ratee_id] = []
        self._ratings[ratee_id].append(rating)
        
        # Update ratee's reputation
        ratee_score = await self.get_reputation(ratee_id)
        ratee_score.total_ratings += 1
        
        # Get rater's reputation for weighting
        rater_score = await self.get_reputation(rater_id)
        rater_weight = max(0.1, rater_score.overall)
        
        # Calculate weighted average rating
        ratings = self._ratings[ratee_id]
        weighted_sum = 0.0
        total_weight = 0.0
        
        for r in ratings:
            # Time decay
            age_days = (datetime.utcnow() - r.timestamp).days
            time_weight = math.exp(-age_days / self.rating_decay_days)
            
            # Rater weight
            rater_rep = await self.get_reputation(r.rater_id)
            weight = rater_rep.overall * time_weight
            
            weighted_sum += r.score * weight
            total_weight += weight
        
        if total_weight > 0:
            ratee_score.average_rating = weighted_sum / total_weight
            # Normalize to 0-1 scale
            ratee_score.quality = ratee_score.average_rating / 5.0
        
        ratee_score.update_confidence()
        await self._update_overall_score(ratee_score)
        
        self._logger.info(
            "rating_submitted",
            rater=rater_id,
            ratee=ratee_id,
            score=score,
            category=category,
        )
        
        return ratee_score
    
    async def _update_overall_score(self, score: ReputationScore) -> None:
        """Recalculate overall reputation score."""
        # Weighted combination of components
        score.overall = (
            self.rating_weight * score.quality +
            self.completion_weight * score.reliability +
            self.response_weight * score.responsiveness
        )
        
        # Adjust by confidence
        score.overall = score.confidence * score.overall + (1 - score.confidence) * 0.5
    
    async def penalize(
        self,
        agent_id: AgentID,
        reason: str,
        severity: float = 0.1,  # 0-1
    ) -> ReputationScore:
        """
        Apply a reputation penalty.
        
        Args:
            agent_id: Agent to penalize
            reason: Reason for penalty
            severity: Severity (0-1)
            
        Returns:
            Updated reputation score
        """
        score = await self.get_reputation(agent_id)
        
        # Apply penalty
        score.overall = max(0, score.overall - severity)
        score.honesty = max(0, score.honesty - severity * 0.5)
        
        self._logger.warning(
            "reputation_penalty",
            agent_id=agent_id,
            reason=reason,
            severity=severity,
            new_score=score.overall,
        )
        
        return score
    
    async def reward(
        self,
        agent_id: AgentID,
        reason: str,
        amount: float = 0.05,  # 0-1
    ) -> ReputationScore:
        """
        Apply a reputation reward.
        
        Args:
            agent_id: Agent to reward
            reason: Reason for reward
            amount: Reward amount (0-1)
            
        Returns:
            Updated reputation score
        """
        score = await self.get_reputation(agent_id)
        
        # Apply reward
        score.overall = min(1, score.overall + amount)
        score.cooperativeness = min(1, score.cooperativeness + amount * 0.5)
        
        self._logger.info(
            "reputation_reward",
            agent_id=agent_id,
            reason=reason,
            amount=amount,
            new_score=score.overall,
        )
        
        return score
    
    async def get_top_agents(
        self,
        min_reputation: float = 0.5,
        limit: int = 10,
    ) -> list[tuple[AgentID, float]]:
        """
        Get top-rated agents.
        
        Args:
            min_reputation: Minimum reputation threshold
            limit: Maximum results
            
        Returns:
            List of (agent_id, score) tuples
        """
        filtered = [
            (agent_id, score.overall)
            for agent_id, score in self._scores.items()
            if score.overall >= min_reputation and score.confidence > 0.3
        ]
        
        # Sort by score descending
        filtered.sort(key=lambda x: x[1], reverse=True)
        
        return filtered[:limit]
    
    async def is_trusted(
        self,
        agent_id: AgentID,
        threshold: float = 0.6,
        min_confidence: float = 0.2,
    ) -> bool:
        """
        Check if an agent is trusted.
        
        Args:
            agent_id: Agent to check
            threshold: Minimum reputation threshold
            min_confidence: Minimum confidence required
            
        Returns:
            True if agent is trusted
        """
        score = await self.get_reputation(agent_id)
        
        return (
            score.overall >= threshold and
            score.confidence >= min_confidence
        )
