"""
Chrome browser history monitor.

Polls Chrome's SQLite History database for new visits and bookmarks.
Emits discrete InputEvent with BrowserEvent payload when new activity is detected.

macOS Chrome history path:
  ~/Library/Application Support/Google/Chrome/Default/History

Note: Chrome locks the DB while running. We copy it to a temp file before reading.

Usage:
    monitor = BrowserMonitor(poll_interval=10.0)
    await monitor.start(event_queue)
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from .models import BrowserEvent, EventCategory, EventNature, InputEvent

logger = logging.getLogger(__name__)


def _get_chrome_history_path() -> Path | None:
    """Get Chrome's History DB path for the current platform."""
    system = platform.system()
    home = Path.home()

    paths = {
        "Darwin": home / "Library/Application Support/Google/Chrome/Default/History",
        "Linux": home / ".config/google-chrome/Default/History",
        "Windows": home / "AppData/Local/Google/Chrome/User Data/Default/History",
    }

    path = paths.get(system)
    if path and path.exists():
        return path

    # Try Chrome Canary on macOS
    if system == "Darwin":
        canary = home / "Library/Application Support/Google/Chrome Canary/Default/History"
        if canary.exists():
            return canary

    return None


def _chrome_timestamp_to_unix(chrome_ts: int) -> float:
    """Convert Chrome's microsecond-since-1601 timestamp to Unix timestamp."""
    # Chrome epoch: 1601-01-01 00:00:00 UTC
    # Unix epoch:   1970-01-01 00:00:00 UTC
    # Difference in microseconds: 11644473600 * 1_000_000
    return (chrome_ts - 11644473600_000_000) / 1_000_000


def _get_chrome_bookmarks_path() -> Path | None:
    """Get Chrome's Bookmarks JSON path."""
    system = platform.system()
    home = Path.home()
    paths = {
        "Darwin": home / "Library/Application Support/Google/Chrome/Default/Bookmarks",
        "Linux": home / ".config/google-chrome/Default/Bookmarks",
        "Windows": home / "AppData/Local/Google/Chrome/User Data/Default/Bookmarks",
    }
    path = paths.get(system)
    return path if path and path.exists() else None


class BrowserMonitor:
    """Monitors Chrome browser history for new visits and bookmarks."""

    def __init__(
        self,
        poll_interval: float = 10.0,
        history_path: str | None = None,
        initial_history: int = 20,
    ):
        self.poll_interval = poll_interval
        self.initial_history = initial_history
        self._history_path = Path(history_path) if history_path else None
        self._running = False
        self._last_visit_id: int = 0

        # Bookmark tracking
        self._bookmarks_path: Path | None = None
        self._known_bookmark_urls: set[str] = set()
        self._last_bookmark_mtime: float = 0.0

        # Dwell time tracking
        self._current_url: str | None = None
        self._current_url_start: float = 0.0

    def _get_db_path(self) -> Path | None:
        if self._history_path and self._history_path.exists():
            return self._history_path
        return _get_chrome_history_path()

    def _copy_db(self, src: Path) -> str:
        """Copy the locked Chrome DB to a temp file for safe reading."""
        tmp = tempfile.mktemp(suffix=".sqlite")
        shutil.copy2(str(src), tmp)
        return tmp

    async def start(self, event_queue: asyncio.Queue) -> None:
        """Start monitoring Chrome history."""
        db_path = self._get_db_path()
        if db_path is None:
            logger.error("Chrome History database not found. Is Chrome installed?")
            return

        logger.info(f"Monitoring Chrome history: {db_path}")
        logger.info(f"Poll interval: {self.poll_interval}s")

        self._running = True

        # Skip past history, only watch for new visits from now on
        try:
            tmp = self._copy_db(db_path)
            conn = sqlite3.connect(tmp)
            cursor = conn.execute("SELECT MAX(id) FROM visits")
            row = cursor.fetchone()
            self._last_visit_id = row[0] if row and row[0] else 0
            conn.close()
            os.unlink(tmp)
            logger.info(f"Watching for new visits only (from visit_id={self._last_visit_id})")
        except Exception as e:
            logger.warning(f"Could not read latest visit ID: {e}")

        # Initialize bookmark tracking
        self._bookmarks_path = _get_chrome_bookmarks_path()
        if self._bookmarks_path:
            self._known_bookmark_urls = self._load_all_bookmark_urls()
            self._last_bookmark_mtime = self._bookmarks_path.stat().st_mtime
            logger.info(f"Bookmark monitoring: {len(self._known_bookmark_urls)} existing bookmarks")

        try:
            while self._running:
                await self._poll_new_visits(db_path, event_queue)
                await self._poll_new_bookmarks(event_queue)
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            logger.info("Browser monitor cancelled")

    async def _poll_new_visits(
        self, db_path: Path, event_queue: asyncio.Queue
    ) -> None:
        """Check for new visits since last poll."""
        loop = asyncio.get_event_loop()
        try:
            events = await loop.run_in_executor(
                None, self._read_new_visits, db_path
            )
            for event in events:
                await event_queue.put(event)
                logger.debug(f"New visit: {event.data.get('title', '?')[:60]}")
        except Exception as e:
            logger.warning(f"Error polling Chrome history: {e}")

    def _read_initial_history(self, db_path: Path) -> list[InputEvent]:
        """Load the N most recent visits on startup so the system has context."""
        events: list[InputEvent] = []
        tmp = self._copy_db(db_path)

        try:
            conn = sqlite3.connect(tmp)
            cursor = conn.execute(
                """
                SELECT v.id, u.url, u.title, v.visit_time, v.visit_duration,
                       v.transition
                FROM visits v
                JOIN urls u ON v.url = u.id
                WHERE u.url NOT LIKE 'chrome://%'
                  AND u.url NOT LIKE 'chrome-extension://%'
                ORDER BY v.id DESC
                LIMIT ?
                """,
                (self.initial_history,),
            )

            rows = cursor.fetchall()
            conn.close()

            # Process in chronological order (oldest first)
            for row in reversed(rows):
                visit_id, url, title, visit_time, duration, transition = row

                unix_ts = _chrome_timestamp_to_unix(visit_time) if visit_time else time.time()
                duration_sec = (duration / 1_000_000) if duration else None

                core_transition = (transition or 0) & 0xFF
                transition_names = {
                    0: "link", 1: "typed", 2: "auto_bookmark",
                    3: "auto_subframe", 4: "manual_subframe",
                    5: "generated", 6: "auto_toplevel", 7: "form_submit",
                    8: "reload", 9: "keyword", 10: "keyword_generated",
                }
                transition_name = transition_names.get(core_transition, f"other_{core_transition}")

                browser_data = BrowserEvent(
                    url=url,
                    title=title or "",
                    visit_time=unix_ts,
                    visit_duration_sec=duration_sec,
                    action="visited",
                    transition_type=transition_name,
                )

                event = InputEvent(
                    timestamp=unix_ts,
                    source="chrome_history",
                    category=EventCategory.BEHAVIORAL,
                    nature=EventNature.DISCRETE,
                    event_type="url_visited",
                    data=browser_data.model_dump(),
                )
                events.append(event)
                self._last_visit_id = max(self._last_visit_id, visit_id)

        except Exception as e:
            logger.error(f"Error reading initial Chrome history: {e}")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

        return events

    def _read_new_visits(self, db_path: Path) -> list[InputEvent]:
        """Read new visits from Chrome's History DB (blocking, run in executor)."""
        events: list[InputEvent] = []
        tmp = self._copy_db(db_path)

        try:
            conn = sqlite3.connect(tmp)
            cursor = conn.execute(
                """
                SELECT v.id, u.url, u.title, v.visit_time, v.visit_duration,
                       v.transition
                FROM visits v
                JOIN urls u ON v.url = u.id
                WHERE v.id > ?
                ORDER BY v.id ASC
                LIMIT 100
                """,
                (self._last_visit_id,),
            )

            for row in cursor.fetchall():
                visit_id, url, title, visit_time, duration, transition = row

                # Skip internal Chrome pages
                if url.startswith("chrome://") or url.startswith("chrome-extension://"):
                    self._last_visit_id = max(self._last_visit_id, visit_id)
                    continue

                unix_ts = _chrome_timestamp_to_unix(visit_time) if visit_time else time.time()
                duration_sec = (duration / 1_000_000) if duration else None

                # Decode transition type
                # https://source.chromium.org/chromium/chromium/src/+/main:ui/base/page_transition_types.h
                core_transition = (transition or 0) & 0xFF
                transition_names = {
                    0: "link", 1: "typed", 2: "auto_bookmark",
                    3: "auto_subframe", 4: "manual_subframe",
                    5: "generated", 6: "auto_toplevel", 7: "form_submit",
                    8: "reload", 9: "keyword", 10: "keyword_generated",
                }
                transition_name = transition_names.get(core_transition, f"other_{core_transition}")

                browser_data = BrowserEvent(
                    url=url,
                    title=title or "",
                    visit_time=unix_ts,
                    visit_duration_sec=duration_sec,
                    action="visited",
                    transition_type=transition_name,
                )

                event = InputEvent(
                    timestamp=unix_ts,
                    source="chrome_history",
                    category=EventCategory.BEHAVIORAL,
                    nature=EventNature.DISCRETE,
                    event_type="url_visited",
                    data=browser_data.model_dump(),
                )
                events.append(event)
                self._last_visit_id = max(self._last_visit_id, visit_id)

            conn.close()
        except Exception as e:
            logger.error(f"Error reading Chrome DB: {e}")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

        return events

    # ── Bookmark Monitoring ────────────────────────────────

    def _load_all_bookmark_urls(self) -> set[str]:
        """Parse Chrome Bookmarks JSON and return all bookmark URLs."""
        if not self._bookmarks_path or not self._bookmarks_path.exists():
            return set()
        try:
            import json
            data = json.loads(self._bookmarks_path.read_text(encoding="utf-8"))
            urls: set[str] = set()
            self._walk_bookmarks(data.get("roots", {}), urls)
            return urls
        except Exception as e:
            logger.warning(f"Error reading bookmarks: {e}")
            return set()

    def _walk_bookmarks(self, node: dict, urls: set[str]) -> None:
        """Recursively walk bookmark tree and collect URLs."""
        if isinstance(node, dict):
            if node.get("type") == "url":
                urls.add(node.get("url", ""))
            for child in node.get("children", []):
                self._walk_bookmarks(child, urls)
            # Walk root folders (bookmark_bar, other, synced)
            for key in ("bookmark_bar", "other", "synced"):
                if key in node:
                    self._walk_bookmarks(node[key], urls)

    async def _poll_new_bookmarks(self, event_queue: asyncio.Queue) -> None:
        """Check if Chrome Bookmarks file changed, emit events for new ones."""
        if not self._bookmarks_path or not self._bookmarks_path.exists():
            return

        try:
            mtime = self._bookmarks_path.stat().st_mtime
            if mtime <= self._last_bookmark_mtime:
                return

            self._last_bookmark_mtime = mtime
            current_urls = self._load_all_bookmark_urls()
            new_urls = current_urls - self._known_bookmark_urls

            for url in new_urls:
                # Try to find the title from bookmark data
                title = self._find_bookmark_title(url)
                browser_data = BrowserEvent(
                    url=url,
                    title=title or url,
                    visit_time=time.time(),
                    action="bookmarked",
                )
                event = InputEvent(
                    source="chrome_history",
                    category=EventCategory.BEHAVIORAL,
                    nature=EventNature.DISCRETE,
                    event_type="url_bookmarked",
                    data=browser_data.model_dump(),
                )
                await event_queue.put(event)
                logger.info(f"New bookmark: {title or url[:60]}")

            self._known_bookmark_urls = current_urls

        except Exception as e:
            logger.warning(f"Error polling bookmarks: {e}")

    def _find_bookmark_title(self, url: str) -> str:
        """Find title for a bookmark URL from the JSON data."""
        try:
            import json
            data = json.loads(self._bookmarks_path.read_text(encoding="utf-8"))
            return self._search_title(data.get("roots", {}), url) or ""
        except Exception:
            return ""

    def _search_title(self, node: dict, target_url: str) -> str | None:
        if isinstance(node, dict):
            if node.get("type") == "url" and node.get("url") == target_url:
                return node.get("name", "")
            for child in node.get("children", []):
                result = self._search_title(child, target_url)
                if result:
                    return result
            for key in ("bookmark_bar", "other", "synced"):
                if key in node:
                    result = self._search_title(node[key], target_url)
                    if result:
                        return result
        return None

    # ── Dwell Time ───────────────────────────────────────

    def _update_dwell_time(self, events: list[InputEvent]) -> None:
        """Track how long user stays on each page. Update events with dwell_time."""
        for event in events:
            url = event.data.get("url", "")
            now = time.time()

            if self._current_url and self._current_url != url:
                # User navigated away — calculate dwell on previous page
                pass  # dwell was already computed by Chrome's visit_duration

            self._current_url = url
            self._current_url_start = now

    async def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
