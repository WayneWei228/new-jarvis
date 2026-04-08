"""
Audio input with real-time speech-to-text via 讯飞实时语音转写大模型。

Uses IflytekStreamingASR (WebSocket) + AudioRecorder (sounddevice) from the
project root. Emits InputEvent with AudioSegment payload on every recognized
sentence.

Required env vars:
    IFLYTEK_APP_ID
    IFLYTEK_API_KEY
    IFLYTEK_API_SECRET

Usage:
    audio = AudioInput()
    await audio.start(event_queue)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time

from .models import AudioSegment, EventCategory, EventNature, InputEvent

logger = logging.getLogger(__name__)

# Add project root so we can import iflytek_client / recorder
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


class AudioInput:
    """Captures microphone audio and transcribes via 讯飞 in real-time."""

    def __init__(self, language: str = "zh"):
        self.language = language
        self._running = False
        self._recorder = None
        self._asr = None
        self._asr_thread: threading.Thread | None = None

    async def start(self, event_queue: asyncio.Queue) -> None:
        """Start microphone capture + 讯飞 streaming ASR."""
        # Check env vars
        app_id = os.environ.get("IFLYTEK_APP_ID")
        api_key = os.environ.get("IFLYTEK_API_KEY")
        api_secret = os.environ.get("IFLYTEK_API_SECRET")

        if not all([app_id, api_key, api_secret]):
            missing = [k for k in ("IFLYTEK_APP_ID", "IFLYTEK_API_KEY", "IFLYTEK_API_SECRET")
                       if not os.environ.get(k)]
            logger.error(f"Missing env vars: {', '.join(missing)}. Cannot start audio input.")
            return

        try:
            from iflytek_client import IflytekStreamingASR
            from recorder import AudioRecorder
        except ImportError as e:
            logger.error(f"Cannot import iflytek_client/recorder: {e}")
            return

        self._running = True
        loop = asyncio.get_event_loop()

        # Set up recorder
        self._recorder = AudioRecorder(sample_rate=16000, channels=1, blocksize=640)

        # Set up ASR client
        self._asr = IflytekStreamingASR(app_id, api_key, api_secret)

        # Track current sentence for building segments
        self._segment_start = time.time()

        def on_result(text: str, is_final: bool):
            """Called from ASR thread when text is recognized."""
            if not text.strip():
                return

            segment = AudioSegment(
                text=text.strip(),
                language=self.language,
                duration_sec=round(time.time() - self._segment_start, 2),
            )

            event = InputEvent(
                source="microphone",
                category=EventCategory.PHYSIOLOGICAL,
                nature=EventNature.CONTINUOUS,
                event_type="speech_transcribed",
                data=segment.model_dump(),
                confidence=1.0 if is_final else 0.6,
            )

            # Schedule putting event into async queue from sync thread
            loop.call_soon_threadsafe(event_queue.put_nowait, event)

            if is_final:
                logger.info(f"[讯飞] {text.strip()}")
                self._segment_start = time.time()

        self._asr.on_result(on_result)

        # Start recorder
        self._recorder.start()
        logger.info("Microphone started (16kHz, mono)")

        # Start ASR in background thread (it's a blocking WebSocket loop)
        self._asr_thread = threading.Thread(
            target=self._asr.run,
            args=(self._recorder._queue,),
            daemon=True,
            name="iflytek-asr",
        )
        self._asr_thread.start()
        logger.info("讯飞 ASR started")

        # Keep alive until stopped
        try:
            while self._running:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info("Audio input cancelled")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop audio capture and ASR."""
        self._running = False
        if self._recorder:
            self._recorder.stop()
            self._recorder = None
            logger.info("Microphone stopped")
