"""
Jarvis — Proactive AI Assistant

Event-driven architecture:
  INPUT (camera + desktop + audio + browser)
    → Reactor (single LLM call: perceive + think + act)
      → Native Overlay (floating macOS panel)

Two response modes:
  - IMMEDIATE: user speaks → react in 3-5s
  - PERIODIC: background observation every 10s

Usage:
    source .venv/bin/activate
    python main.py
    python main.py --no-camera
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
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
from reactor import Reactor
from executor import NativeOverlay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


async def main(args):
    logger.info("=" * 50)
    logger.info("  Jarvis — Proactive AI Assistant")
    logger.info("  INPUT → Reactor → Overlay")
    logger.info("=" * 50)
    logger.info(f"  Camera:   {'ON' if args.camera else 'OFF'}")
    logger.info(f"  Desktop:  {'ON' if args.desktop else 'OFF'}")
    logger.info(f"  Audio:    {'ON' if args.audio else 'OFF'}")
    logger.info(f"  Browser:  {'ON' if args.browser else 'OFF'}")
    logger.info(f"  Periodic: every {args.periodic}s")
    logger.info("=" * 50)

    # 1. Native Overlay
    overlay = NativeOverlay()
    overlay.start()

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

    # 3. Reactor (replaces Analysis + Brain + Executor)
    reactor = Reactor(
        collector=collector,
        overlay=overlay,
        periodic_interval=args.periodic,
    )

    # Handle Ctrl+C
    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("\nShutting down...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    # Start
    await collector.start()
    reactor_task = asyncio.create_task(reactor.start())

    # Wait until Ctrl+C
    await stop_event.wait()

    # Cleanup
    reactor_task.cancel()
    await reactor.stop()
    await collector.stop()
    overlay.stop()
    logger.info("Done.")


def parse_args():
    p = argparse.ArgumentParser(description="Jarvis — Proactive AI Assistant")
    p.add_argument("--no-camera", dest="camera", action="store_false", default=True)
    p.add_argument("--no-desktop", dest="desktop", action="store_false", default=True)
    p.add_argument("--no-audio", dest="audio", action="store_false", default=True)
    p.add_argument("--no-browser", dest="browser", action="store_false", default=True)
    p.add_argument("--camera-interval", type=float, default=3.0,
                   help="Seconds between camera captures (default: 3)")
    p.add_argument("--desktop-interval", type=float, default=5.0,
                   help="Seconds between desktop screenshots (default: 5)")
    p.add_argument("--browser-interval", type=float, default=5.0,
                   help="Seconds between browser history polls (default: 5)")
    p.add_argument("--periodic", type=float, default=10.0,
                   help="Seconds between periodic background reactions (default: 10)")
    p.add_argument("--language", default="zh")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
