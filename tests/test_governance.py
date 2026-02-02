"""Tests for governance and safety."""

import pytest
import asyncio

from agent_infrastructure_platform.governance.policy import (
    PolicyEngine,
    Policy,
    PolicyAction,
    PolicyScope,
)
from agent_infrastructure_platform.governance.audit import AuditLogger, AuditEvent
from agent_infrastructure_platform.governance.killswitch import (
    KillSwitch,
    KillSwitchLevel,
    KillSwitchReason,
)


@pytest.mark.asyncio
class TestPolicyEngine:
    """Test policy enforcement."""

    async def test_policy_registration(self):
        """Test policy registration."""
        engine = PolicyEngine()
        
        policy = Policy(
            id="test-policy",
            name="Test Policy",
            scope=PolicyScope.GLOBAL,
            action=PolicyAction.DENY,
        )
        
        engine.register_policy(policy)
        assert len(engine._policies) == 1

    async def test_policy_evaluation_allow(self):
        """Test policy evaluation - allow."""
        engine = PolicyEngine()
        
        result = await engine.evaluate(
            agent_id="agent-1",
            action="test",
            context={},
        )
        
        assert result.allowed is True
        assert result.decision == PolicyAction.ALLOW

    async def test_policy_evaluation_deny(self):
        """Test policy evaluation - deny."""
        engine = PolicyEngine()
        
        # Register deny policy
        engine.register_policy(Policy(
            id="deny-all",
            name="Deny All",
            condition="true",  # Always matches
            action=PolicyAction.DENY,
        ))
        
        result = await engine.evaluate(
            agent_id="agent-1",
            action="test",
            context={},
        )
        
        assert result.allowed is False
        assert result.decision == PolicyAction.DENY

    async def test_policy_condition_evaluation(self):
        """Test policy condition evaluation."""
        engine = PolicyEngine()
        
        engine.register_policy(Policy(
            id="capability-check",
            name="Capability Check",
            condition="capability.name == 'dangerous'",
            action=PolicyAction.DENY,
        ))
        
        # Should not match
        result = await engine.evaluate(
            agent_id="agent-1",
            action="test",
            context={"capability": {"name": "safe"}},
        )
        assert result.allowed is True
        
        # Should match
        result = await engine.evaluate(
            agent_id="agent-1",
            action="test",
            context={"capability": {"name": "dangerous"}},
        )
        assert result.allowed is False


@pytest.mark.asyncio
class TestAuditLogger:
    """Test audit logging."""

    async def test_event_logging(self):
        """Test logging events."""
        audit = AuditLogger()
        
        event = await audit.log(
            action="test.action",
            resource="test://resource",
            agent_id="agent-1",
            success=True,
        )
        
        assert event.action == "test.action"
        assert event.agent_id == "agent-1"
        assert event.success is True
        assert event.event_hash is not None

    async def test_event_query(self):
        """Test querying events."""
        audit = AuditLogger()
        
        await audit.log(action="action-1", agent_id="agent-1")
        await audit.log(action="action-2", agent_id="agent-2")
        await audit.log(action="action-3", agent_id="agent-1")
        
        events = await audit.query(agent_id="agent-1")
        
        assert len(events) == 2
        assert all(e.agent_id == "agent-1" for e in events)

    async def test_chain_verification(self):
        """Test audit chain verification."""
        audit = AuditLogger()
        
        await audit.log(action="action-1")
        await audit.log(action="action-2")
        await audit.log(action="action-3")
        
        is_valid, broken_id = await audit.verify_chain()
        
        assert is_valid is True
        assert broken_id is None

    async def test_export(self):
        """Test audit export."""
        audit = AuditLogger()
        
        await audit.log(
            action="test",
            agent_id="agent-1",
            input_data={"key": "value"},
        )
        
        json_export = await audit.export(format="json")
        assert "test" in json_export
        assert "agent-1" in json_export


@pytest.mark.asyncio
class TestKillSwitch:
    """Test kill switch functionality."""

    async def test_agent_kill(self):
        """Test killing a single agent."""
        killswitch = KillSwitch()
        
        # Create a mock task
        task = asyncio.create_task(asyncio.sleep(100))
        killswitch.monitor_agent("agent-1", task)
        
        assert killswitch.is_killed("agent-1") is False
        
        # Kill the agent
        event = await killswitch.activate(
            level=KillSwitchLevel.AGENT,
            target="agent-1",
            reason=KillSwitchReason.POLICY_VIOLATION,
        )
        
        assert event.agents_terminated == 1
        assert killswitch.is_killed("agent-1") is True

    async def test_global_kill(self):
        """Test global kill switch."""
        killswitch = KillSwitch()
        
        # Monitor multiple agents
        for i in range(3):
            task = asyncio.create_task(asyncio.sleep(100))
            killswitch.monitor_agent(f"agent-{i}", task)
        
        # Global kill
        event = await killswitch.activate(
            level=KillSwitchLevel.GLOBAL,
            target="*",
            reason=KillSwitchReason.EMERGENCY_STOP,
        )
        
        assert event.agents_terminated == 3
        assert all(killswitch.is_killed(f"agent-{i}") for i in range(3))

    async def test_kill_and_deactivate(self):
        """Test kill and deactivate."""
        killswitch = KillSwitch()
        
        task = asyncio.create_task(asyncio.sleep(100))
        killswitch.monitor_agent("agent-1", task)
        
        # Kill
        await killswitch.activate(
            level=KillSwitchLevel.AGENT,
            target="agent-1",
            reason=KillSwitchReason.MANUAL_OVERRIDE,
        )
        
        assert killswitch.is_killed("agent-1") is True
        
        # Deactivate
        success = await killswitch.deactivate(
            level=KillSwitchLevel.AGENT,
            target="agent-1",
        )
        
        assert success is True
        assert killswitch.is_killed("agent-1") is False

    async def test_check_or_raise(self):
        """Test check_or_raise method."""
        from agent_infrastructure_platform.common.exceptions import KillSwitchActivated
        
        killswitch = KillSwitch()
        
        # Should not raise
        killswitch.check_or_raise("agent-1")
        
        # Kill and check
        task = asyncio.create_task(asyncio.sleep(100))
        killswitch.monitor_agent("agent-1", task)
        
        await killswitch.activate(
            level=KillSwitchLevel.AGENT,
            target="agent-1",
            reason=KillSwitchReason.POLICY_VIOLATION,
        )
        
        # Should raise
        with pytest.raises(KillSwitchActivated):
            killswitch.check_or_raise("agent-1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
