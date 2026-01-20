"""Facto compiler service with streaming output."""

import asyncio
import subprocess
import tempfile
import os
import re
from pathlib import Path
from typing import AsyncGenerator
from dataclasses import dataclass
from enum import Enum

from config import get_settings

settings = get_settings()


class OutputType(str, Enum):
    LOG = "log"
    BLUEPRINT = "blueprint"
    ERROR = "error"
    STATUS = "status"


@dataclass
class CompilerOptions:
    """Options passed to the Facto compiler."""
    power_poles: str | None = None  # small, medium, big, substation
    name: str | None = None         # Blueprint name
    no_optimize: bool = False
    json_output: bool = False
    log_level: str = "info"         # debug, info, warning, error


def sanitize_source(source: str) -> str:
    """
    Sanitize source code to prevent injection attacks.
    Returns cleaned source or raises ValueError.
    """
    if len(source) > settings.max_source_length:
        raise ValueError(f"Source code exceeds maximum length of {settings.max_source_length} characters")
    
    # Remove any null bytes
    source = source.replace('\x00', '')
    
    # Check for suspicious patterns (shell injection attempts)
    suspicious_patterns = [
        r'`[^`]*`',           # Backtick command substitution
        r'\$\([^)]*\)',       # $() command substitution
        r'\$\{[^}]*\}',       # ${} variable expansion (could be malicious)
        r';\s*rm\s',          # rm commands
        r';\s*cat\s',         # cat commands attempting to read files
        r'\|\s*sh\b',         # Piping to shell
        r'\|\s*bash\b',       # Piping to bash
    ]
    
    for pattern in suspicious_patterns:
        if re.search(pattern, source, re.IGNORECASE):
            raise ValueError("Source contains potentially malicious content")
    
    return source


def build_compiler_command(source_path: str, options: CompilerOptions) -> list[str]:
    """Build the compiler command with options."""
    cmd = [settings.facto_compiler_path, source_path]
    
    if options.power_poles:
        cmd.extend(["--power-poles", options.power_poles])
    
    if options.name:
        cmd.extend(["--name", options.name])
    
    if options.no_optimize:
        cmd.append("--no-optimize")
    
    if options.json_output:
        cmd.append("--json")
    
    if options.log_level:
        cmd.extend(["--log-level", options.log_level])
    
    return cmd


# Semaphore to limit concurrent compilations
_compilation_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _compilation_semaphore
    if _compilation_semaphore is None:
        _compilation_semaphore = asyncio.Semaphore(settings.max_concurrent_compilations)
    return _compilation_semaphore


async def compile_facto(
    source: str,
    options: CompilerOptions
) -> AsyncGenerator[tuple[OutputType, str], None]:
    """
    Compile Facto source code and yield output as it becomes available.
    
    Yields tuples of (output_type, content) for streaming to frontend.
    """
    # Acquire semaphore to limit concurrent compilations
    semaphore = get_semaphore()
    
    try:
        async with asyncio.timeout(5):  # Wait max 5 seconds for slot
            await semaphore.acquire()
    except asyncio.TimeoutError:
        yield (OutputType.ERROR, "Server busy. Too many concurrent compilations. Please try again.")
        return
    
    try:
        # Sanitize input
        try:
            source = sanitize_source(source)
        except ValueError as e:
            yield (OutputType.ERROR, str(e))
            return
        
        yield (OutputType.STATUS, "Starting compilation...")
        
        # Create temporary file for source
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.facto',
            delete=False,
            encoding='utf-8'
        ) as f:
            f.write(source)
            source_path = f.name
        
        try:
            # Build command
            cmd = build_compiler_command(source_path, options)
            yield (OutputType.LOG, f"Running: {' '.join(cmd)}")
            
            # Run compiler with timeout
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=os.path.dirname(source_path)
                )
            except FileNotFoundError:
                yield (OutputType.ERROR, f"Compiler not found: '{settings.facto_compiler_path}' is not installed or not in PATH")
                yield (OutputType.ERROR, "Install factompile: pip install factompile")
                return
            
            # Collect output with timeout
            try:
                async with asyncio.timeout(settings.compilation_timeout):
                    stdout_data = []
                    stderr_data = []
                    
                    # Read stderr (log output) line by line
                    if process.stderr:
                        while True:
                            line = await process.stderr.readline()
                            if not line:
                                break
                            decoded = line.decode('utf-8', errors='replace').rstrip()
                            stderr_data.append(decoded)
                            yield (OutputType.LOG, decoded)
                    
                    # Read stdout (blueprint output)
                    if process.stdout:
                        stdout_bytes = await process.stdout.read()
                        stdout_text = stdout_bytes.decode('utf-8', errors='replace').strip()
                        if stdout_text:
                            stdout_data.append(stdout_text)
                    
                    await process.wait()
                    
                    if process.returncode == 0:
                        yield (OutputType.STATUS, "Compilation successful!")
                        if stdout_data:
                            # The blueprint is in stdout
                            yield (OutputType.BLUEPRINT, stdout_data[-1])
                    else:
                        yield (OutputType.STATUS, f"Compilation failed (exit code {process.returncode})")
                        yield (OutputType.ERROR, "See log output for details")
                        
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                yield (OutputType.ERROR, f"Compilation timed out after {settings.compilation_timeout} seconds")
                
        finally:
            # Clean up temporary file
            try:
                os.unlink(source_path)
            except OSError:
                pass
                
    finally:
        semaphore.release()
