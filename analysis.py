"""
LLM Analysis Module — 融合多模态输入，生成用户状态描述。

Takes a snapshot from InputCollector (camera frames, audio transcriptions,
browser visits), sends to Claude on AWS Bedrock, and produces a structured
text description of what the user is currently doing.

Output: user_status_{timestamp}.md in input/user_status/
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from anthropic import AnthropicBedrock

from input import InputCollector

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一个用户状态分析引擎。你会收到四种实时数据：
1. 摄像头画面 — 用户当前的样子和环境
2. 桌面截屏 — 用户电脑屏幕上正在显示什么
3. 麦克风语音转文字 — 用户说了什么
4. 浏览器记录 — 用户正在看什么网页

你的任务：综合以上所有信息，用中文写一段简洁的用户状态描述，包含：

## 当前状态
- 用户在做什么（一句话）
- 情绪/状态（专注、疲惫、兴奋、无聊等）
- 环境（在哪里、周围有什么）

## 关键信号
- 列出 2-3 个最重要的观察（HIGH/MEDIUM/LOW 标注）

## 推测意图
- 用户可能想要完成什么？

保持简洁，不要编造没有依据的信息。如果某个数据源没有内容就跳过。
"""


class LLMAnalysis:
    """Periodically analyzes input data and generates user status descriptions."""

    def __init__(
        self,
        collector: InputCollector,
        interval_sec: float = 30.0,
        output_dir: str = "input/user_status",
        max_frames: int = 2,
        notifier=None,
    ):
        self.collector = collector
        self.interval_sec = interval_sec
        self.output_dir = Path(output_dir)
        self.max_frames = max_frames
        self._running = False
        self._round = 0
        self._notifier = notifier

        # AWS Bedrock with API Key
        self._token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
        self._region = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1")

    async def start(self) -> None:
        """Start the periodic analysis loop."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        logger.info(f"LLM Analysis started (every {self.interval_sec}s, region={self._region})")

        try:
            while self._running:
                await asyncio.sleep(self.interval_sec)
                await self._analyze()
        except asyncio.CancelledError:
            logger.info("LLM Analysis stopped")

    async def _analyze(self) -> None:
        """Run one analysis round."""
        self._round += 1
        snapshot = self.collector.get_snapshot(window_sec=self.interval_sec + 5)

        if snapshot["total_events"] == 0:
            logger.debug(f"Round {self._round}: no events, skipping")
            return

        logger.info(f"Round {self._round}: analyzing {snapshot['total_events']} events...")

        content = self._build_content(snapshot)
        if not content:
            return

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self._call_llm, content)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return

        # Save result
        ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
        output_path = self.output_dir / f"status_{ts}.md"

        header = f"# User Status — {datetime.now(timezone(timedelta(hours=8))).isoformat()}\n\n"
        output_path.write_text(header + response, encoding="utf-8")

        logger.info(f"Round {self._round}: saved → {output_path.name}")
        preview = response[:200].replace("\n", " ")
        logger.info(f"  {preview}...")

        if self._notifier:
            asyncio.ensure_future(self._notifier.push_event("status_update", {
                "summary": preview,
            }))

    def _build_content(self, snapshot: dict) -> list[dict]:
        """Build Claude API message content from snapshot."""
        content: list[dict] = []

        # 1. Camera frames (as images)
        frames = snapshot["physiological"]["camera_frames"]
        if frames:
            recent_frames = frames[-self.max_frames:]
            for f in recent_frames:
                img_path = f.get("image_path")
                if img_path and os.path.exists(img_path):
                    try:
                        with open(img_path, "rb") as fh:
                            img_b64 = base64.standard_b64encode(fh.read()).decode()
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": img_b64,
                            },
                        })
                    except Exception as e:
                        logger.warning(f"Cannot read frame {img_path}: {e}")

            content.append({"type": "text", "text": f"[摄像头] 以上是最近 {len(recent_frames)} 帧画面"})

        # 2. Desktop screenshots
        screenshots = snapshot["behavioral"]["desktop_screenshots"]
        if screenshots:
            latest = screenshots[-1]  # only send the most recent one
            img_path = latest.get("image_path")
            if img_path and os.path.exists(img_path):
                try:
                    with open(img_path, "rb") as fh:
                        img_b64 = base64.standard_b64encode(fh.read()).decode()
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64,
                        },
                    })
                    content.append({"type": "text", "text": "[桌面截屏] 以上是用户当前的电脑桌面"})
                except Exception as e:
                    logger.warning(f"Cannot read screenshot {img_path}: {e}")

        # 3. Audio transcriptions
        transcriptions = snapshot["physiological"]["audio_transcriptions"]
        if transcriptions:
            lines = []
            for t in transcriptions:
                text = t.get("text", "")
                dur = t.get("duration_sec", 0)
                if text:
                    lines.append(f"- ({dur:.1f}s) {text}")
            if lines:
                content.append({
                    "type": "text",
                    "text": "[麦克风语音转文字]\n" + "\n".join(lines),
                })

        # 3. Browser visits
        visits = snapshot["behavioral"]["browser_visits"]
        if visits:
            lines = []
            for v in visits:
                title = v.get("title", "?")
                url = v.get("url", "?")
                lines.append(f"- {title}\n  {url}")
            if lines:
                content.append({
                    "type": "text",
                    "text": "[浏览器记录]\n" + "\n".join(lines),
                })

        if not content:
            return []

        content.append({
            "type": "text",
            "text": "请综合以上所有信息，生成用户当前状态描述。",
        })

        return content

    def _call_llm(self, content: list[dict]) -> str:
        """Call Claude via AWS Bedrock with API Key (blocking, run in executor)."""
        client = AnthropicBedrock(
            aws_region=self._region,
            api_key=self._token,
        )
        response = client.messages.create(
            model="apac.anthropic.claude-sonnet-4-20250514-v1:0",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text

    async def stop(self) -> None:
        self._running = False
