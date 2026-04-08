"""
Camera / Screen Capture input source.

Opens the system camera (or screen capture) and periodically saves frames.
Emits InputEvent with CameraFrame payload.

Usage:
    capture = ScreenCapture(interval_sec=5.0)
    await capture.start(event_queue)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from .models import CameraFrame, EventCategory, EventNature, InputEvent

logger = logging.getLogger(__name__)


class ScreenCapture:
    """Captures frames from the system camera at a configurable interval."""

    def __init__(
        self,
        interval_sec: float = 5.0,
        output_dir: str = "input/user_status/frames",
        camera_index: int = 0,
        max_frames: int = 1000,
    ):
        self.interval_sec = interval_sec
        self.output_dir = Path(output_dir)
        self.camera_index = camera_index
        self.max_frames = max_frames
        self._running = False
        self._cap = None

    async def start(self, event_queue: asyncio.Queue) -> None:
        """Start capturing frames and pushing events to the queue."""
        try:
            import cv2
        except ImportError:
            logger.error("opencv-python not installed. Run: pip install opencv-python")
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._cap = cv2.VideoCapture(self.camera_index)

        if not self._cap.isOpened():
            logger.error(f"Cannot open camera at index {self.camera_index}")
            return

        # Warm up camera (first few frames are often black)
        for _ in range(10):
            self._cap.read()

        logger.info(f"Camera opened (index={self.camera_index}), capturing every {self.interval_sec}s")
        self._running = True
        frame_count = 0

        try:
            while self._running:
                ret, frame = self._cap.read()
                if not ret:
                    logger.warning("Failed to read frame from camera, retrying...")
                    await asyncio.sleep(1.0)
                    continue

                # Save frame to disk
                ts = int(time.time() * 1000)
                filename = f"frame_{ts}.jpg"
                filepath = self.output_dir / filename
                cv2.imwrite(str(filepath), frame)

                h, w = frame.shape[:2]
                camera_data = CameraFrame(
                    image_path=str(filepath),
                    width=w,
                    height=h,
                )

                event = InputEvent(
                    source="camera",
                    category=EventCategory.PHYSIOLOGICAL,
                    nature=EventNature.CONTINUOUS,
                    event_type="frame_captured",
                    data=camera_data.model_dump(),
                )
                await event_queue.put(event)

                frame_count += 1
                logger.debug(f"Frame captured: {filepath} ({w}x{h})")

                # Cleanup old frames to prevent disk bloat
                if frame_count > self.max_frames:
                    self._cleanup_old_frames()

                await asyncio.sleep(self.interval_sec)

        except asyncio.CancelledError:
            logger.info("Camera capture cancelled")
        finally:
            self._release()

    def _cleanup_old_frames(self) -> None:
        """Remove oldest frames when exceeding max_frames."""
        frames = sorted(self.output_dir.glob("frame_*.jpg"))
        to_remove = len(frames) - self.max_frames
        if to_remove > 0:
            for f in frames[:to_remove]:
                f.unlink(missing_ok=True)
            logger.debug(f"Cleaned up {to_remove} old frames")

    def _release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("Camera released")

    async def stop(self) -> None:
        """Stop capturing."""
        self._running = False
        self._release()
