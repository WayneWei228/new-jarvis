"""
Data models for the INPUT module.

All input sources emit InputEvent objects into a shared async queue.
The LLM Analysis module consumes these events to produce user_status_*.md files.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventCategory(str, Enum):
    """Three categories per ARCHITECTURE.md."""
    PHYSIOLOGICAL = "physiological"   # heart rate, video, audio, facial expression
    BEHAVIORAL = "behavioral"         # browser URLs, favorites, clicks, app switches
    EXECUTION_FEEDBACK = "feedback"   # results from previous Executor round


class EventNature(str, Enum):
    """How the event was produced."""
    CONTINUOUS = "continuous"  # polled at interval (camera, audio, heart rate)
    DISCRETE = "discrete"     # triggered by user action (bookmark, click)
    FEEDBACK = "feedback"     # pushed by Executor after execution


class InputEvent(BaseModel):
    """A single input event from any source."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = Field(default_factory=time.time)
    source: str                       # e.g. "camera", "microphone", "chrome_history", "executor"
    category: EventCategory
    nature: EventNature
    event_type: str                   # e.g. "frame_captured", "speech_transcribed", "url_visited"
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0           # 0.0-1.0, how reliable is this data

    class Config:
        json_encoders = {float: lambda v: round(v, 3)}


class CameraFrame(BaseModel):
    """Data payload for a camera capture event."""
    image_path: str                   # path to saved frame
    width: int
    height: int
    description: str | None = None    # optional LLM-generated description of what's in frame


class AudioSegment(BaseModel):
    """Data payload for an audio transcription event."""
    text: str                         # transcribed text
    language: str = "zh"              # detected language
    duration_sec: float               # segment duration
    audio_path: str | None = None     # path to saved audio clip (optional)


class BrowserEvent(BaseModel):
    """Data payload for a browser history event."""
    url: str
    title: str
    visit_time: float                 # timestamp of visit
    visit_duration_sec: float | None = None
    action: str = "visited"           # visited, favorited, closed
    transition_type: str | None = None  # link, typed, reload, etc.


class FeedbackEvent(BaseModel):
    """Data payload for execution feedback."""
    decision_id: str
    action: str
    status: str                       # success, failed, partial
    result: dict[str, Any] = Field(default_factory=dict)
    user_reaction: str | None = None  # explicit feedback if any
