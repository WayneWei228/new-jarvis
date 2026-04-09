"""
实时麦克风音频采集 — 使用 sounddevice 从默认麦克风捕获 16kHz 单声道音频流。
"""

from __future__ import annotations

import queue

import numpy as np
import sounddevice as sd


class AudioRecorder:
    """Captures audio from the default microphone in real-time.

    Includes energy-based gate: only forwards audio chunks whose RMS
    energy exceeds the threshold, filtering out distant background chatter.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        blocksize: int = 640,
        energy_threshold: float = 0.02,
        holdover_blocks: int = 12,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self.energy_threshold = energy_threshold
        self._holdover_blocks = holdover_blocks  # keep sending N blocks after last loud chunk
        self._holdover_remaining = 0
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None

    def _callback(
        self, indata: np.ndarray, frames: int, time_info, status: sd.CallbackFlags
    ):
        if status:
            pass  # ignore occasional overflow

        rms = np.sqrt(np.mean(indata ** 2))

        if rms >= self.energy_threshold:
            # Loud enough — forward and reset holdover
            self._holdover_remaining = self._holdover_blocks
            self._queue.put(indata.copy())
        elif self._holdover_remaining > 0:
            # Still in holdover window — forward to capture tail of speech
            self._holdover_remaining -= 1
            self._queue.put(indata.copy())

    def start(self):
        """Open the microphone stream and begin capturing audio."""
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=self.blocksize,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        """Close the microphone stream."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
