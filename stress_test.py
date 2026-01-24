#!/usr/bin/env python3
"""
Stress test script for Facto web compiler.

Sends a large volume of compile requests to test system behavior under load.

Usage:
    python3 stress_test.py [--url URL] [--requests N] [--concurrent N] [--duration SECONDS]
"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from typing import List, Dict, Any
import aiohttp


# Sample Facto code for testing
SAMPLE_FACTO_CODE = """
// Simple test program
function main() {
    let x = 5;
    let y = 10;
    return x + y;
}
"""

COMPLEX_FACTO_CODE = """
// More complex test program
function fibonacci(n) {
    if (n <= 1) {
        return n;
    }
    return fibonacci(n - 1) + fibonacci(n - 2);
}

function main() {
    let result = fibonacci(10);
    return result;
}
"""


class StressTestStats:
    """Track stress test statistics."""

    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.timeouts = 0
        self.connection_errors = 0
        self.rate_limit_errors = 0
        self.response_times: List[float] = []
        self.start_time = None
        self.end_time = None

    def record_success(self, duration: float):
        """Record a successful request."""
        self.successful_requests += 1
        self.response_times.append(duration)

    def record_failure(self, error_type: str = "unknown"):
        """Record a failed request."""
        self.failed_requests += 1
        if error_type == "timeout":
            self.timeouts += 1
        elif error_type == "connection":
            self.connection_errors += 1
        elif error_type == "rate_limit":
            self.rate_limit_errors += 1

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        total_time = (
            (self.end_time - self.start_time)
            if self.start_time and self.end_time
            else 0
        )

        summary = {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "timeouts": self.timeouts,
            "connection_errors": self.connection_errors,
            "rate_limit_errors": self.rate_limit_errors,
            "success_rate": round(
                self.successful_requests / self.total_requests * 100, 2
            )
            if self.total_requests > 0
            else 0,
            "total_duration_seconds": round(total_time, 2),
        }

        if self.response_times:
            sorted_times = sorted(self.response_times)
            n = len(sorted_times)

            summary["avg_response_time_seconds"] = round(sum(sorted_times) / n, 3)
            summary["min_response_time_seconds"] = round(sorted_times[0], 3)
            summary["max_response_time_seconds"] = round(sorted_times[-1], 3)

            # Median
            if n % 2 == 0:
                median = (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2
            else:
                median = sorted_times[n // 2]
            summary["median_response_time_seconds"] = round(median, 3)

            # Percentiles
            p95_idx = int(n * 0.95)
            p99_idx = int(n * 0.99)
            summary["p95_response_time_seconds"] = round(sorted_times[p95_idx], 3)
            summary["p99_response_time_seconds"] = round(sorted_times[p99_idx], 3)

            # Requests per second
            if total_time > 0:
                summary["requests_per_second"] = round(
                    self.successful_requests / total_time, 2
                )

        return summary

    def print_summary(self):
        """Print summary statistics."""
        summary = self.get_summary()

        print("\n" + "=" * 60)
        print("STRESS TEST RESULTS")
        print("=" * 60)
        print(f"Total requests:       {summary['total_requests']}")
        print(f"Successful:           {summary['successful_requests']}")
        print(f"Failed:               {summary['failed_requests']}")
        print(f"  - Timeouts:         {summary['timeouts']}")
        print(f"  - Connection errors: {summary['connection_errors']}")
        print(f"  - Rate limit errors: {summary['rate_limit_errors']}")
        print(f"Success rate:         {summary['success_rate']}%")
        print(f"Total duration:       {summary['total_duration_seconds']}s")

        if self.response_times:
            print(f"\nResponse times:")
            print(f"  Min:                {summary['min_response_time_seconds']}s")
            print(f"  Average:            {summary['avg_response_time_seconds']}s")
            print(f"  Median:             {summary['median_response_time_seconds']}s")
            print(f"  P95:                {summary['p95_response_time_seconds']}s")
            print(f"  P99:                {summary['p99_response_time_seconds']}s")
            print(f"  Max:                {summary['max_response_time_seconds']}s")
            print(f"\nThroughput:")
            print(f"  Requests/second:    {summary.get('requests_per_second', 0)}")

        print("=" * 60 + "\n")


async def send_compile_request(
    session: aiohttp.ClientSession,
    url: str,
    code: str,
    stats: StressTestStats,
    request_id: int,
    timeout: int = 60,
) -> None:
    """
    Send a single compile request.

    Args:
        session: aiohttp session
        url: Compile endpoint URL
        code: Facto source code
        stats: Stats tracker
        request_id: Request identifier
        timeout: Request timeout in seconds
    """
    stats.total_requests += 1
    start_time = time.time()

    payload = {"source": code, "json_output": False, "log_level": "info"}

    try:
        async with session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as response:
            duration = time.time() - start_time

            if response.status == 200:
                # For streaming endpoint, just check that we got a response
                stats.record_success(duration)
                print(f"[{request_id}] ✓ Success ({duration:.2f}s)")
            elif response.status == 429:
                stats.record_failure("rate_limit")
                print(f"[{request_id}] ✗ Rate limited")
            else:
                stats.record_failure("unknown")
                print(f"[{request_id}] ✗ Failed (HTTP {response.status})")

    except asyncio.TimeoutError:
        stats.record_failure("timeout")
        print(f"[{request_id}] ✗ Timeout")
    except aiohttp.ClientError as e:
        stats.record_failure("connection")
        print(f"[{request_id}] ✗ Connection error: {e}")
    except Exception as e:
        stats.record_failure("unknown")
        print(f"[{request_id}] ✗ Error: {e}")


async def run_stress_test(
    url: str,
    total_requests: int,
    concurrent_requests: int,
    duration: int = None,
    use_complex_code: bool = False,
) -> StressTestStats:
    """
    Run stress test.

    Args:
        url: Target URL
        total_requests: Total number of requests to send
        concurrent_requests: Number of concurrent requests
        duration: Run for this many seconds (overrides total_requests if set)
        use_complex_code: Use more complex code samples

    Returns:
        StressTestStats object with results
    """
    stats = StressTestStats()
    stats.start_time = time.time()

    print(f"\nStarting stress test...")
    print(f"  Target: {url}")
    print(
        f"  Total requests: {total_requests if not duration else 'unlimited (duration-based)'}"
    )
    print(f"  Concurrent requests: {concurrent_requests}")
    if duration:
        print(f"  Duration: {duration}s")
    print(f"  Code complexity: {'complex' if use_complex_code else 'simple'}")
    print()

    code = COMPLEX_FACTO_CODE if use_complex_code else SAMPLE_FACTO_CODE

    async with aiohttp.ClientSession() as session:
        if duration:
            # Duration-based test
            end_time = time.time() + duration
            request_id = 0

            while time.time() < end_time:
                tasks = []
                batch_size = min(concurrent_requests, 100)  # Limit batch size

                for _ in range(batch_size):
                    request_id += 1
                    task = send_compile_request(session, url, code, stats, request_id)
                    tasks.append(task)

                await asyncio.gather(*tasks)

                # Brief pause between batches
                await asyncio.sleep(0.1)
        else:
            # Request count-based test
            tasks = []

            for i in range(1, total_requests + 1):
                task = send_compile_request(session, url, code, stats, i)
                tasks.append(task)

                # Execute in batches to respect concurrency limit
                if len(tasks) >= concurrent_requests or i == total_requests:
                    await asyncio.gather(*tasks)
                    tasks = []

                    # Brief pause between batches
                    if i < total_requests:
                        await asyncio.sleep(0.1)

    stats.end_time = time.time()
    return stats


def main():
    parser = argparse.ArgumentParser(description="Stress test Facto web compiler")
    parser.add_argument(
        "--url",
        default="https://facto.spokenrobot.com:3000/compile/sync",
        help="Compile endpoint URL (default: https://facto.spokenrobot.com:3000/compile/sync)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=100,
        help="Total number of requests to send (default: 100)",
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=10,
        help="Number of concurrent requests (default: 10)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        help="Run for this many seconds instead of fixed request count",
    )
    parser.add_argument(
        "--complex", action="store_true", help="Use more complex code samples"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Request timeout in seconds (default: 60)",
    )

    args = parser.parse_args()

    # Run stress test
    stats = asyncio.run(
        run_stress_test(
            url=args.url,
            total_requests=args.requests,
            concurrent_requests=args.concurrent,
            duration=args.duration,
            use_complex_code=args.complex,
        )
    )

    # Print results
    stats.print_summary()

    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"stress_test_results_{timestamp}.json"

    with open(results_file, "w") as f:
        json.dump(stats.get_summary(), f, indent=2)

    print(f"Results saved to: {results_file}")


if __name__ == "__main__":
    main()
