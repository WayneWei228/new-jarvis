"""
Execution feedback receiver.

Receives results from the Executor module and pushes them
into the input pipeline as feedback events.

This is the "C" input category from ARCHITECTURE.md — the feedback loop
that lets each round inform the next.

Usage:
    receiver = FeedbackReceiver()
    await receiver.start(event_queue)

    # From executor:
    await receiver.push_feedback(decision_id="dec_001", action="organize_docs",
                                  status="success", result={...})
"""

from __future__ import annotations

import asyncio
import logging

from .models import EventCategory, EventNature, FeedbackEvent, InputEvent

logger = logging.getLogger(__name__)


class FeedbackReceiver:
    """Receives execution feedback and injects it into the input pipeline."""

    def __init__(self):
        self._feedback_queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def start(self, event_queue: asyncio.Queue) -> None:
        """Listen for feedback and forward to the main event queue."""
        self._running = True
        logger.info("Feedback receiver started")

        try:
            while self._running:
                try:
                    feedback = await asyncio.wait_for(
                        self._feedback_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                event = InputEvent(
                    source="executor",
                    category=EventCategory.EXECUTION_FEEDBACK,
                    nature=EventNature.FEEDBACK,
                    event_type="execution_complete",
                    data=feedback.model_dump(),
                )
                await event_queue.put(event)
                logger.info(
                    f"Feedback received: {feedback.action} -> {feedback.status}"
                )

        except asyncio.CancelledError:
            logger.info("Feedback receiver cancelled")

    async def push_feedback(
        self,
        decision_id: str,
        action: str,
        status: str,
        result: dict | None = None,
        user_reaction: str | None = None,
    ) -> None:
        """Push execution feedback into the pipeline. Called by Executor."""
        feedback = FeedbackEvent(
            decision_id=decision_id,
            action=action,
            status=status,
            result=result or {},
            user_reaction=user_reaction,
        )
        await self._feedback_queue.put(feedback)

    async def stop(self) -> None:
        """Stop receiving feedback."""
        self._running = False
