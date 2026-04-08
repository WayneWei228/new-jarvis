"""
Brainiest Mind - Main Entry Point

INPUT (camera + audio + browser) → LLM Analysis → 用户状态描述

Usage:
    cd brainiest-mind
    source .venv/bin/activate
    python main.py

    # Analyze every 30s (default):
    python main.py

    # Faster analysis cycle:
    python main.py --analysis-interval 15

    # No camera:
    python main.py --no-camera
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path

# Load .env from project root
_ENV_PATH = Path(__file__).resolve().parent / ".env"
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from input import InputCollector
from analysis import LLMAnalysis
from brain import Brain
from executor import Executor, Notifier, WebUI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


async def print_events_loop(collector: InputCollector, interval: float = 5.0):
    """Periodically print a summary of recent events."""
    last_check = time.time()

    while True:
        await asyncio.sleep(interval)
        now = time.time()
        events = collector.get_events(since=last_check)
        last_check = now

        if not events:
            continue

        logger.info(f"--- {len(events)} new events ---")
        for e in events:
            if e.source == "chrome_history":
                title = e.data.get("title", "?")[:50]
                url = e.data.get("url", "?")[:60]
                logger.info(f"  [BROWSER] {title} — {url}")
            elif e.source == "microphone":
                text = e.data.get("text", "")[:80]
                logger.info(f"  [AUDIO] {text}")
            elif e.source == "camera":
                logger.info(f"  [CAMERA] frame captured")
            elif e.source == "desktop":
                logger.info(f"  [DESKTOP] screenshot captured")
            elif e.source == "executor":
                action = e.data.get("action", "?")
                status = e.data.get("status", "?")
                logger.info(f"  [FEEDBACK] {action} → {status}")


async def main(args):
    logger.info("=" * 50)
    logger.info("  Brainiest Mind")
    logger.info("  INPUT → LLM Analysis → 状态描述")
    logger.info("=" * 50)
    logger.info(f"  Camera:   {'ON' if args.camera else 'OFF'}")
    logger.info(f"  Desktop:  {'ON' if args.desktop else 'OFF'}")
    logger.info(f"  Audio:    {'ON' if args.audio else 'OFF'}")
    logger.info(f"  Browser:  {'ON' if args.browser else 'OFF'}")
    logger.info(f"  Analysis: every {args.analysis_interval}s")
    logger.info(f"  Brain:    every {args.brain_interval}s")
    logger.info("=" * 50)

    # 1. Notifier (shared event bus for UI)
    notifier = Notifier()

    # 2. Input Collector
    collector = InputCollector(
        enable_camera=args.camera,
        enable_desktop=args.desktop,
        enable_audio=args.audio,
        enable_browser=args.browser,
        camera_interval=args.camera_interval,
        desktop_interval=args.desktop_interval,
        browser_poll_interval=args.browser_interval,
        audio_language=args.language,
    )

    # 3. LLM Analysis
    analysis = LLMAnalysis(
        collector=collector,
        interval_sec=args.analysis_interval,
        max_frames=2,
        notifier=notifier,
    )

    # 4. Brain — continuous reasoning
    brain = Brain(
        interval_sec=args.brain_interval,
        notifier=notifier,
    )

    # 5. Executor + Web UI
    web_ui = WebUI(notifier, port=7888)
    executor = Executor(notifier=notifier)

    # Handle Ctrl+C
    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("\nShutting down...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    # Start everything
    await web_ui.start()
    await collector.start()
    tasks = [
        asyncio.create_task(print_events_loop(collector, interval=args.print_interval)),
        asyncio.create_task(analysis.start()),
        asyncio.create_task(brain.start()),
        asyncio.create_task(executor.start()),
    ]

    # Wait until Ctrl+C
    await stop_event.wait()

    # Cleanup
    for t in tasks:
        t.cancel()
    await executor.stop()
    await brain.stop()
    await analysis.stop()
    await collector.stop()
    await web_ui.stop()
    logger.info("Done.")


def parse_args():
    p = argparse.ArgumentParser(description="Brainiest Mind")
    p.add_argument("--no-camera", dest="camera", action="store_false", default=True)
    p.add_argument("--no-desktop", dest="desktop", action="store_false", default=True)
    p.add_argument("--no-audio", dest="audio", action="store_false", default=True)
    p.add_argument("--no-browser", dest="browser", action="store_false", default=True)
    p.add_argument("--camera-interval", type=float, default=5.0,
                   help="Seconds between camera captures (default: 5)")
    p.add_argument("--desktop-interval", type=float, default=10.0,
                   help="Seconds between desktop screenshots (default: 10)")
    p.add_argument("--browser-interval", type=float, default=10.0,
                   help="Seconds between browser history polls (default: 10)")
    p.add_argument("--analysis-interval", type=float, default=30.0,
                   help="Seconds between LLM analysis rounds (default: 30)")
    p.add_argument("--brain-interval", type=float, default=35.0,
                   help="Seconds between Brain reasoning rounds (default: 35)")
    p.add_argument("--print-interval", type=float, default=5.0,
                   help="Seconds between event summary prints (default: 5)")
    p.add_argument("--language", default="zh")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
