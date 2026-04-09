"""
Jarvis — Proactive AI Assistant

Two modes:
  --streaming  : OpenAI Realtime API (gpt-4o) — 持续感知，原生音频理解
  (default)    : Haiku 3s tick — 截屏+ASR 快照式观察

Usage:
    python main.py                # Haiku tick mode
    python main.py --streaming    # Realtime streaming mode
    python main.py --no-camera
"""

from __future__ import annotations

import argparse
import atexit
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
from executor import NativeOverlay
from ws_bridge import ThinkingBridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


async def main(args):
    mode = "STREAMING" if args.streaming else "TICK"

    logger.info("=" * 50)
    logger.info("  Jarvis — Proactive AI Assistant")
    logger.info(f"  Mode: {mode}")
    logger.info("=" * 50)
    logger.info(f"  Camera:  {'ON' if args.camera else 'OFF (Web UI uses camera)'}")
    logger.info(f"  Desktop: {'ON' if args.desktop else 'OFF'}")
    if args.streaming:
        logger.info(f"  Audio:   STREAMING (native, 24kHz)")
        logger.info(f"  Vision:  every {args.vision_interval}s")
    else:
        logger.info(f"  Audio:   {'ON' if args.audio else 'OFF'} (ASR)")
        logger.info(f"  Tick:    every {args.periodic}s")
    logger.info(f"  Browser: {'ON' if args.browser else 'OFF'}")
    logger.info("=" * 50)

    # 1. Native Overlay + WebSocket Bridge
    overlay = NativeOverlay()
    overlay.start()

    bridge = ThinkingBridge(port=8765)
    await bridge.start()
    overlay.set_ws_bridge(bridge)

    # 2. Input Collector
    # In streaming mode, disable audio (StreamingReactor handles audio directly)
    collector = InputCollector(
        enable_camera=args.camera,
        enable_desktop=args.desktop,
        enable_audio=False if args.streaming else args.audio,
        enable_browser=args.browser,
        camera_interval=args.camera_interval,
        desktop_interval=args.desktop_interval,
        browser_poll_interval=args.browser_interval,
        audio_language=args.language,
        audio_energy_threshold=args.energy_threshold,
    )

    # 3. Reactor
    if args.streaming:
        from streaming_reactor import StreamingReactor
        reactor = StreamingReactor(
            collector=collector,
            overlay=overlay,
            vision_interval=args.vision_interval,
        )
    else:
        from reactor import Reactor
        reactor = Reactor(
            collector=collector,
            overlay=overlay,
            tick_interval=args.periodic,
            profile=args.profile,
        )

    # Ensure overlay is killed no matter how we exit
    atexit.register(overlay.stop)

    # Handle Ctrl+C / SIGTERM
    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("\nShutting down...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    # Handle Ctrl+Z (SIGTSTP) — clean up before suspending
    def handle_tstp():
        logger.info("\nSuspending — cleaning up overlay...")
        overlay.stop()
        atexit.unregister(overlay.stop)
        # Re-raise SIGTSTP with default handler to actually suspend
        signal.signal(signal.SIGTSTP, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTSTP)

    loop.add_signal_handler(signal.SIGTSTP, handle_tstp)

    # Start
    await collector.start()
    reactor_task = asyncio.create_task(reactor.start())

    # Wait until Ctrl+C
    await stop_event.wait()

    # Cleanup
    reactor_task.cancel()
    await reactor.stop()
    await collector.stop()
    await bridge.stop()
    overlay.stop()
    atexit.unregister(overlay.stop)
    logger.info("Done.")


def parse_args():
    p = argparse.ArgumentParser(description="Jarvis — Proactive AI Assistant")

    # Mode & Profile
    p.add_argument("--streaming", action="store_true", default=False,
                   help="Use OpenAI Realtime API for continuous streaming perception")
    p.add_argument("--profile", type=str, default="",
                   help="User profile to load from profiles/<name>.json (optional)")

    # Input toggles
    p.add_argument("--no-camera", dest="camera", action="store_false", default=True)
    p.add_argument("--no-desktop", dest="desktop", action="store_false", default=True)
    p.add_argument("--no-audio", dest="audio", action="store_false", default=True)
    p.add_argument("--no-browser", dest="browser", action="store_false", default=True)

    # Intervals
    p.add_argument("--camera-interval", type=float, default=3.0,
                   help="Camera capture interval (default: 3s)")
    p.add_argument("--desktop-interval", type=float, default=5.0,
                   help="Desktop screenshot interval (default: 5s)")
    p.add_argument("--browser-interval", type=float, default=5.0,
                   help="Browser history poll interval (default: 5s)")
    p.add_argument("--periodic", type=float, default=3.0,
                   help="Tick interval for Haiku mode (default: 3s)")
    p.add_argument("--vision-interval", type=float, default=5.0,
                   help="Vision update interval for streaming mode (default: 5s)")

    # Audio
    p.add_argument("--language", default="zh")
    p.add_argument("--energy-threshold", type=float, default=0.02,
                   help="Mic energy gate for Haiku mode (default: 0.02)")

    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
