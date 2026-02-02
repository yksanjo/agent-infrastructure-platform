"""Secure Sandbox for agent code execution."""

from __future__ import annotations

import ast
import builtins
import resource
import signal
import sys
import traceback
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable

import structlog

logger = structlog.get_logger()


@dataclass
class SandboxConfig:
    """Configuration for sandboxed execution."""
    
    # Time limits
    max_execution_time: float = 30.0  # seconds
    max_cpu_time: float = 10.0  # seconds
    
    # Memory limits
    max_memory_mb: int = 256
    
    # Code limits
    max_code_size: int = 100000  # characters
    max_ast_nodes: int = 10000
    
    # Allowed operations
    allowed_modules: list[str] = field(default_factory=lambda: [
        "json", "re", "math", "random", "datetime", "collections",
        "itertools", "functools", "typing", "hashlib", "base64",
    ])
    blocked_builtins: list[str] = field(default_factory=lambda: [
        "__import__", "eval", "exec", "compile", "open",
        "input", "raw_input", "reload", "exit", "quit",
    ])
    
    # Network
    allow_network: bool = False
    
    # File system
    allow_file_read: bool = False
    allow_file_write: bool = False
    allowed_paths: list[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    """Result of sandboxed execution."""
    
    success: bool
    result: Any = None
    error: str | None = None
    error_type: str | None = None
    
    # Resource usage
    execution_time_ms: float = 0.0
    memory_peak_mb: float = 0.0
    
    # Security
    security_violations: list[str] = field(default_factory=list)


class Sandbox:
    """
    Secure sandbox for executing untrusted agent code.
    
    Features:
    - AST analysis and validation
    - Resource limits (CPU, memory, time)
    - Restricted builtins
    - Module whitelist
    - File system restrictions
    
    Example:
        ```python
        sandbox = Sandbox(SandboxConfig(
            max_execution_time=10.0,
            max_memory_mb=128,
            allowed_modules=["json", "math"],
        ))
        
        result = sandbox.execute("""
            import json
            import math
            
            data = {"x": 10, "y": 20}
            result = math.sqrt(data["x"] ** 2 + data["y"] ** 2)
        """)
        
        if result.success:
            print(f"Result: {result.result}")
        else:
            print(f"Error: {result.error}")
        ```
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config or SandboxConfig()
        self._logger = logger
    
    def execute(self, code: str, context: dict[str, Any] | None = None) -> SandboxResult:
        """
        Execute code in sandbox.
        
        Args:
            code: Python code to execute
            context: Variables to inject into execution context
            
        Returns:
            Sandbox result
        """
        import time
        
        start_time = time.perf_counter()
        violations: list[str] = []
        
        # Validate code size
        if len(code) > self.config.max_code_size:
            return SandboxResult(
                success=False,
                error=f"Code exceeds maximum size of {self.config.max_code_size}",
                error_type="ValidationError",
                security_violations=["code_too_large"],
            )
        
        # Parse and validate AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return SandboxResult(
                success=False,
                error=str(e),
                error_type="SyntaxError",
            )
        
        # Check AST complexity
        node_count = sum(1 for _ in ast.walk(tree))
        if node_count > self.config.max_ast_nodes:
            return SandboxResult(
                success=False,
                error=f"Code too complex: {node_count} nodes > {self.config.max_ast_nodes}",
                error_type="ValidationError",
                security_violations=["too_complex"],
            )
        
        # Analyze AST for security
        violations = self._analyze_ast(tree)
        if violations:
            return SandboxResult(
                success=False,
                error=f"Security violations: {violations}",
                error_type="SecurityError",
                security_violations=violations,
            )
        
        # Set up restricted environment
        env = self._create_restricted_env()
        
        # Add context variables
        if context:
            env.update(context)
        
        # Execute with resource limits
        try:
            # Set memory limit
            memory_limit = self.config.max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
            
            # Set CPU time limit
            def timeout_handler(signum, frame):
                raise TimeoutError("Execution timed out")
            
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(self.config.max_execution_time))
            
            try:
                exec(compile(tree, "<sandbox>", "exec"), env)
                
                # Get result (look for common result variables)
                result_value = env.get("result") or env.get("_") or env.get("output")
                
                execution_time = (time.perf_counter() - start_time) * 1000
                
                return SandboxResult(
                    success=True,
                    result=result_value,
                    execution_time_ms=execution_time,
                )
                
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
                
        except TimeoutError as e:
            return SandboxResult(
                success=False,
                error="Execution timed out",
                error_type="TimeoutError",
                execution_time_ms=self.config.max_execution_time * 1000,
            )
        except MemoryError:
            return SandboxResult(
                success=False,
                error="Out of memory",
                error_type="MemoryError",
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                error=str(e),
                error_type=type(e).__name__,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
    
    def _analyze_ast(self, tree: ast.AST) -> list[str]:
        """Analyze AST for security violations."""
        violations = []
        
        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in self.config.allowed_modules:
                        violations.append(f"import_not_allowed:{alias.name}")
            
            elif isinstance(node, ast.ImportFrom):
                if node.module not in self.config.allowed_modules:
                    violations.append(f"import_not_allowed:{node.module}")
            
            # Check for dangerous builtins
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.config.blocked_builtins:
                        violations.append(f"blocked_builtin:{node.func.id}")
            
            # Check for file operations
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in ("open", "file"):
                        if not self.config.allow_file_read and not self.config.allow_file_write:
                            violations.append("file_operation_not_allowed")
            
            # Check for network operations
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("socket", "connect", "urlopen"):
                        if not self.config.allow_network:
                            violations.append("network_operation_not_allowed")
        
        return violations
    
    def _create_restricted_env(self) -> dict[str, Any]:
        """Create restricted execution environment."""
        # Start with safe builtins
        safe_builtins = {
            name: getattr(builtins, name)
            for name in dir(builtins)
            if name not in self.config.blocked_builtins
            and not name.startswith("_")
        }
        
        # Create restricted environment
        env = {
            "__builtins__": safe_builtins,
            "__name__": "__sandbox__",
        }
        
        # Add allowed modules
        for module_name in self.config.allowed_modules:
            try:
                import importlib
                module = importlib.import_module(module_name)
                env[module_name] = module
            except ImportError:
                pass
        
        return env
    
    def validate(self, code: str) -> tuple[bool, list[str]]:
        """
        Validate code without executing.
        
        Returns:
            (is_valid, list of violations)
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, [f"syntax_error:{e}"]
        
        violations = self._analyze_ast(tree)
        
        return len(violations) == 0, violations
