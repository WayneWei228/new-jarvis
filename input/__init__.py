"""
INPUT MODULE - Unified input collection orchestrator.

Starts all input sources (camera, microphone, browser, feedback),
merges their events into a single async stream, and exposes a clean
interface for the LLM Analysis module to consume.

Architecture:
    ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐
    │   Camera     │  │  Microphone  │  │  Chrome History  │  │ Feedback Receiver│
    │ (continuous) │  │ (continuous) │  │   (discrete)     │  │   (event-driven) │
    └──────┬──────┘  └──────┬───────┘  └────────┬─────────┘  └────────┬─────────┘
           │                │                    │                      │
           └────────────────┴────────────────────┴──────────────────────┘
                                       │
                                  event_queue
                                       │
                                       ▼
                              ┌─────────────────┐
                              │ InputCollector   │
                              │ get_events()     │
                              │ get_snapshot()   │
                              └─────────────────┘

Usage:
    collector = InputCollector()
    await collector.start()

    # Get recent events for LLM Analysis
    events = collector.get_events(since=time.time() - 60)

    # Get a snapshot dict suitable for LLM prompt
    snapshot = collector.get_snapshot(window_sec=60)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

from .browser_monitor import BrowserMonitor
from .desktop_capture import DesktopCapture
from .feedback_receiver import FeedbackReceiver
from .models import EventCategory, InputEvent
from .screen_capture import ScreenCapture
from .sensor_adapter import AudioInput

logger = logging.getLogger(__name__)

# Re-export models for convenience
from .models import (
    AudioSegment,
    BrowserEvent,
    CameraFrame,
    EventCategory,
    EventNature,
    FeedbackEvent,
    InputEvent,
)

__all__ = [
    "InputCollector",
    "InputEvent",
    "EventCategory",
    "EventNature",
    "CameraFrame",
    "AudioSegment",
    "BrowserEvent",
    "FeedbackEvent",
]


class InputCollector:
    """
    Orchestrates all input sources and provides a unified event stream.

    All sources push events into a shared asyncio.Queue.
    Events are stored in a bounded deque for recent history access.
    """

    def __init__(
        self,
        camera_interval: float = 5.0,
        desktop_interval: float = 10.0,
        browser_poll_interval: float = 10.0,
        audio_language: str = "zh",
        max_events: int = 5000,
        enable_camera: bool = True,
        enable_desktop: bool = True,
        enable_audio: bool = True,
        enable_browser: bool = True,
    ):
        self.max_events = max_events
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._events: deque[InputEvent] = deque(maxlen=max_events)
        self._tasks: list[asyncio.Task] = []

        # Input sources
        self._camera = ScreenCapture(interval_sec=camera_interval) if enable_camera else None
        self._desktop = DesktopCapture(interval_sec=desktop_interval) if enable_desktop else None
        self._audio = AudioInput(language=audio_language) if enable_audio else None
        self._browser = BrowserMonitor(poll_interval=browser_poll_interval) if enable_browser else None
        self._feedback = FeedbackReceiver()

        self._running = False

    async def start(self) -> None:
        """Start all input sources and the event consumer."""
        self._running = True
        logger.info("InputCollector starting...")

        # Start the event consumer
        self._tasks.append(
            asyncio.create_task(self._consume_events(), name="event_consumer")
        )

        # Start each enabled input source
        if self._camera:
            self._tasks.append(
                asyncio.create_task(
                    self._camera.start(self._event_queue), name="camera"
                )
            )
            logger.info("  [+] Camera capture enabled")

        if self._desktop:
            self._tasks.append(
                asyncio.create_task(
                    self._desktop.start(self._event_queue), name="desktop"
                )
            )
            logger.info("  [+] Desktop capture enabled")

        if self._audio:
            self._tasks.append(
                asyncio.create_task(
                    self._audio.start(self._event_queue), name="audio"
                )
            )
            logger.info("  [+] Audio input enabled")

        if self._browser:
            self._tasks.append(
                asyncio.create_task(
                    self._browser.start(self._event_queue), name="browser"
                )
            )
            logger.info("  [+] Browser monitor enabled")

        # Feedback receiver is always on
        self._tasks.append(
            asyncio.create_task(
                self._feedback.start(self._event_queue), name="feedback"
            )
        )
        logger.info("  [+] Feedback receiver enabled")
        logger.info(f"InputCollector started with {len(self._tasks)} tasks")

    async def _consume_events(self) -> None:
        """Drain the event queue into the history deque."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                self._events.append(event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def get_events(
        self,
        since: float | None = None,
        category: EventCategory | None = None,
        limit: int = 100,
    ) -> list[InputEvent]:
        """
        Get recent events, optionally filtered by time and category.

        Args:
            since: Unix timestamp, only return events after this time
            category: Filter by event category
            limit: Max number of events to return
        """
        results = []
        for event in reversed(self._events):
            if since and event.timestamp < since:
                break
            if category and event.category != category:
                continue
            results.append(event)
            if len(results) >= limit:
                break
        return list(reversed(results))

    def get_snapshot(self, window_sec: float = 60.0) -> dict[str, Any]:
        """
        Get a structured snapshot of recent input data,
        suitable for passing to the LLM Analysis module.

        Returns dict with sections for each input category.
        """
        since = time.time() - window_sec
        events = self.get_events(since=since, limit=500)

        snapshot: dict[str, Any] = {
            "timestamp": time.time(),
            "window_sec": window_sec,
            "total_events": len(events),
            "physiological": {
                "camera_frames": [],
                "audio_transcriptions": [],
            },
            "behavioral": {
                "desktop_screenshots": [],
                "browser_visits": [],
            },
            "feedback": {
                "execution_results": [],
            },
        }

        for event in events:
            if event.source == "camera":
                snapshot["physiological"]["camera_frames"].append({
                    "timestamp": event.timestamp,
                    "image_path": event.data.get("image_path"),
                    "description": event.data.get("description"),
                })
            elif event.source == "microphone":
                snapshot["physiological"]["audio_transcriptions"].append({
                    "timestamp": event.timestamp,
                    "text": event.data.get("text"),
                    "duration_sec": event.data.get("duration_sec"),
                    "language": event.data.get("language"),
                })
            elif event.source == "desktop":
                snapshot["behavioral"]["desktop_screenshots"].append({
                    "timestamp": event.timestamp,
                    "image_path": event.data.get("image_path"),
                })
            elif event.source == "chrome_history":
                snapshot["behavioral"]["browser_visits"].append({
                    "timestamp": event.timestamp,
                    "url": event.data.get("url"),
                    "title": event.data.get("title"),
                    "action": event.data.get("action"),
                    "duration_sec": event.data.get("visit_duration_sec"),
                })
            elif event.source == "executor":
                snapshot["feedback"]["execution_results"].append({
                    "timestamp": event.timestamp,
                    "decision_id": event.data.get("decision_id"),
                    "action": event.data.get("action"),
                    "status": event.data.get("status"),
                })

        return snapshot

    @property
    def feedback_receiver(self) -> FeedbackReceiver:
        """Access the feedback receiver to push feedback from Executor."""
        return self._feedback

    @property
    def event_count(self) -> int:
        return len(self._events)

    async def stop(self) -> None:
        """Stop all input sources and clean up."""
        logger.info("InputCollector stopping...")
        self._running = False

        # Stop individual sources
        if self._camera:
            await self._camera.stop()
        if self._desktop:
            await self._desktop.stop()
        if self._audio:
            await self._audio.stop()
        if self._browser:
            await self._browser.stop()
        await self._feedback.stop()

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("InputCollector stopped")
