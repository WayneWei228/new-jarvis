"""
Desktop screen capture — 定期截取用户桌面，了解用户在电脑上做什么。

Uses macOS built-in `screencapture` command (no extra deps, no permission popup).
Emits InputEvent with screenshot path.

Usage:
    capture = DesktopCapture(interval_sec=10.0)
    await capture.start(event_queue)
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path

from .models import EventCategory, EventNature, InputEvent

logger = logging.getLogger(__name__)


class DesktopCapture:
    """Captures desktop screenshots at a configurable interval."""

    def __init__(
        self,
        interval_sec: float = 10.0,
        output_dir: str = "input/user_status/screenshots",
        max_screenshots: int = 200,
    ):
        self.interval_sec = interval_sec
        self.output_dir = Path(output_dir)
        self.max_screenshots = max_screenshots
        self._running = False

    async def start(self, event_queue: asyncio.Queue) -> None:
        """Start capturing desktop screenshots."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        count = 0

        logger.info(f"Desktop capture started (every {self.interval_sec}s)")

        try:
            while self._running:
                ts = int(time.time() * 1000)
                filepath = self.output_dir / f"desktop_{ts}.jpg"

                # macOS screencapture: -x = no sound, -t jpg, -C = capture cursor
                proc = await asyncio.create_subprocess_exec(
                    "screencapture", "-x", "-t", "jpg", "-C", str(filepath),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()

                if filepath.exists() and filepath.stat().st_size > 0:
                    event = InputEvent(
                        source="desktop",
                        category=EventCategory.BEHAVIORAL,
                        nature=EventNature.CONTINUOUS,
                        event_type="desktop_captured",
                        data={
                            "image_path": str(filepath),
                            "size_kb": round(filepath.stat().st_size / 1024),
                        },
                    )
                    await event_queue.put(event)
                    count += 1
                    logger.debug(f"Desktop screenshot: {filepath.name}")

                    if count > self.max_screenshots:
                        self._cleanup_old()
                else:
                    logger.warning("screencapture failed or produced empty file")

                await asyncio.sleep(self.interval_sec)

        except asyncio.CancelledError:
            logger.info("Desktop capture cancelled")

    def _cleanup_old(self) -> None:
        """Remove oldest screenshots when exceeding limit."""
        shots = sorted(self.output_dir.glob("desktop_*.jpg"))
        to_remove = len(shots) - self.max_screenshots
        if to_remove > 0:
            for f in shots[:to_remove]:
                f.unlink(missing_ok=True)

    async def stop(self) -> None:
        self._running = False
