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
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class NativeOverlay:
    """
    Controls the native macOS overlay from the async executor.
    Spawns overlay_window.py as a separate subprocess.
    Reads feedback from stdout (user button clicks, auto-expire).
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._script = Path(__file__).parent / "overlay_window.py"
        self._feedback_buffer: list[dict] = []
        self._feedback_lock = threading.Lock()

    def start(self):
        """Start the overlay window process."""
        self._proc = subprocess.Popen(
            [sys.executable, str(self._script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Start stdout reader for feedback
        self._stdout_thread = threading.Thread(
            target=self._read_stdout, daemon=True
        )
        self._stdout_thread.start()
        logger.info("Native overlay process started (with feedback reader)")

    def _read_stdout(self):
        """Read feedback JSON from overlay process stdout."""
        while self._proc and self._proc.poll() is None:
            try:
                line = self._proc.stdout.readline()
                if not line:
                    break
                line = line.decode("utf-8").strip()
                if line:
                    try:
                        feedback = json.loads(line)
                        with self._feedback_lock:
                            self._feedback_buffer.append(feedback)
                        logger.debug(f"Overlay feedback: {feedback}")
                    except json.JSONDecodeError:
                        pass
            except Exception:
                break

    def get_feedback(self) -> list[dict]:
        """Get and clear pending feedback events from overlay."""
        with self._feedback_lock:
            feedback = list(self._feedback_buffer)
            self._feedback_buffer.clear()
        return feedback

    def show_card(
        self,
        title: str,
        body: str,
        card_type: str = "result",
        card_id: str = "",
        timeout: int = 30,
    ):
        """Show a floating card next to the active window."""
        self._send({
            "action": "show",
            "type": card_type,
            "title": title,
            "body": body,
            "card_id": card_id,
            "timeout": timeout,
        })

    def push_thinking(self, entries: list[dict]):
        """Push entries to the thinking log panel.

        Each entry: {"text": "...", "type": "input|reason|decision|action|feedback|separator"}
        """
        if entries:
            self._send({"action": "thinking", "entries": entries})

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
