"""
Notifier — 实时通知用户 AI 在做什么。

Two channels:
1. macOS toast notification (osascript) — 快速提醒
2. SSE event bus — 推送到 Web Overlay 实时显示
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)


class Notifier:
    """Manages notification channels: macOS toast + SSE event bus."""

    def __init__(self):
        self._sse_clients: list[asyncio.Queue] = []

    # ── SSE Event Bus ──────────────────────────────────────

    def add_sse_client(self) -> asyncio.Queue:
        """Register a new SSE client, returns its event queue."""
        q: asyncio.Queue = asyncio.Queue()
        self._sse_clients.append(q)
        return q

    def remove_sse_client(self, q: asyncio.Queue) -> None:
        if q in self._sse_clients:
            self._sse_clients.remove(q)

    async def push_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Push an event to all SSE clients + optional macOS toast."""
        payload = {
            "type": event_type,
            "timestamp": time.time(),
            **data,
        }

        # Push to all SSE clients
        for q in self._sse_clients:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

        # macOS toast for important events
        if event_type in ("brain_thinking", "execution_complete"):
            title = data.get("title", "Brainiest Mind")
            message = data.get("message", "")[:100]
            self._macos_notify(title, message)

    @staticmethod
    def _macos_notify(title: str, message: str) -> None:
        """Send a macOS notification center toast."""
        try:
            script = (
                f'display notification "{message}" '
                f'with title "{title}" '
                f'sound name "Glass"'
            )
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.debug(f"macOS notify failed: {e}")
