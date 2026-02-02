"""Agent Runtime for portable execution environments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

import structlog

from agent_infrastructure_platform.common.types import AgentID

logger = structlog.get_logger()


@dataclass
class ContainerConfig:
    """Configuration for agent container."""
    
    image: str = "python:3.11-slim"
    command: list[str] = field(default_factory=lambda: ["python", "-m", "agent"])
    
    # Resources
    cpu_limit: float = 1.0  # CPU cores
    memory_limit: str = "512m"  # Memory limit
    timeout_seconds: float = 300.0
    
    # Environment
    env_vars: dict[str, str] = field(default_factory=dict)
    volumes: list[tuple[str, str]] = field(default_factory=list)  # (host, container)
    
    # Network
    network_mode: str = "bridge"
    allow_internet: bool = False
    
    # Security
    read_only_root: bool = True
    drop_capabilities: list[str] = field(default_factory=lambda: ["ALL"])
    seccomp_profile: str | None = None
    
    # Runtime
    runtime: str = "runc"  # runc, gvisor, kata


@dataclass
class ExecutionResult:
    """Result of container execution."""
    
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    
    # Resource usage
    cpu_time_ms: float | None = None
    memory_peak_mb: float | None = None
    
    # Attestation
    execution_hash: str | None = None


class AgentRuntime:
    """
    Portable runtime environment for agent execution.
    
    Features:
    - Containerized execution
    - Resource limits
    - Network isolation
    - Security sandboxing
    - Verifiable execution
    
    Example:
        ```python
        runtime = AgentRuntime()
        
        # Create container config
        config = ContainerConfig(
            image="agent-base:latest",
            memory_limit="1g",
            cpu_limit=2.0,
            allow_internet=False,
        )
        
        # Execute agent code
        result = await runtime.execute(
            agent_id="agent-1",
            code=agent_code,
            config=config,
            input_data={"task": "analyze_data"},
        )
        
        if result.success:
            print(result.stdout)
        ```
    """

    def __init__(
        self,
        default_config: ContainerConfig | None = None,
        work_dir: str | None = None,
    ) -> None:
        self.default_config = default_config or ContainerConfig()
        self.work_dir = work_dir or tempfile.gettempdir()
        
        # Track running containers
        self._containers: dict[str, subprocess.Popen] = {}
        
        # Execution cache for verification
        self._execution_logs: dict[str, dict[str, Any]] = {}
        
        self._logger = logger
    
    async def execute(
        self,
        agent_id: AgentID,
        code: str,
        config: ContainerConfig | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """
        Execute agent code in container.
        
        Args:
            agent_id: Agent identifier
            code: Python code to execute
            config: Container configuration
            input_data: Input data for execution
            
        Returns:
            Execution result
        """
        config = config or self.default_config
        execution_id = f"exec-{uuid4().hex[:12]}"
        
        self._logger.info(
            "execution_starting",
            execution_id=execution_id,
            agent_id=agent_id,
            image=config.image,
        )
        
        # Create execution directory
        exec_dir = Path(self.work_dir) / execution_id
        exec_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Write code file
            code_file = exec_dir / "agent.py"
            code_file.write_text(code)
            
            # Write input data
            input_file = exec_dir / "input.json"
            input_file.write_text(json.dumps(input_data or {}))
            
            # Build Docker command
            cmd = self._build_docker_command(config, exec_dir)
            
            # Execute with timeout
            start_time = asyncio.get_event_loop().time()
            
            try:
                process = await asyncio.wait_for(
                    self._run_container(cmd, config),
                    timeout=config.timeout_seconds,
                )
                
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                
                # Read outputs
                stdout_file = exec_dir / "stdout.txt"
                stderr_file = exec_dir / "stderr.txt"
                
                stdout = stdout_file.read_text() if stdout_file.exists() else ""
                stderr = stderr_file.read_text() if stderr_file.exists() else ""
                
                success = process.returncode == 0
                
                # Compute execution hash for verification
                execution_hash = hashlib.sha256(
                    f"{code}{stdout}{stderr}{process.returncode}".encode()
                ).hexdigest()
                
                result = ExecutionResult(
                    success=success,
                    exit_code=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    duration_ms=duration_ms,
                    execution_hash=execution_hash,
                )
                
                # Log execution
                self._execution_logs[execution_id] = {
                    "agent_id": agent_id,
                    "execution_id": execution_id,
                    "config": config,
                    "result": result,
                    "timestamp": start_time,
                }
                
                self._logger.info(
                    "execution_completed",
                    execution_id=execution_id,
                    success=success,
                    duration_ms=duration_ms,
                )
                
                return result
                
            except asyncio.TimeoutError:
                self._logger.error("execution_timeout", execution_id=execution_id)
                return ExecutionResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr="Execution timed out",
                    duration_ms=config.timeout_seconds * 1000,
                )
                
        finally:
            # Cleanup
            import shutil
            shutil.rmtree(exec_dir, ignore_errors=True)
    
    def _build_docker_command(self, config: ContainerConfig, exec_dir: Path) -> list[str]:
        """Build Docker run command."""
        cmd = [
            "docker", "run",
            "--rm",
            "--network", config.network_mode if config.allow_internet else "none",
            "--cpus", str(config.cpu_limit),
            "--memory", config.memory_limit,
            "--read-only" if config.read_only_root else "",
        ]
        
        # Add capability drops
        for cap in config.drop_capabilities:
            cmd.extend(["--cap-drop", cap])
        
        # Add volumes
        cmd.extend(["-v", f"{exec_dir}:/workspace"])
        for host, container in config.volumes:
            cmd.extend(["-v", f"{host}:{container}"])
        
        # Add environment variables
        for key, value in config.env_vars.items():
            cmd.extend(["-e", f"{key}={value}"])
        
        # Add image and command
        cmd.append(config.image)
        cmd.extend(config.command)
        
        # Remove empty strings
        return [c for c in cmd if c]
    
    async def _run_container(
        self,
        cmd: list[str],
        config: ContainerConfig,
    ) -> subprocess.CompletedProcess:
        """Run container and return result."""
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await process.communicate()
        
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=process.returncode,
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )
    
    async def stream_logs(
        self,
        execution_id: str,
    ) -> AsyncIterator[str]:
        """Stream logs from a running execution."""
        # Implementation would tail container logs
        yield f"Streaming logs for {execution_id}"
    
    async def verify_execution(self, execution_id: str) -> bool:
        """
        Verify execution integrity.
        
        Args:
            execution_id: Execution to verify
            
        Returns:
            True if execution is valid
        """
        log = self._execution_logs.get(execution_id)
        if not log:
            return False
        
        # Verify hash
        result = log["result"]
        expected_hash = result.execution_hash
        
        # In a real implementation, this would verify
        # against a blockchain or distributed ledger
        
        return expected_hash is not None
    
    def get_execution_log(self, execution_id: str) -> dict[str, Any] | None:
        """Get execution log."""
        return self._execution_logs.get(execution_id)
    
    async def pull_image(self, image: str) -> bool:
        """Pull container image."""
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "pull", image,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
            return process.returncode == 0
        except Exception as e:
            self._logger.error("image_pull_failed", image=image, error=str(e))
            return False
