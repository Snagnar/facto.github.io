"""Simple statistics collection for Facto web compiler."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


# How many recent compilation times to keep for statistics
MAX_RECENT_TIMES = 100


class Stats:
    """
    Simple statistics tracker that persists to a YAML file.
    Thread-safe for async operations.
    """

    def __init__(self, stats_file: str = "stats.yaml"):
        self._file_path = Path(stats_file)
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] = self._load_or_init()

    def _load_or_init(self) -> dict[str, Any]:
        """Load existing stats or initialize new ones."""
        if self._file_path.exists():
            try:
                with open(self._file_path, "r") as f:
                    data = yaml.safe_load(f) or {}
                    # Ensure all required fields exist
                    self._ensure_fields(data)
                    return data
            except Exception:
                pass

        return self._create_initial_data()

    def _create_initial_data(self) -> dict[str, Any]:
        """Create initial stats structure."""
        return {
            "created_at": datetime.utcnow().isoformat(),
            "last_updated": datetime.utcnow().isoformat(),
            "unique_sessions": 0,
            "total_compilations": 0,
            "successful_compilations": 0,
            "failed_compilations": 0,
            "compilation_times": [],  # Recent times in seconds for computing stats
            "avg_compilation_time_seconds": 0.0,
            "median_compilation_time_seconds": 0.0,
            "min_compilation_time_seconds": 0.0,
            "max_compilation_time_seconds": 0.0,
        }

    def _ensure_fields(self, data: dict[str, Any]):
        """Ensure all required fields exist in loaded data."""
        defaults = self._create_initial_data()
        for key, value in defaults.items():
            if key not in data:
                data[key] = value

    async def _save(self):
        """Save stats to YAML file."""
        self._data["last_updated"] = datetime.utcnow().isoformat()
        try:
            with open(self._file_path, "w") as f:
                yaml.dump(self._data, f, default_flow_style=False, sort_keys=False)
        except Exception as e:
            print(f"Warning: Could not save stats: {e}")

    async def record_session(self):
        """Record a new session (frontend connect)."""
        async with self._lock:
            self._data["unique_sessions"] = self._data.get("unique_sessions", 0) + 1
            await self._save()

    async def record_compilation_start(self):
        """Record start of a compilation."""
        async with self._lock:
            self._data["total_compilations"] = (
                self._data.get("total_compilations", 0) + 1
            )
            await self._save()

    async def record_compilation_success(self, duration_seconds: float):
        """Record successful compilation with timing."""
        async with self._lock:
            self._data["successful_compilations"] = (
                self._data.get("successful_compilations", 0) + 1
            )
            self._record_compilation_time(duration_seconds)
            await self._save()

    async def record_compilation_failure(self, duration_seconds: float):
        """Record failed compilation with timing."""
        async with self._lock:
            self._data["failed_compilations"] = (
                self._data.get("failed_compilations", 0) + 1
            )
            self._record_compilation_time(duration_seconds)
            await self._save()

    def _record_compilation_time(self, duration: float):
        """Record a compilation time and update statistics."""
        times = self._data.get("compilation_times", [])
        times.append(round(duration, 3))

        # Keep only recent times
        if len(times) > MAX_RECENT_TIMES:
            times = times[-MAX_RECENT_TIMES:]

        self._data["compilation_times"] = times

        # Update time statistics
        if times:
            sorted_times = sorted(times)
            self._data["avg_compilation_time_seconds"] = round(
                sum(times) / len(times), 3
            )
            self._data["min_compilation_time_seconds"] = sorted_times[0]
            self._data["max_compilation_time_seconds"] = sorted_times[-1]

            # Median
            n = len(sorted_times)
            if n % 2 == 0:
                median = (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2
            else:
                median = sorted_times[n // 2]
            self._data["median_compilation_time_seconds"] = round(median, 3)

    def get_stats(self) -> dict[str, Any]:
        """Get current statistics (excluding raw times list)."""
        result = dict(self._data)
        # Don't expose the raw times list
        result.pop("compilation_times", None)
        return result


# Global stats instance
_stats: Stats | None = None


def get_stats() -> Stats:
    """Get the global stats instance."""
    global _stats
    if _stats is None:
        _stats = Stats()
    return _stats
