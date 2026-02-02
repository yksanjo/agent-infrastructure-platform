"""
Example: Multi-Agent Workflow with AIP

This example demonstrates:
1. Creating agents with different capabilities
2. Registering them with the orchestrator
3. Creating a task plan
4. Executing with full observability
"""

import asyncio
from dataclasses import dataclass

from agent_infrastructure_platform import Agent, AgentCard, Orchestrator
from agent_infrastructure_platform.common.agent import AgentConfig
from agent_infrastructure_platform.common.types import (
    Capability,
    CapabilityCategory,
    Context,
    Task,
    TaskStatus,
)
from agent_infrastructure_platform.governance import AuditLogger, KillSwitch, PolicyEngine
from agent_infrastructure_platform.identity import IdentityManager
from agent_infrastructure_platform.memory import HybridMemoryStore
from agent_infrastructure_platform.protocols.a2a.protocol import A2AProtocol
from agent_infrastructure_platform.protocols.mcp.server import MCPServer


@dataclass
class ResearchResult:
    """Result from research task."""
    topic: str
    findings: list[str]
    sources: list[str]


@dataclass
class WritingResult:
    """Result from writing task."""
    title: str
    content: str
    word_count: int


class ResearchAgent(Agent):
    """Agent that researches topics."""
    
    def __init__(self) -> None:
        super().__init__(AgentConfig(name="research-agent"))
        self.register_capability(Capability(
            name="web-research",
            category=CapabilityCategory.TOOL,
        ))
        self.register_capability(Capability(
            name="data-analysis",
            category=CapabilityCategory.COGNITIVE,
        ))
    
    async def handle_task(self, task: Task, ctx: Context) -> Task:
        """Research the given topic."""
        topic = task.input_data.get("topic", "unknown")
        
        # Simulate research
        await asyncio.sleep(0.5)
        
        result = ResearchResult(
            topic=topic,
            findings=[
                f"Finding 1 about {topic}",
                f"Finding 2 about {topic}",
            ],
            sources=["source1.com", "source2.com"],
        )
        
        task.output_data = result.__dict__
        return task
    
    async def handle_message(self, message, ctx):
        return None


class WritingAgent(Agent):
    """Agent that writes content."""
    
    def __init__(self) -> None:
        super().__init__(AgentConfig(name="writing-agent"))
        self.register_capability(Capability(
            name="content-writing",
            category=CapabilityCategory.COGNITIVE,
        ))
        self.register_capability(Capability(
            name="editing",
            category=CapabilityCategory.COGNITIVE,
        ))
    
    async def handle_task(self, task: Task, ctx: Context) -> Task:
        """Write content based on research."""
        research_data = task.input_data.get("research", {})
        topic = research_data.get("topic", "unknown")
        findings = research_data.get("findings", [])
        
        # Simulate writing
        await asyncio.sleep(0.5)
        
        content = f"# {topic.title()}\n\n"
        for i, finding in enumerate(findings, 1):
            content += f"{i}. {finding}\n\n"
        
        result = WritingResult(
            title=topic.title(),
            content=content,
            word_count=len(content.split()),
        )
        
        task.output_data = result.__dict__
        return task
    
    async def handle_message(self, message, ctx):
        return None


class ReviewAgent(Agent):
    """Agent that reviews content."""
    
    def __init__(self) -> None:
        super().__init__(AgentConfig(name="review-agent"))
        self.register_capability(Capability(
            name="content-review",
            category=CapabilityCategory.COGNITIVE,
        ))
    
    async def handle_task(self, task: Task, ctx: Context) -> Task:
        """Review content and provide feedback."""
        content = task.input_data.get("content", {})
        
        # Simulate review
        await asyncio.sleep(0.3)
        
        review = {
            "approved": True,
            "score": 0.92,
            "feedback": ["Well structured", "Good sources"],
            "suggestions": ["Add more details in section 2"],
        }
        
        task.output_data = review
        return task
    
    async def handle_message(self, message, ctx):
        return None


async def main():
    """Run the multi-agent workflow example."""
    
    print("=" * 60)
    print("Agent Infrastructure Platform - Multi-Agent Workflow Demo")
    print("=" * 60)
    print()
    
    # 1. Initialize infrastructure
    print("1. Initializing infrastructure...")
    
    # Identity management
    identity = IdentityManager(issuer_id="org:demo")
    
    # Memory
    memory = HybridMemoryStore()
    
    # Governance
    audit = AuditLogger()
    policy = PolicyEngine()
    killswitch = KillSwitch()
    
    # 2. Create agents
    print("2. Creating specialized agents...")
    
    research_agent = ResearchAgent()
    writing_agent = WritingAgent()
    review_agent = ReviewAgent()
    
    # Initialize agents
    await research_agent.initialize()
    await writing_agent.initialize()
    await review_agent.initialize()
    
    print(f"   - Research Agent: {research_agent.id}")
    print(f"     Capabilities: {[c.name for c in research_agent.list_capabilities()]}")
    print(f"   - Writing Agent: {writing_agent.id}")
    print(f"     Capabilities: {[c.name for c in writing_agent.list_capabilities()]}")
    print(f"   - Review Agent: {review_agent.id}")
    print(f"     Capabilities: {[c.name for c in review_agent.list_capabilities()]}")
    print()
    
    # 3. Set up orchestrator
    print("3. Setting up orchestrator...")
    
    orchestrator = Orchestrator(max_concurrent_tasks=10)
    
    # Register agents with orchestrator
    orchestrator.register_agent(
        research_agent,
        ["web-research", "data-analysis"],
    )
    orchestrator.register_agent(
        writing_agent,
        ["content-writing", "editing"],
    )
    orchestrator.register_agent(
        review_agent,
        ["content-review"],
    )
    
    print(f"   - Registered {len(orchestrator._agents)} agents")
    print()
    
    # 4. Create task plan
    print("4. Creating task plan...")
    
    topic = "artificial intelligence in healthcare"
    
    plan = await orchestrator.create_plan(
        goal=f"Write an article about {topic}",
        required_capabilities=["web-research", "content-writing", "content-review"],
    )
    
    # Customize the plan with our specific input
    plan.name = f"Article on {topic}"
    plan.tasks[0].input_data = {"topic": topic}
    plan.dependencies[plan.tasks[1].id] = [plan.tasks[0].id]
    plan.dependencies[plan.tasks[2].id] = [plan.tasks[1].id]
    
    print(f"   - Plan: {plan.name}")
    print(f"   - Tasks: {len(plan.tasks)}")
    for i, task in enumerate(plan.tasks):
        deps = plan.dependencies.get(task.id, [])
        print(f"     {i+1}. {task.name} (deps: {deps if deps else 'none'})")
    print()
    
    # 5. Execute workflow
    print("5. Executing workflow...")
    print()
    
    results = await orchestrator.execute(plan)
    
    # 6. Display results
    print("6. Results:")
    print()
    
    for task_id, result in results.items():
        status = "✓" if result.success else "✗"
        print(f"   {status} Task {task_id[:20]}...")
        print(f"     Success: {result.success}")
        print(f"     Duration: {result.duration_ms:.2f}ms")
        
        if result.output:
            print(f"     Output: {str(result.output)[:100]}...")
        
        if result.error:
            print(f"     Error: {result.error}")
        print()
    
    # 7. Cleanup
    print("7. Cleaning up...")
    
    await research_agent.shutdown()
    await writing_agent.shutdown()
    await review_agent.shutdown()
    
    print("   - All agents shut down")
    print()
    
    # 8. Final stats
    print("=" * 60)
    print("Final Statistics")
    print("=" * 60)
    print(f"Orchestrator Status: {orchestrator.get_status()}")
    print(f"Audit Events: {audit.get_stats()}")
    print()
    print("Demo completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
