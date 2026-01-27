#!/usr/bin/env python3
"""
Telegram monitoring bot for Facto backend statistics.

Features:
- Request aggregated stats via /stats command
- Automatic alerts for high traffic
- Automatic alerts for anomalies (sudden jumps)
- Configure alert thresholds

Setup:
1. Create a Telegram bot via @BotFather and get the token
2. Set TELEGRAM_BOT_TOKEN environment variable
3. Set TELEGRAM_CHAT_ID environment variable (your chat ID)
4. Run: python3 telegram_bot.py --stats-file /path/to/aggregated_stats.yaml

To get your chat ID:
- Message your bot
- Visit: https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
- Look for "chat":{"id": YOUR_CHAT_ID}

Usage:
    export TELEGRAM_BOT_TOKEN="your_bot_token"
    export TELEGRAM_CHAT_ID="your_chat_id"
    python3 telegram_bot.py --stats-file ./aggregated_stats.yaml
"""

import argparse
import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import yaml


from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TELEGRAM_AVAILABLE = True


class StatsMonitor:
    """Monitor stats file and detect anomalies."""

    def __init__(self, stats_file: str):
        self.stats_file = Path(stats_file)
        self.previous_stats: Optional[Dict[str, Any]] = None
        self.last_alert_time: Dict[str, float] = {}

        # Alert thresholds
        self.thresholds = {
            "requests_per_minute": 150,  # Alert if > 150 req/min
            "compilation_jump": 50,  # Alert if compilations jump by > 50
            "success_rate_drop": 20,  # Alert if success rate drops > 20%
            "avg_time_spike": 10,  # Alert if avg time increases > 10s            'queue_length': 10,  # Alert if queue length > 10
            "avg_total_time_spike": 15,  # Alert if total time > 15s            "alert_cooldown": 300,  # Min seconds between same alert type
            "queue_length": 10,  # Alert if queue length > 10
            "alert_cooldown": 300,  # Min seconds between same alert type
        }

    def load_stats(self) -> Optional[Dict[str, Any]]:
        """Load current stats from file."""
        try:
            if not self.stats_file.exists():
                return None

            with open(self.stats_file, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"Error loading stats: {e}")
            return None

    def check_alerts(self, stats: Dict[str, Any]) -> list[str]:
        """
        Check for conditions that should trigger alerts.

        Returns list of alert messages.
        """
        alerts = []
        current_time = time.time()

        # Check high request rate
        nginx_metrics = stats.get("nginx_metrics", {})
        req_per_min = nginx_metrics.get("requests_per_minute", 0)

        if req_per_min > self.thresholds["requests_per_minute"]:
            alert_type = "high_traffic"
            if self._should_alert(alert_type, current_time):
                alerts.append(
                    f"⚠️ HIGH TRAFFIC ALERT!\n"
                    f"Requests per minute: {req_per_min}\n"
                    f"Threshold: {self.thresholds['requests_per_minute']}"
                )
                self.last_alert_time[alert_type] = current_time

        # Check for sudden compilation jump
        if self.previous_stats:
            prev_compilations = self.previous_stats.get("total_compilations", 0)
            curr_compilations = stats.get("total_compilations", 0)
            jump = curr_compilations - prev_compilations

            if jump > self.thresholds["compilation_jump"]:
                alert_type = "compilation_jump"
                if self._should_alert(alert_type, current_time):
                    alerts.append(
                        f"📈 COMPILATION SPIKE DETECTED!\n"
                        f"Sudden increase: {jump} compilations\n"
                        f"Total: {prev_compilations} → {curr_compilations}"
                    )
                    self.last_alert_time[alert_type] = current_time

            # Check for success rate drop
            prev_rate = self.previous_stats.get("success_rate", 100)
            curr_rate = stats.get("success_rate", 100)
            rate_drop = prev_rate - curr_rate

            if rate_drop > self.thresholds["success_rate_drop"] and curr_rate < 80:
                alert_type = "success_rate_drop"
                if self._should_alert(alert_type, current_time):
                    alerts.append(
                        f"⚠️ SUCCESS RATE DROP!\n"
                        f"Success rate: {prev_rate:.1f}% → {curr_rate:.1f}%\n"
                        f"Drop: {rate_drop:.1f}%"
                    )
                    self.last_alert_time[alert_type] = current_time

            # Check for avg time spike
            prev_avg = self.previous_stats.get("avg_compilation_time_seconds", 0)
            curr_avg = stats.get("avg_compilation_time_seconds", 0)
            time_increase = curr_avg - prev_avg

            if time_increase > self.thresholds["avg_time_spike"]:
                alert_type = "avg_time_spike"
                if self._should_alert(alert_type, current_time):
                    alerts.append(
                        f"⏱️ COMPILATION TIME SPIKE!\n"
                        f"Avg time: {prev_avg:.2f}s → {curr_avg:.2f}s\n"
                        f"Increase: {time_increase:.2f}s"
                    )
                    self.last_alert_time[alert_type] = current_time

            # Check for total request time spike
            prev_total = self.previous_stats.get("avg_total_request_seconds", 0)
            curr_total = stats.get("avg_total_request_seconds", 0)
            total_increase = curr_total - prev_total

            if total_increase > self.thresholds["avg_total_time_spike"]:
                alert_type = "avg_total_time_spike"
                if self._should_alert(alert_type, current_time):
                    alerts.append(
                        f"⏱️ TOTAL REQUEST TIME SPIKE!\n"
                        f"Avg total time: {prev_total:.2f}s → {curr_total:.2f}s\n"
                        f"Increase: {total_increase:.2f}s\n"
                        f"(queue wait + compilation)"
                    )
                    self.last_alert_time[alert_type] = current_time

        # Check queue length
        queue_length = stats.get("current_queue_length", 0)
        if queue_length > self.thresholds["queue_length"]:
            alert_type = "high_queue_length"
            if self._should_alert(alert_type, current_time):
                alerts.append(
                    f"📊 HIGH QUEUE LENGTH!\n"
                    f"Current queue: {queue_length} requests\n"
                    f"Threshold: {self.thresholds['queue_length']}\n"
                    f"System is under heavy load!"
                )
                self.last_alert_time[alert_type] = current_time

        return alerts

    def _should_alert(self, alert_type: str, current_time: float) -> bool:
        """Check if enough time has passed since last alert of this type."""
        last_alert = self.last_alert_time.get(alert_type, 0)
        return (current_time - last_alert) >= self.thresholds["alert_cooldown"]

    def format_stats(self, stats: Dict[str, Any]) -> str:
        """Format stats for display."""
        if not stats:
            return "No stats available"

        if "error" in stats:
            return f"Error: {stats['error']}"

        lines = [
            "📊 *Facto Backend Statistics*",
            "",
            f"🖥️ *Servers*",
            f"  Active: {stats.get('server_count', 0)} / {stats.get('servers_queried', 0)} responding",
            "",
            f"📈 *Compilations*",
            f"  Total: {stats.get('total_compilations', 0)}",
            f"  Successful: {stats.get('successful_compilations', 0)}",
            f"  Failed: {stats.get('failed_compilations', 0)}",
            f"  Success Rate: {stats.get('success_rate', 0):.1f}%",
            "",
            f"⏱️ *Compilation Times*",
            f"  Average: {stats.get('avg_compilation_time_seconds', 0):.2f}s",
            f"  Median: {stats.get('median_compilation_time_seconds', 0):.2f}s",
            f"  Min: {stats.get('min_compilation_time_seconds', 0):.2f}s",
            f"  Max: {stats.get('max_compilation_time_seconds', 0):.2f}s",
            "",
            f"� *Queue Metrics*",
            f"  Current queue: {stats.get('current_queue_length', 0)} requests",
            f"  Max queue seen: {stats.get('max_queue_length_seen', 0)}",
            f"  Total queued: {stats.get('total_queued_requests', 0)}",
            f"  Avg wait time: {stats.get('avg_queue_wait_seconds', 0):.2f}s",
            f"  Max wait time: {stats.get('max_queue_wait_seconds', 0):.2f}s",
            "",
            f"🎯 *Total Request Times* (queue + compile)",
            f"  Average: {stats.get('avg_total_request_seconds', 0):.2f}s",
            f"  Median: {stats.get('median_total_request_seconds', 0):.2f}s",
            f"  Min: {stats.get('min_total_request_seconds', 0):.2f}s",
            f"  Max: {stats.get('max_total_request_seconds', 0):.2f}s",
            "",
            f"�👥 *Sessions*",
            f"  Unique: {stats.get('unique_sessions', 0)}",
        ]

        # Add nginx metrics if available
        nginx_metrics = stats.get("nginx_metrics", {})
        if nginx_metrics:
            lines.extend(
                [
                    "",
                    f"🌐 *Nginx Metrics*",
                    f"  Requests/min: {nginx_metrics.get('requests_per_minute', 0)}",
                    f"  Compile requests/min: {nginx_metrics.get('compile_requests_per_minute', 0)}",
                ]
            )

        # Add timestamps
        if "aggregated_at" in stats:
            lines.extend(
                ["", f"🕐 Updated: {stats['aggregated_at'][:19].replace('T', ' ')}"]
            )

        return "\n".join(lines)


# Global monitor instance
monitor: Optional[StatsMonitor] = None


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command."""
    if monitor is None:
        await update.message.reply_text("Monitor not initialized")
        return

    stats = monitor.load_stats()
    if stats is None:
        await update.message.reply_text("Could not load stats file")
        return

    message = monitor.format_stats(stats)
    await update.message.reply_text(message, parse_mode="Markdown")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "👋 Welcome to Facto Stats Monitor!\n\n"
        "Commands:\n"
        "/stats - Get current statistics\n"
        "/help - Show this help message\n\n"
        "I'll also send you automatic alerts for:\n"
        "• High traffic\n"
        "• Sudden compilation spikes\n"
        "• Success rate drops\n"
        "• Compilation time increases"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await start_command(update, context)


async def monitoring_loop(app: Application, chat_id: str, check_interval: int = 30):
    """Background monitoring loop that checks for alerts."""
    print(f"Starting monitoring loop (checking every {check_interval}s)...")

    while True:
        try:
            stats = monitor.load_stats()
            if stats:
                alerts = monitor.check_alerts(stats)

                for alert in alerts:
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id, text=alert, parse_mode="Markdown"
                        )
                        print(f"Alert sent: {alert[:50]}...")
                    except Exception as e:
                        print(f"Error sending alert: {e}")

                # Update previous stats for next comparison
                monitor.previous_stats = stats

        except Exception as e:
            print(f"Error in monitoring loop: {e}")

        await asyncio.sleep(check_interval)


def main():
    if not TELEGRAM_AVAILABLE:
        print("ERROR: python-telegram-bot not installed")
        print("Install with: pip install python-telegram-bot")
        return

    parser = argparse.ArgumentParser(
        description="Telegram monitoring bot for Facto stats"
    )
    parser.add_argument(
        "--stats-file",
        default="./aggregated_stats.yaml",
        help="Path to aggregated stats file (default: ./aggregated_stats.yaml)",
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=30,
        help="How often to check for alerts in seconds (default: 30)",
    )
    parser.add_argument(
        "--token", help="Telegram bot token (or set TELEGRAM_BOT_TOKEN env var)"
    )
    parser.add_argument(
        "--chat-id", help="Telegram chat ID (or set TELEGRAM_CHAT_ID env var)"
    )

    args = parser.parse_args()

    load_dotenv()
    # Get credentials
    token = args.token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = args.chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    if not token:
        print("ERROR: Telegram bot token not provided")
        print("Set TELEGRAM_BOT_TOKEN environment variable or use --token")
        return

    if not chat_id:
        print("ERROR: Telegram chat ID not provided")
        print("Set TELEGRAM_CHAT_ID environment variable or use --chat-id")
        print("\nTo get your chat ID:")
        print("1. Message your bot")
        print(f"2. Visit: https://api.telegram.org/bot{token}/getUpdates")
        print("3. Look for 'chat':{'id': YOUR_CHAT_ID}")
        return

    # Initialize monitor
    global monitor
    monitor = StatsMonitor(args.stats_file)

    print(f"Facto Telegram Bot Starting")
    print(f"  Stats file: {args.stats_file}")
    print(f"  Check interval: {args.check_interval}s")
    print(f"  Chat ID: {chat_id}")
    print()
    print("Bot is running. Send /start to begin.")
    print()

    # Create application
    app = Application.builder().token(token).build()

    # Add command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))

    # Start monitoring loop
    async def post_init(application: Application):
        """Start monitoring after bot initialization."""
        asyncio.create_task(monitoring_loop(application, chat_id, args.check_interval))

    app.post_init = post_init

    # Run bot
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down bot...")
