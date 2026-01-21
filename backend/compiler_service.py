"""Facto compiler service with streaming output."""

import asyncio
import tempfile
import os
import re
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator, Callable
from dataclasses import dataclass
from enum import Enum

from config import get_settings
from stats import get_stats

settings = get_settings()


class OutputType(str, Enum):
    LOG = "log"
    BLUEPRINT = "blueprint"
    ERROR = "error"
    STATUS = "status"
    QUEUE = "queue"  # For queue position updates


@dataclass
class CompilerOptions:
    """Options passed to the Facto compiler."""

    power_poles: str | None = None  # small, medium, big, substation
    name: str | None = None  # Blueprint name
    no_optimize: bool = False
    json_output: bool = False
    log_level: str = "info"  # debug, info, warning, error


# ==================== Compilation Queue ====================


class CompilationQueue:
    """
    A queue that ensures only one compilation runs at a time.
    Tracks queue position for waiting clients.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._queue: list[str] = []  # List of request IDs in queue
        self._current: str | None = None  # Currently compiling request ID
        self._events: dict[str, asyncio.Event] = {}  # Events for each waiting request

    @property
    def queue_length(self) -> int:
        """Number of requests waiting in queue (not including current)."""
        return len(self._queue)

    def get_position(self, request_id: str) -> int:
        """Get position in queue (0 = currently compiling, 1+ = waiting)."""
        if self._current == request_id:
            return 0
        try:
            return self._queue.index(request_id) + 1
        except ValueError:
            return -1  # Not in queue

    async def acquire(
        self, request_id: str, position_callback: Callable[[int], None] | None = None
    ) -> bool:
        """
        Wait for turn to compile. Returns True when acquired.
        position_callback is called with queue position updates.
        """
        event = asyncio.Event()

        async with self._lock:
            # If nothing is compiling and queue is empty, start immediately
            if self._current is None and len(self._queue) == 0:
                self._current = request_id
                return True

            # Add to queue
            self._queue.append(request_id)
            self._events[request_id] = event
            position = len(self._queue)

        # Notify initial position
        if position_callback:
            position_callback(position)

        # Wait for our turn with position updates
        while True:
            try:
                # Wait with timeout to periodically update position
                await asyncio.wait_for(event.wait(), timeout=1.0)
                break  # Event was set, we can proceed
            except asyncio.TimeoutError:
                # Update position
                pos = self.get_position(request_id)
                if pos == 0:
                    break  # We're up!
                if pos == -1:
                    return False  # Somehow removed from queue
                if position_callback:
                    position_callback(pos)

        return True

    async def release(self, request_id: str):
        """Release the compilation slot and notify next in queue."""
        async with self._lock:
            if self._current == request_id:
                self._current = None

                # Notify next in queue
                if self._queue:
                    next_id = self._queue.pop(0)
                    self._current = next_id
                    if next_id in self._events:
                        self._events[next_id].set()
                        del self._events[next_id]
            elif request_id in self._queue:
                # Request cancelled while waiting
                self._queue.remove(request_id)
                if request_id in self._events:
                    del self._events[request_id]


# Global compilation queue (only 1 compilation at a time)
_compilation_queue: CompilationQueue | None = None


def get_compilation_queue() -> CompilationQueue:
    global _compilation_queue
    if _compilation_queue is None:
        _compilation_queue = CompilationQueue()
    return _compilation_queue


def sanitize_source(source: str) -> str:
    """
    Sanitize source code to prevent injection attacks.
    Returns cleaned source or raises ValueError.
    """
    if len(source) > settings.max_source_length:
        raise ValueError(
            f"Source code exceeds maximum length of {settings.max_source_length} characters"
        )

    # Remove any null bytes
    source = source.replace("\x00", "")

    # Check for suspicious patterns (shell injection attempts)
    suspicious_patterns = [
        r"`[^`]*`",  # Backtick command substitution
        r"\$\([^)]*\)",  # $() command substitution
        r"\$\{[^}]*\}",  # ${} variable expansion (could be malicious)
        r";\s*rm\s",  # rm commands
        r";\s*cat\s",  # cat commands attempting to read files
        r"\|\s*sh\b",  # Piping to shell
        r"\|\s*bash\b",  # Piping to bash
    ]

    for pattern in suspicious_patterns:
        if re.search(pattern, source, re.IGNORECASE):
            raise ValueError("Source contains potentially malicious content")

    return source


def build_compiler_command(
    source_path: str, output_path: str, options: CompilerOptions
) -> list[str]:
    """Build the compiler command with options."""
    cmd = [settings.facto_compiler_path, source_path, "-o", output_path]

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


async def compile_facto(
    source: str, options: CompilerOptions
) -> AsyncGenerator[tuple[OutputType, str], None]:
    """
    Compile Facto source code and yield output as it becomes available.

    Yields tuples of (output_type, content) for streaming to frontend.
    """
    queue = get_compilation_queue()
    request_id = str(uuid.uuid4())

    # Track queue position updates to yield
    position_updates: list[int] = []

    def on_position_update(pos: int):
        position_updates.append(pos)

    # Check initial queue length
    initial_queue_length = queue.queue_length
    if initial_queue_length > 0 or queue._current is not None:
        yield (OutputType.QUEUE, str(initial_queue_length + 1))
        yield (
            OutputType.STATUS,
            f"Waiting in queue (position {initial_queue_length + 1})...",
        )

    # Try to acquire slot with timeout
    try:
        acquire_task = asyncio.create_task(
            queue.acquire(request_id, on_position_update)
        )

        # Wait for slot with periodic position updates
        while not acquire_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(acquire_task), timeout=1.0)
            except asyncio.TimeoutError:
                # Yield any position updates
                while position_updates:
                    pos = position_updates.pop(0)
                    yield (OutputType.QUEUE, str(pos))
                    yield (OutputType.STATUS, f"Waiting in queue (position {pos})...")

        if not acquire_task.result():
            yield (OutputType.ERROR, "Failed to acquire compilation slot")
            return

    except asyncio.TimeoutError:
        yield (
            OutputType.ERROR,
            "Queue timeout. Server is very busy. Please try again later.",
        )
        await queue.release(request_id)
        return

    # Now we have the slot, yield position 0
    yield (OutputType.QUEUE, "0")

    # Record compilation start
    stats = get_stats()
    await stats.record_compilation_start()
    compilation_success = False
    start_time = time.perf_counter()

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
            mode="w", suffix=".facto", delete=False, encoding="utf-8"
        ) as f:
            f.write(source)
            source_path = f.name

        # Create temporary file for output blueprint
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            output_path = f.name

        try:
            # Build command
            cmd = build_compiler_command(source_path, output_path, options)
            yield (OutputType.LOG, f"Running: {' '.join(cmd)}")

            # Run compiler with timeout
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=os.path.dirname(source_path),
                )
            except FileNotFoundError:
                yield (
                    OutputType.ERROR,
                    f"Compiler not found: '{settings.facto_compiler_path}' is not installed or not in PATH",
                )
                yield (OutputType.ERROR, "Install factompile: pip install factompile")
                return

            # Collect output with timeout
            try:
                async with asyncio.timeout(settings.compilation_timeout):
                    stderr_data = []

                    # Read stderr (log output) line by line
                    if process.stderr:
                        while True:
                            line = await process.stderr.readline()
                            if not line:
                                break
                            decoded = line.decode("utf-8", errors="replace").rstrip()
                            stderr_data.append(decoded)
                            yield (OutputType.LOG, decoded)

                    # Wait for process to complete
                    await process.wait()

                    if process.returncode == 0:
                        yield (OutputType.STATUS, "Compilation successful!")
                        compilation_success = True
                        # Read blueprint from output file (clean output)
                        try:
                            with open(output_path, "r", encoding="utf-8") as bp_file:
                                blueprint = bp_file.read().strip()
                                if blueprint:
                                    yield (OutputType.BLUEPRINT, blueprint)
                        except FileNotFoundError:
                            yield (OutputType.ERROR, "Blueprint output file not found")
                            compilation_success = False
                    else:
                        yield (
                            OutputType.STATUS,
                            f"Compilation failed (exit code {process.returncode})",
                        )
                        yield (OutputType.ERROR, "See log output for details")

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                yield (
                    OutputType.ERROR,
                    f"Compilation timed out after {settings.compilation_timeout} seconds",
                )

        finally:
            # Clean up temporary files
            try:
                os.unlink(source_path)
            except OSError:
                pass
            try:
                os.unlink(output_path)
            except OSError:
                pass

    finally:
        # Record compilation result with timing
        duration = time.perf_counter() - start_time
        if compilation_success:
            await stats.record_compilation_success(duration)
        else:
            await stats.record_compilation_failure(duration)
        await queue.release(request_id)
