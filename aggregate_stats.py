#!/usr/bin/env python3
"""
Stats aggregation script for Facto backend servers.

This script:
1. Reads backend server addresses from nginx config
2. Fetches stats from each backend server
3. Aggregates the statistics
4. Writes to an aggregated stats file
5. Optionally parses nginx access logs for request metrics
6. Updates every 10 seconds

Usage:
    python3 aggregate_stats.py [--nginx-config PATH] [--output PATH] [--interval SECONDS]
"""

import argparse
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any
import urllib.request
import urllib.error
import yaml


def parse_nginx_config(config_path: str) -> List[str]:
    """
    Parse nginx config to extract backend server addresses.

    Looks for upstream blocks and extracts server directives.
    Example:
        upstream facto_backend {
            server localhost:3001;
            server localhost:3002;
        }

    Returns list of server addresses (e.g., ['localhost:3001', 'localhost:3002'])
    """
    servers = []

    try:
        with open(config_path, "r") as f:
            content = f.read()

        # Find upstream blocks
        upstream_pattern = r"upstream\s+[\w_]+\s*\{([^}]+)\}"
        upstream_blocks = re.findall(upstream_pattern, content, re.DOTALL)

        for block in upstream_blocks:
            # Extract server directives
            server_pattern = r"server\s+([\w\.\-:]+)"
            block_servers = re.findall(server_pattern, block)
            servers.extend(block_servers)

        # Remove duplicates while preserving order
        seen = set()
        unique_servers = []
        for server in servers:
            if server not in seen:
                seen.add(server)
                unique_servers.append(server)

        return unique_servers

    except FileNotFoundError:
        print(f"Warning: Nginx config not found at {config_path}")
        return []
    except Exception as e:
        print(f"Error parsing nginx config: {e}")
        return []


def fetch_stats_from_server(
    server_address: str, stats_port: int = 4000, timeout: int = 5
) -> Dict[str, Any]:
    """
    Fetch statistics from a single backend server.

    Args:
        server_address: Server address (e.g., 'localhost:3001')
        stats_port: Port where stats server is running
        timeout: Request timeout in seconds

    Returns:
        Dictionary with stats, or empty dict on failure
    """
    # Extract host from server_address (remove port if present)
    host = server_address.split(":")[0]

    url = f"http://{host}:{stats_port}/stats"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "StatsAggregator/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data
    except urllib.error.URLError as e:
        print(f"Warning: Could not fetch stats from {url}: {e}")
        return {}
    except json.JSONDecodeError as e:
        print(f"Warning: Invalid JSON from {url}: {e}")
        return {}
    except Exception as e:
        print(f"Warning: Error fetching stats from {url}: {e}")
        return {}


def aggregate_stats(stats_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate statistics from multiple backend servers.

    Rules:
    - SUM: total_compilations, successful_compilations, failed_compilations, unique_sessions
    - AVERAGE: avg_compilation_time_seconds, median_compilation_time_seconds
    - MIN: min_compilation_time_seconds (across all servers)
    - MAX: max_compilation_time_seconds (across all servers)
    - LATEST: created_at (oldest), last_updated (newest)
    """
    if not stats_list:
        return {
            "error": "No stats available",
            "aggregated_at": datetime.utcnow().isoformat(),
            "server_count": 0,
        }

    # Filter out empty dicts
    stats_list = [s for s in stats_list if s]

    if not stats_list:
        return {
            "error": "No valid stats available",
            "aggregated_at": datetime.utcnow().isoformat(),
            "server_count": 0,
        }

    aggregated = {
        "aggregated_at": datetime.utcnow().isoformat(),
        "server_count": len(stats_list),
        "servers_queried": len([s for s in stats_list if s]),
    }

    # SUM metrics
    sum_metrics = [
        "total_compilations",
        "successful_compilations",
        "failed_compilations",
        "unique_sessions",
    ]

    for metric in sum_metrics:
        values = [s.get(metric, 0) for s in stats_list if s.get(metric) is not None]
        aggregated[metric] = sum(values)

    # AVERAGE metrics
    avg_metrics = ["avg_compilation_time_seconds", "median_compilation_time_seconds"]

    for metric in avg_metrics:
        values = [
            s.get(metric, 0)
            for s in stats_list
            if s.get(metric) is not None and s.get(metric) > 0
        ]
        if values:
            aggregated[metric] = round(sum(values) / len(values), 3)
        else:
            aggregated[metric] = 0.0

    # MIN metric
    min_values = [
        s.get("min_compilation_time_seconds", float("inf"))
        for s in stats_list
        if s.get("min_compilation_time_seconds") is not None
        and s.get("min_compilation_time_seconds") > 0
    ]
    aggregated["min_compilation_time_seconds"] = (
        round(min(min_values), 3) if min_values else 0.0
    )

    # MAX metric
    max_values = [
        s.get("max_compilation_time_seconds", 0)
        for s in stats_list
        if s.get("max_compilation_time_seconds") is not None
    ]
    aggregated["max_compilation_time_seconds"] = (
        round(max(max_values), 3) if max_values else 0.0
    )

    # LATEST timestamps
    created_dates = [s.get("created_at") for s in stats_list if s.get("created_at")]
    if created_dates:
        aggregated["created_at"] = min(created_dates)  # Oldest

    last_updated_dates = [
        s.get("last_updated") for s in stats_list if s.get("last_updated")
    ]
    if last_updated_dates:
        aggregated["last_updated"] = max(last_updated_dates)  # Newest

    # Calculate success rate
    total = aggregated.get("total_compilations", 0)
    successful = aggregated.get("successful_compilations", 0)
    if total > 0:
        aggregated["success_rate"] = round(successful / total * 100, 2)
    else:
        aggregated["success_rate"] = 0.0

    return aggregated


def parse_nginx_access_log(log_path: str, minutes: int = 1) -> Dict[str, Any]:
    """
    Parse nginx access log to get request metrics.

    Args:
        log_path: Path to nginx access.log
        minutes: Look back this many minutes

    Returns:
        Dictionary with request metrics
    """
    try:
        if not Path(log_path).exists():
            return {}

        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        request_count = 0
        compile_requests = 0

        # Nginx log format: IP - - [timestamp] "METHOD /path HTTP/x.x" status size
        # Example: 127.0.0.1 - - [24/Jan/2026:10:30:45 +0000] "POST /compile HTTP/1.1" 200 1234
        log_pattern = r'\[([\d\/\w: +]+)\]\s+"(\w+)\s+([^"]+)\s+HTTP'

        with open(log_path, "r") as f:
            for line in f:
                match = re.search(log_pattern, line)
                if match:
                    timestamp_str, method, path = match.groups()

                    # Parse timestamp
                    try:
                        # Format: 24/Jan/2026:10:30:45 +0000
                        timestamp = datetime.strptime(
                            timestamp_str.split()[0], "%d/%b/%Y:%H:%M:%S"
                        )

                        if timestamp >= cutoff_time:
                            request_count += 1
                            if "/compile" in path:
                                compile_requests += 1
                    except ValueError:
                        continue

        return {
            "requests_per_minute": request_count,
            "compile_requests_per_minute": compile_requests,
            "total_requests_per_minute": request_count,
            "log_analyzed_minutes": minutes,
        }

    except Exception as e:
        print(f"Warning: Could not parse nginx log: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(description="Aggregate Facto backend statistics")
    parser.add_argument(
        "--nginx-config",
        default="/etc/nginx/sites-available/facto.spokenrobot.com",
        help="Path to nginx config file (default: /etc/nginx/sites-available/facto.spokenrobot.com)",
    )
    parser.add_argument(
        "--output",
        default="./aggregated_stats.yaml",
        help="Path to output aggregated stats file (default: ./aggregated_stats.yaml)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Update interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--stats-port",
        type=int,
        default=4000,
        help="Port where backend stats servers are running (default: 4000)",
    )
    parser.add_argument(
        "--nginx-log",
        default="/var/log/nginx/access.log",
        help="Path to nginx access log (default: /var/log/nginx/access.log)",
    )

    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Stats Aggregator Starting")
    print(f"  Nginx config: {args.nginx_config}")
    print(f"  Output file: {args.output}")
    print(f"  Update interval: {args.interval}s")
    print(f"  Stats port: {args.stats_port}")
    print(f"  Nginx log: {args.nginx_log}")
    print()

    iteration = 0

    while True:
        iteration += 1
        start_time = time.time()

        # Parse nginx config to get backend servers
        servers = parse_nginx_config(args.nginx_config)

        if not servers:
            print(f"[{iteration}] No servers found in nginx config")
            time.sleep(args.interval)
            continue

        print(
            f"[{iteration}] Found {len(servers)} backend servers: {', '.join(servers)}"
        )

        # Fetch stats from each server
        stats_list = []
        for server in servers:
            stats = fetch_stats_from_server(server, args.stats_port)
            stats_list.append(stats)

        # Aggregate statistics
        aggregated = aggregate_stats(stats_list)

        # Add nginx request metrics
        nginx_metrics = parse_nginx_access_log(args.nginx_log, minutes=1)
        if nginx_metrics:
            aggregated["nginx_metrics"] = nginx_metrics

        # Write to output file
        try:
            with open(output_path, "w") as f:
                yaml.dump(aggregated, f, default_flow_style=False, sort_keys=False)

            print(f"[{iteration}] Aggregated stats written to {output_path}")
            print(
                f"         Total compilations: {aggregated.get('total_compilations', 0)}"
            )
            print(f"         Success rate: {aggregated.get('success_rate', 0)}%")
            print(
                f"         Avg time: {aggregated.get('avg_compilation_time_seconds', 0)}s"
            )
            if nginx_metrics:
                print(
                    f"         Requests/min: {nginx_metrics.get('requests_per_minute', 0)}"
                )
        except Exception as e:
            print(f"[{iteration}] Error writing stats: {e}")

        # Sleep for remaining interval time
        elapsed = time.time() - start_time
        sleep_time = max(0, args.interval - elapsed)

        if sleep_time > 0:
            time.sleep(sleep_time)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down stats aggregator...")
