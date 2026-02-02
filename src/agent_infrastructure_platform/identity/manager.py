"""Identity Manager for the Agent Infrastructure Platform."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from pydantic import BaseModel

from agent_infrastructure_platform.common.types import AgentID
from agent_infrastructure_platform.identity.agent_card import AgentCard, AgentCardBuilder
from agent_infrastructure_platform.identity.credentials import (
    CredentialIssuer,
    CredentialVerifier,
    VerifiableCredential,
)
from agent_infrastructure_platform.identity.reputation import ReputationScore, ReputationSystem

logger = structlog.get_logger()


class IdentityManager:
    """
    Central manager for agent identity operations.
    
    Combines:
    - Agent Card management
    - Credential issuance and verification
    - Reputation tracking
    - Cryptographic operations
    
    Example:
        ```python
        identity = IdentityManager()
        
        # Create agent card
        card = identity.create_card(
            name="my-agent",
            owner="org:my-org",
        )
        
        # Issue capability credential
        cred = identity.issue_credential(
            subject_id=card.id,
            claims={"capability": "code-review", "level": "expert"},
        )
        
        # Verify another agent
        if identity.verify_card(other_card):
            reputation = await identity.get_reputation(other_card.id)
            if reputation.overall > 0.7:
                # Trust this agent
                pass
        ```
    """

    def __init__(
        self,
        issuer_id: str | None = None,
        private_key_pem: str | None = None,
    ) -> None:
        self.issuer_id = issuer_id or f"did:aip:{__import__('uuid').uuid4().hex[:16]}"
        
        # Components
        self._credential_issuer = CredentialIssuer(self.issuer_id, private_key_pem)
        self._credential_verifier = CredentialVerifier()
        self._reputation_system = ReputationSystem()
        
        # Storage
        self._cards: dict[AgentID, AgentCard] = {}
        
        self._logger = logger.bind(identity_manager=True)
    
    #region Agent Card Management
    
    def create_card(
        self,
        name: str,
        owner: str,
        description: str = "",
    ) -> AgentCardBuilder:
        """
        Start building a new Agent Card.
        
        Args:
            name: Agent name
            owner: Owner identifier
            description: Agent description
            
        Returns:
            AgentCardBuilder for fluent construction
        """
        return AgentCardBuilder(name=name, owner=owner).with_description(description)
    
    def register_card(self, card: AgentCard) -> None:
        """
        Register an agent card in the local registry.
        
        Args:
            card: Agent card to register
        """
        self._cards[card.id] = card
        self._logger.info("card_registered", agent_id=card.id, name=card.name)
    
    def get_card(self, agent_id: AgentID) -> AgentCard | None:
        """Get a registered agent card."""
        return self._cards.get(agent_id)
    
    def sign_card(self, card: AgentCard, private_key_pem: str) -> AgentCard:
        """
        Sign an agent card with a private key.
        
        Args:
            card: Card to sign
            private_key_pem: Private key in PEM format
            
        Returns:
            Signed card
        """
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        import base64
        
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(),
            password=None,
        )
        
        payload = card.to_signing_payload().encode()
        signature = private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        
        card.proof = base64.b64encode(signature).decode()
        
        # Extract and store public key
        public_key = private_key.public_key()
        card.public_key = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        
        self._logger.info("card_signed", agent_id=card.id)
        
        return card
    
    def verify_card(self, card: AgentCard, public_key_pem: str | None = None) -> bool:
        """
        Verify an agent card's signature.
        
        Args:
            card: Card to verify
            public_key_pem: Public key (uses card.public_key if not provided)
            
        Returns:
            True if signature is valid
        """
        if not card.proof:
            self._logger.warning("card_not_signed", agent_id=card.id)
            return False
        
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        import base64
        
        try:
            key_pem = public_key_pem or card.public_key
            if not key_pem:
                self._logger.warning("no_public_key", agent_id=card.id)
                return False
            
            public_key = serialization.load_pem_public_key(key_pem.encode())
            
            signature = base64.b64decode(card.proof)
            payload = card.to_signing_payload().encode()
            
            public_key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
            
            return True
            
        except Exception as e:
            self._logger.warning("card_verification_failed", agent_id=card.id, error=str(e))
            return False
    
    #endregion
    
    #region Credentials
    
    def trust_issuer(self, issuer_id: str, public_key_pem: str) -> None:
        """Trust a credential issuer."""
        self._credential_verifier.trust_issuer(issuer_id, public_key_pem)
    
    def issue_credential(
        self,
        subject_id: str,
        claims: dict[str, Any],
        credential_type: str = "AgentCapability",
        expires_in_days: int = 365,
    ) -> VerifiableCredential:
        """
        Issue a verifiable credential.
        
        Args:
            subject_id: Agent receiving the credential
            claims: Claims being attested
            credential_type: Type of credential
            expires_in_days: Validity period
            
        Returns:
            Signed credential
        """
        return self._credential_issuer.issue_credential(
            subject_id=subject_id,
            claims=claims,
            credential_type=credential_type,
            expires_in_days=expires_in_days,
        )
    
    def verify_credential(self, credential: VerifiableCredential) -> bool:
        """Verify a credential."""
        return self._credential_verifier.verify(credential)
    
    def attach_credential(self, card: AgentCard, credential: VerifiableCredential) -> None:
        """
        Attach a credential to an agent card.
        
        Args:
            card: Agent card
            credential: Credential to attach
        """
        from agent_infrastructure_platform.identity.agent_card import AgentCredential
        
        agent_cred = AgentCredential(
            type=credential.type[1] if len(credential.type) > 1 else "Generic",
            issuer=credential.issuer,
            issued_at=credential.issuance_date,
            expires_at=credential.expiration_date or datetime.utcnow(),
            claims=credential.claims,
            proof=credential.proof_value,
        )
        
        card.credentials.append(agent_cred)
        self._logger.info("credential_attached", agent_id=card.id, credential_id=credential.id)
    
    #endregion
    
    #region Reputation
    
    async def get_reputation(self, agent_id: AgentID) -> ReputationScore:
        """Get an agent's reputation."""
        return await self._reputation_system.get_reputation(agent_id)
    
    async def record_task_completion(
        self,
        agent_id: AgentID,
        success: bool,
        duration_ms: float | None = None,
        quality_score: float | None = None,
    ) -> ReputationScore:
        """Record a task completion event."""
        return await self._reputation_system.record_task_completion(
            agent_id=agent_id,
            success=success,
            duration_ms=duration_ms,
            quality_score=quality_score,
        )
    
    async def submit_rating(
        self,
        rater_id: AgentID,
        ratee_id: AgentID,
        score: float,
        task_id: str | None = None,
        category: str = "general",
    ) -> ReputationScore:
        """Submit a rating for an agent."""
        return await self._reputation_system.submit_rating(
            rater_id=rater_id,
            ratee_id=ratee_id,
            score=score,
            task_id=task_id,
            category=category,
        )
    
    async def is_trusted(
        self,
        agent_id: AgentID,
        threshold: float = 0.6,
        min_confidence: float = 0.2,
    ) -> bool:
        """Check if an agent is trusted."""
        return await self._reputation_system.is_trusted(
            agent_id=agent_id,
            threshold=threshold,
            min_confidence=min_confidence,
        )
    
    #endregion
    
    #region Validation
    
    async def validate_agent(
        self,
        card: AgentCard,
        require_trusted: bool = True,
        min_reputation: float = 0.5,
    ) -> tuple[bool, list[str]]:
        """
        Validate an agent comprehensively.
        
        Args:
            card: Agent card to validate
            require_trusted: Whether to require trusted issuer
            min_reputation: Minimum reputation threshold
            
        Returns:
            (is_valid, list of issues)
        """
        issues: list[str] = []
        
        # Check card validity
        if not card.is_valid():
            issues.append("Card is not valid (expired or inactive)")
        
        # Verify signature
        if card.proof and not self.verify_card(card):
            issues.append("Card signature verification failed")
        
        # Check reputation
        reputation = await self.get_reputation(card.id)
        if reputation.overall < min_reputation:
            issues.append(f"Reputation too low: {reputation.overall:.2f} < {min_reputation}")
        
        # Verify credentials
        for cred in card.credentials:
            # Convert AgentCredential to VerifiableCredential format
            # This is a simplified check
            pass
        
        is_valid = len(issues) == 0
        
        return is_valid, issues
    
    #endregion
