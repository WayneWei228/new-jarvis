"""
Memory Store — 持久化存储，给 Brain 提供跨轮次的上下文。

Stores:
- decisions.jsonl  — Brain 做过的决策
- results.jsonl    — Executor 执行结果
- feedback.jsonl   — 用户反馈
- preferences.json — 学到的用户偏好

Retention policy:
- Hot (1h): full detail
- Warm (24h): summarized
- Cold (older): key learnings only
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MemoryStore:
    """Read/write interface for the persistent memory store."""

    def __init__(self, memory_dir: str = "memory"):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self._decisions_path = self.memory_dir / "decisions.jsonl"
        self._results_path = self.memory_dir / "results.jsonl"
        self._feedback_path = self.memory_dir / "feedback.jsonl"
        self._preferences_path = self.memory_dir / "preferences.json"

        # Initialize files if they don't exist
        for p in [self._decisions_path, self._results_path, self._feedback_path]:
            if not p.exists():
                p.touch()

        if not self._preferences_path.exists():
            self._preferences_path.write_text("{}", encoding="utf-8")

    # ── Write ──────────────────────────────────────────────

    def save_decision(self, decision: dict[str, Any]) -> None:
        """Append a decision to the history."""
        decision["_saved_at"] = time.time()
        self._append_jsonl(self._decisions_path, decision)
        logger.debug(f"Saved decision: {decision.get('action', '?')}")

    def save_result(self, result: dict[str, Any]) -> None:
        """Append an execution result."""
        result["_saved_at"] = time.time()
        self._append_jsonl(self._results_path, result)

    def save_feedback(self, feedback: dict[str, Any]) -> None:
        """Append user feedback."""
        feedback["_saved_at"] = time.time()
        self._append_jsonl(self._feedback_path, feedback)

    def update_preferences(self, updates: dict[str, Any]) -> None:
        """Merge updates into the preferences file."""
        prefs = self.get_preferences()
        prefs.update(updates)
        self._preferences_path.write_text(
            json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── Read ───────────────────────────────────────────────

    def get_recent_decisions(self, hours: float = 1.0, limit: int = 20) -> list[dict]:
        """Get recent decisions within the time window."""
        cutoff = time.time() - hours * 3600
        return self._read_jsonl_recent(self._decisions_path, cutoff, limit)

    def get_recent_results(self, hours: float = 1.0, limit: int = 20) -> list[dict]:
        """Get recent execution results."""
        cutoff = time.time() - hours * 3600
        return self._read_jsonl_recent(self._results_path, cutoff, limit)

    def get_recent_feedback(self, hours: float = 1.0, limit: int = 20) -> list[dict]:
        """Get recent user feedback."""
        cutoff = time.time() - hours * 3600
        return self._read_jsonl_recent(self._feedback_path, cutoff, limit)

    def get_preferences(self) -> dict[str, Any]:
        """Read the learned preferences."""
        try:
            return json.loads(self._preferences_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def get_context_summary(self, hours: float = 1.0) -> str:
        """
        Build a text summary of recent memory for inclusion in Brain's LLM prompt.
        Returns empty string if no memory exists.
        """
        parts = []

        decisions = self.get_recent_decisions(hours=hours, limit=10)
        if decisions:
            lines = []
            for d in decisions:
                action = d.get("action", "?")
                reason = d.get("reason", "")
                confidence = d.get("confidence", "?")
                lines.append(f"- {action} (confidence={confidence}): {reason}")
            parts.append("[过去的决策]\n" + "\n".join(lines))

        results = self.get_recent_results(hours=hours, limit=10)
        if results:
            lines = []
            for r in results:
                action = r.get("action", "?")
                status = r.get("status", "?")
                lines.append(f"- {action} → {status}")
            parts.append("[执行结果]\n" + "\n".join(lines))

        feedback = self.get_recent_feedback(hours=hours, limit=10)
        if feedback:
            lines = []
            for f in feedback:
                lines.append(f"- {f.get('summary', json.dumps(f, ensure_ascii=False))}")
            parts.append("[用户反馈]\n" + "\n".join(lines))

        prefs = self.get_preferences()
        if prefs:
            lines = [f"- {k}: {v}" for k, v in prefs.items()]
            parts.append("[用户偏好]\n" + "\n".join(lines))

        return "\n\n".join(parts)

    # ── Internal ───────────────────────────────────────────

    @staticmethod
    def _append_jsonl(path: Path, data: dict) -> None:
        """Atomic append to a JSONL file."""
        line = json.dumps(data, ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    @staticmethod
    def _read_jsonl_recent(path: Path, cutoff: float, limit: int) -> list[dict]:
        """Read JSONL entries newer than cutoff, return latest `limit` entries."""
        if not path.exists() or path.stat().st_size == 0:
            return []

        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                saved_at = entry.get("_saved_at", 0)
                if saved_at >= cutoff:
                    entries.append(entry)
            except json.JSONDecodeError:
                continue

        return entries[-limit:]
