"""
Example: Secure Agent Execution with TEE and Sandboxing

Demonstrates:
1. Sandbox execution for untrusted code
2. TEE execution for sensitive operations
3. Containerized execution
"""

import asyncio

from agent_infrastructure_platform.compute.runtime import AgentRuntime, ContainerConfig
from agent_infrastructure_platform.compute.sandbox import Sandbox, SandboxConfig
from agent_infrastructure_platform.compute.tee import TEERuntime, TEEConfig


async def sandbox_example():
    """Demonstrate sandboxed execution."""
    print("=" * 60)
    print("Sandbox Example")
    print("=" * 60)
    
    # Create sandbox with restrictions
    sandbox = Sandbox(SandboxConfig(
        max_execution_time=5.0,
        max_memory_mb=128,
        allowed_modules=["json", "math"],
        allow_network=False,
    ))
    
    # Safe code
    safe_code = """
import json
import math

data = {"x": 3, "y": 4}
result = math.sqrt(data["x"] ** 2 + data["y"] ** 2)
output = {"input": data, "result": result}
"""
    
    print("\n1. Executing safe code...")
    result = sandbox.execute(safe_code)
    print(f"   Success: {result.success}")
    print(f"   Output: {result.result}")
    print(f"   Duration: {result.execution_time_ms:.2f}ms")
    
    # Code with security violation
    bad_code = """
import os
result = os.system("ls")
"""
    
    print("\n2. Executing code with security violation...")
    result = sandbox.execute(bad_code)
    print(f"   Success: {result.success}")
    print(f"   Error: {result.error}")
    print(f"   Security violations: {result.security_violations}")
    
    # Code that times out
    slow_code = """
import time
time.sleep(10)
result = "done"
"""
    
    print("\n3. Executing code that times out...")
    result = sandbox.execute(slow_code)
    print(f"   Success: {result.success}")
    print(f"   Error: {result.error}")
    print()


async def tee_example():
    """Demonstrate TEE execution."""
    print("=" * 60)
    print("TEE Example")
    print("=" * 60)
    
    # Initialize TEE
    tee = TEERuntime(TEEConfig(tee_type="sgx", attestation_required=True))
    
    print("\n1. Initializing TEE...")
    success = await tee.initialize()
    print(f"   Initialized: {success}")
    
    if success:
        # Execute sensitive code
        sensitive_code = """
# Process sensitive data
input_data = input_data or {}
pii = input_data.get("pii", {})

# Hash the sensitive data
import hashlib
hashed = hashlib.sha256(str(pii).encode()).hexdigest()

output = {
    "hashed_pii": hashed,
    "processed": True,
}
"""
        
        print("\n2. Executing sensitive code in TEE...")
        result = await tee.execute(
            code=sensitive_code,
            input_data={"pii": {"ssn": "123-45-6789", "dob": "1990-01-01"}},
        )
        
        print(f"   Success: {result.success}")
        print(f"   Output: {result.output}")
        print(f"   Execution hash: {result.execution_hash}")
        print(f"   Code hash: {result.code_hash}")
        
        if result.attestation:
            print(f"\n3. Attestation report:")
            print(f"   Is valid: {result.attestation.is_valid}")
            print(f"   Enclave measurement: {result.attestation.enclave_measurement}")
            print(f"   Timestamp: {result.attestation.timestamp}")
            
            # Verify attestation
            is_valid = await tee.verify_attestation(result.attestation)
            print(f"\n4. Attestation verification: {is_valid}")
        
        await tee.shutdown()
    
    print()


async def container_example():
    """Demonstrate containerized execution."""
    print("=" * 60)
    print("Container Example")
    print("=" * 60)
    
    runtime = AgentRuntime()
    
    # Configure container
    config = ContainerConfig(
        image="python:3.11-slim",
        cpu_limit=0.5,
        memory_limit="256m",
        allow_internet=False,
        read_only_root=True,
    )
    
    # Simple code to execute
    code = """
import sys
print("Hello from container!")
print(f"Python version: {sys.version}")
result = {"status": "success", "message": "Container execution complete"}
"""
    
    print("\n1. Pulling image...")
    success = await runtime.pull_image(config.image)
    print(f"   Success: {success}")
    
    if success:
        print("\n2. Executing in container...")
        # Note: This requires Docker to be running
        # Commented out to avoid errors in environments without Docker
        print("   (Skipped - requires Docker)")
        # result = await runtime.execute(
        #     agent_id="demo-agent",
        #     code=code,
        #     config=config,
        # )
        # print(f"   Success: {result.success}")
        # print(f"   Exit code: {result.exit_code}")
        # print(f"   Output: {result.stdout[:200]}")
    
    print()


async def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("Agent Infrastructure Platform - Secure Execution Demo")
    print("=" * 60)
    print()
    
    await sandbox_example()
    await tee_example()
    await container_example()
    
    print("=" * 60)
    print("Demo completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
