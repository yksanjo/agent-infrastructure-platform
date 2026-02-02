"""Tests for identity and trust layer."""

import pytest
import asyncio

from agent_infrastructure_platform.identity.agent_card import (
    AgentCard,
    AgentCardBuilder,
    AgentCapability,
    AgentEndpoint,
)
from agent_infrastructure_platform.identity.credentials import (
    CredentialIssuer,
    CredentialVerifier,
    VerifiableCredential,
)
from agent_infrastructure_platform.identity.reputation import (
    ReputationSystem,
    ReputationScore,
)
from agent_infrastructure_platform.common.types import Capability, CapabilityCategory


class TestAgentCard:
    """Test Agent Card functionality."""

    def test_card_builder(self):
        """Test agent card builder."""
        card = (
            AgentCardBuilder(name="test-agent", owner="org:test")
            .with_description("A test agent")
            .with_tag("test")
            .with_capability("search", CapabilityCategory.TOOL)
            .build()
        )
        
        assert card.name == "test-agent"
        assert card.owner == "org:test"
        assert "search" in [c.capability.name for c in card.capabilities]

    def test_capability_check(self):
        """Test capability checking."""
        card = AgentCardBuilder("test", "org:test").with_capability(
            "analyze", CapabilityCategory.COGNITIVE
        ).build()
        
        assert card.has_capability("analyze") is True
        assert card.has_capability("unknown") is False

    def test_card_validity(self):
        """Test card validity checking."""
        from datetime import datetime, timedelta
        
        # Valid card
        card = AgentCardBuilder("test", "org:test").build()
        assert card.is_valid() is True
        
        # Expired card
        card.expires_at = datetime.utcnow() - timedelta(days=1)
        assert card.is_valid() is False


class TestCredentials:
    """Test credential system."""

    def test_credential_issuance(self):
        """Test issuing credentials."""
        issuer = CredentialIssuer(issuer_id="did:test:issuer")
        
        credential = issuer.issue_credential(
            subject_id="agent-1",
            claims={"role": "validator"},
            credential_type="AgentRole",
        )
        
        assert credential.issuer == "did:test:issuer"
        assert credential.subject_id == "agent-1"
        assert "AgentRole" in credential.type
        assert credential.proof_value is not None

    def test_credential_verification(self):
        """Test verifying credentials."""
        issuer = CredentialIssuer(issuer_id="did:test:issuer")
        verifier = CredentialVerifier()
        
        # Trust the issuer
        verifier.trust_issuer("did:test:issuer", issuer.get_public_key_pem())
        
        # Issue and verify
        credential = issuer.issue_credential(
            subject_id="agent-1",
            claims={"role": "validator"},
        )
        
        assert verifier.verify(credential) is True

    def test_expired_credential(self):
        """Test expired credential rejection."""
        issuer = CredentialIssuer(issuer_id="did:test:issuer")
        
        credential = issuer.issue_credential(
            subject_id="agent-1",
            claims={},
            expires_in_days=-1,  # Already expired
        )
        
        assert credential.is_expired() is True


@pytest.mark.asyncio
class TestReputation:
    """Test reputation system."""

    async def test_reputation_initialization(self):
        """Test reputation initialization."""
        rep = ReputationSystem()
        
        score = await rep.get_reputation("agent-1")
        assert score.overall == 0.5  # Default
        assert score.agent_id == "agent-1"

    async def test_task_completion(self):
        """Test recording task completion."""
        rep = ReputationSystem()
        
        # Successful task
        score = await rep.record_task_completion("agent-1", success=True)
        assert score.total_tasks_completed == 1
        assert score.reliability > 0.5
        
        # Failed task
        score = await rep.record_task_completion("agent-1", success=False)
        assert score.total_tasks_failed == 1
        assert score.reliability < 1.0

    async def test_rating_submission(self):
        """Test rating submission."""
        rep = ReputationSystem()
        
        score = await rep.submit_rating(
            rater_id="agent-1",
            ratee_id="agent-2",
            score=5.0,
        )
        
        assert score.total_ratings == 1
        assert score.average_rating > 0

    async def test_penalty_and_reward(self):
        """Test penalties and rewards."""
        rep = ReputationSystem()
        
        # Initial score
        score = await rep.get_reputation("agent-1")
        initial = score.overall
        
        # Apply penalty
        score = await rep.penalize("agent-1", "bad behavior", severity=0.1)
        assert score.overall < initial
        
        # Apply reward
        score = await rep.reward("agent-1", "good behavior", amount=0.05)
        assert score.overall > score.overall - 0.05

    async def test_trust_check(self):
        """Test trust checking."""
        rep = ReputationSystem()
        
        # Low reputation agent
        is_trusted = await rep.is_trusted("agent-1", threshold=0.8)
        assert is_trusted is False
        
        # Build reputation
        for _ in range(10):
            await rep.record_task_completion("agent-1", success=True)
        
        is_trusted = await rep.is_trusted("agent-1", threshold=0.6)
        assert is_trusted is True


class TestMPC:
    """Test MPC key management."""

    @pytest.mark.asyncio
    async def test_key_generation(self):
        """Test key generation."""
        from agent_infrastructure_platform.identity.mpc import MPCKeyManager
        
        mpc = MPCKeyManager(threshold=3, num_shares=5)
        
        key_id, shares = await mpc.generate_key("agent-1")
        
        assert key_id.startswith("mpc-key-")
        assert len(shares) == 5
        assert all(s.threshold_index > 0 for s in shares)

    @pytest.mark.asyncio
    async def test_signing_with_shares(self):
        """Test signing with key shares."""
        from agent_infrastructure_platform.identity.mpc import MPCKeyManager
        
        mpc = MPCKeyManager(threshold=3, num_shares=5)
        
        key_id, shares = await mpc.generate_key("agent-1")
        
        # Sign with threshold number of shares
        message = b"test message"
        signature = await mpc.sign_with_shares(key_id, shares[:3], message)
        
        assert signature is not None
        assert len(signature) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
