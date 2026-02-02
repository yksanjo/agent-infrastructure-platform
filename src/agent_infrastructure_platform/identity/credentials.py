"""Verifiable Credentials for agent identity and capabilities."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import BaseModel, ConfigDict, Field

logger = structlog.get_logger()


class VerifiableCredential(BaseModel):
    """
    W3C Verifiable Credential for agents.
    
    Credentials can attest to:
    - Identity (this agent is who they claim to be)
    - Capabilities (this agent can do X)
    - Reputation (this agent has good standing)
    - Authorization (this agent is allowed to do Y)
    """

    model_config = ConfigDict(frozen=True)

    # Metadata
    id: str = Field(default_factory=lambda: f"urn:uuid:{__import__('uuid').uuid4()}")
    type: list[str] = Field(default_factory=lambda: ["VerifiableCredential"])
    
    # Issuer
    issuer: str  # DID or identifier
    issuance_date: datetime = Field(default_factory=datetime.utcnow)
    expiration_date: datetime | None = None
    
    # Subject (the agent being credentialed)
    subject_id: str  # Agent ID
    claims: dict[str, Any] = Field(default_factory=dict)
    
    # Proof
    proof_type: str = "Ed25519Signature2020"
    proof_value: str | None = None
    proof_purpose: str = "assertionMethod"
    verification_method: str | None = None
    
    def is_expired(self) -> bool:
        """Check if credential is expired."""
        if self.expiration_date:
            return datetime.utcnow() > self.expiration_date
        return False
    
    def to_signing_payload(self) -> str:
        """Get payload for signing/verification."""
        # Exclude proof from signing payload
        data = {
            "id": self.id,
            "type": self.type,
            "issuer": self.issuer,
            "issuanceDate": self.issuance_date.isoformat(),
            "expirationDate": self.expiration_date.isoformat() if self.expiration_date else None,
            "credentialSubject": {
                "id": self.subject_id,
                **self.claims,
            },
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


class CredentialIssuer:
    """Issues verifiable credentials for agents."""
    
    def __init__(self, issuer_id: str, private_key_pem: str | None = None) -> None:
        self.issuer_id = issuer_id
        self._logger = logger.bind(issuer=issuer_id)
        
        # Generate or load key pair
        if private_key_pem:
            self._private_key = serialization.load_pem_private_key(
                private_key_pem.encode(),
                password=None,
            )
        else:
            self._private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
        
        self._public_key = self._private_key.public_key()
    
    def get_public_key_pem(self) -> str:
        """Get public key in PEM format."""
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
    
    def issue_credential(
        self,
        subject_id: str,
        claims: dict[str, Any],
        credential_type: str = "AgentCapability",
        expires_in_days: int = 365,
    ) -> VerifiableCredential:
        """
        Issue a new credential.
        
        Args:
            subject_id: Agent receiving the credential
            claims: Claims being attested
            credential_type: Type of credential
            expires_in_days: Validity period
            
        Returns:
            Signed credential
        """
        credential = VerifiableCredential(
            type=["VerifiableCredential", credential_type],
            issuer=self.issuer_id,
            expiration_date=datetime.utcnow() + timedelta(days=expires_in_days),
            subject_id=subject_id,
            claims=claims,
            verification_method=f"{self.issuer_id}#keys-1",
        )
        
        # Sign the credential
        payload = credential.to_signing_payload().encode()
        signature = self._private_key.sign(
            payload,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        
        # Store signature as base64
        import base64
        credential = credential.model_copy(
            update={"proof_value": base64.b64encode(signature).decode()},
        )
        
        self._logger.info(
            "credential_issued",
            credential_id=credential.id,
            subject=subject_id,
            type=credential_type,
        )
        
        return credential
    
    def revoke_credential(self, credential_id: str) -> bool:
        """
        Revoke a previously issued credential.
        
        In a production system, this would add to a revocation list
        or use a revocation registry.
        """
        self._logger.info("credential_revoked", credential_id=credential_id)
        # Implementation would update revocation list
        return True


class CredentialVerifier:
    """Verifies credentials presented by agents."""
    
    def __init__(self) -> None:
        self._trusted_issuers: dict[str, bytes] = {}  # issuer_id -> public_key_pem
        self._revoked_credentials: set[str] = set()
        self._logger = logger
    
    def trust_issuer(self, issuer_id: str, public_key_pem: str) -> None:
        """Add a trusted issuer."""
        self._trusted_issuers[issuer_id] = public_key_pem.encode()
        self._logger.info("issuer_trusted", issuer_id=issuer_id)
    
    def untrust_issuer(self, issuer_id: str) -> None:
        """Remove a trusted issuer."""
        if issuer_id in self._trusted_issuers:
            del self._trusted_issuers[issuer_id]
            self._logger.info("issuer_untrusted", issuer_id=issuer_id)
    
    def revoke_credential(self, credential_id: str) -> None:
        """Mark a credential as revoked."""
        self._revoked_credentials.add(credential_id)
        self._logger.info("credential_marked_revoked", credential_id=credential_id)
    
    def verify(self, credential: VerifiableCredential) -> bool:
        """
        Verify a credential.
        
        Checks:
        1. Not expired
        2. Not revoked
        3. Issuer is trusted
        4. Signature is valid
        
        Returns:
            True if credential is valid
        """
        # Check expiration
        if credential.is_expired():
            self._logger.warning("credential_expired", credential_id=credential.id)
            return False
        
        # Check revocation
        if credential.id in self._revoked_credentials:
            self._logger.warning("credential_revoked", credential_id=credential.id)
            return False
        
        # Check issuer trust
        if credential.issuer not in self._trusted_issuers:
            self._logger.warning("issuer_not_trusted", issuer=credential.issuer)
            return False
        
        # Verify signature
        try:
            public_key_pem = self._trusted_issuers[credential.issuer]
            public_key = serialization.load_pem_public_key(public_key_pem)
            
            import base64
            signature = base64.b64decode(credential.proof_value)
            payload = credential.to_signing_payload().encode()
            
            public_key.verify(
                signature,
                payload,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            
            return True
            
        except Exception as e:
            self._logger.error("signature_verification_failed", error=str(e))
            return False
    
    def verify_claim(
        self,
        credential: VerifiableCredential,
        claim_path: str,
        expected_value: Any | None = None,
    ) -> bool:
        """
        Verify a specific claim in a credential.
        
        Args:
            credential: Credential to check
            claim_path: Dot-separated path to claim (e.g., "capabilities.text-generation")
            expected_value: Expected value (optional)
            
        Returns:
            True if claim exists and matches expected value
        """
        if not self.verify(credential):
            return False
        
        # Navigate to claim
        value = credential.claims
        for key in claim_path.split("."):
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return False
        
        if expected_value is not None:
            return value == expected_value
        
        return True
