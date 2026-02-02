"""Distributed Identity & Trust Layer."""

from agent_infrastructure_platform.identity.agent_card import AgentCard, AgentCapability
from agent_infrastructure_platform.identity.credentials import (
    VerifiableCredential,
    CredentialIssuer,
    CredentialVerifier,
)
from agent_infrastructure_platform.identity.reputation import ReputationSystem, ReputationScore
from agent_infrastructure_platform.identity.manager import IdentityManager
from agent_infrastructure_platform.identity.mpc import MPCKeyManager

__all__ = [
    "AgentCard",
    "AgentCapability",
    "VerifiableCredential",
    "CredentialIssuer",
    "CredentialVerifier",
    "ReputationSystem",
    "ReputationScore",
    "IdentityManager",
    "MPCKeyManager",
]
