"""
Native macOS Overlay — 原生浮动面板，贴在活动窗口旁边。

Architecture:
- overlay_window.py: 独立进程，运行 AppKit 事件循环，显示浮动面板
- 本模块通过 subprocess 启动它，通过 stdin pipe 发送 JSON 命令
- 命令: {"action": "show", ...} / {"action": "close_all"} / {"action": "quit"}
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class NativeOverlay:
    """
    Controls the native macOS overlay from the async executor.
    Spawns overlay_window.py as a separate subprocess.
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._script = Path(__file__).parent / "overlay_window.py"

    def start(self):
        """Start the overlay window process."""
        self._proc = subprocess.Popen(
            [sys.executable, str(self._script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info("Native overlay process started")

    def show_card(
        self,
        title: str,
        body: str,
        card_type: str = "result",
        action: str = "",
        confidence: float = 0,
        timeout: int = 30,
    ):
        """Show a floating card next to the active window."""
        self._send({
            "action": "show",
            "type": card_type,
            "title": title,
            "body": body,
            "action_label": action,
            "confidence": confidence,
            "timeout": timeout,
        })

    def close_all(self):
        self._send({"action": "close_all"})

    def stop(self):
        """Stop the overlay process."""
        self._send({"action": "quit"})
        if self._proc:
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        logger.info("Native overlay stopped")

    def _send(self, cmd: dict):
        """Send a JSON command to the overlay process via stdin."""
        if not self._proc or self._proc.poll() is not None:
            logger.warning("Overlay process not running")
            return
        try:
            line = json.dumps(cmd, ensure_ascii=False) + "\n"
            self._proc.stdin.write(line.encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.warning(f"Cannot send to overlay: {e}")
