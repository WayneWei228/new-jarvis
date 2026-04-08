"""
Reactor — 事件驱动的快速响应引擎。

单次 LLM 调用同时完成：感知分析 + 推理决策 + 产出内容。

Two trigger modes:
1. AUDIO    — 积累完整语音后触发（等说完再反应）
2. PERIODIC — 每 15s 背景观察一轮

核心原则：大部分时候安静观察，只在真正有价值时才出手。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time

from anthropic import AnthropicBedrock

from input import InputCollector
from brain.memory import MemoryStore
from executor.overlay import NativeOverlay

logger = logging.getLogger(__name__)

REACTOR_SYSTEM_PROMPT = """\
你是一个坐在用户旁边的聪明朋友。你能看到用户的摄像头画面、桌面屏幕、听到他们说的话、知道他们在浏览什么网页。

## 你的性格

你是一个有分寸的朋友，不是一个急于表现的助手。
- 大部分时候你安静地观察和理解，不说话
- 只有当你真的有价值的东西要说时，你才开口
- 你的判断力比你的反应速度更重要

## 感知权重

根据用户的身体语言动态调整你关注的信息：
- **用户在看屏幕** → 屏幕内容是最重要的（正在读什么、写什么、看什么）
- **用户没看屏幕（在聊天、走动、吃东西）** → 语音和摄像头更重要，屏幕信息几乎忽略
- **用户在说话** → 仔细听他在说什么，判断是否有你能帮上的需求

## 什么时候 should_act = true

只有以下情况才行动（门槛要高！）：
1. **用户直接对你说话或表达了明确需求** — "帮我总结一下"、"这个怎么弄"、"翻译一下"
2. **你观察到用户卡住了** — 长时间盯着同一个地方、表情困惑、反复操作同一个东西
3. **有真正高价值的主动帮助** — 比如用户在读长英文文章，你可以总结要点

## 什么时候 should_act = false（大部分时候！）

- 用户在和别人闲聊 → 安静听着，理解上下文，但不插嘴
- 用户在专注写代码/文档 → 不打扰
- 用户在吃东西、休息 → 不打扰
- 你不确定用户需要什么 → 不打扰
- 你上一次行动才过去不久 → 不打扰，除非用户直接叫你

## 输出格式

输出 JSON（不要 markdown 代码块）：

{
  "should_act": true/false,
  "action": "你要做什么（一句话）",
  "content": "直接产出的内容（总结、翻译、建议、代码等）",
  "reason": "简短说明判断依据"
}

## content 规则（只在 should_act=true 时需要）

- **必须是实际产出** — 不要说"我建议你..."，直接做出来
- **简洁** — 200 字以内，用户在忙
- **中文** — 除非涉及代码或英文术语
- **有用** — 问自己：如果我是用户，收到这个会觉得有价值吗？
"""


class Reactor:
    """Event-driven fast response engine."""

    def __init__(
        self,
        collector: InputCollector,
        overlay: NativeOverlay,
        memory_dir: str = "memory",
        periodic_interval: float = 15.0,
        max_frames: int = 1,
    ):
        self.collector = collector
        self.overlay = overlay
        self.memory = MemoryStore(memory_dir=memory_dir)
        self.periodic_interval = periodic_interval
        self.max_frames = max_frames
        self._running = False
        self._last_react_time = 0
        self._last_act_time = 0  # Last time we actually showed a card
        self._min_act_gap = 15.0  # Minimum seconds between overlay cards
        self._audio_buffer: list[str] = []
        self._audio_silence_start: float = 0

        # AWS Bedrock
        self._token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
        self._region = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1")

    async def start(self) -> None:
        """Start the reactor with two concurrent loops."""
        self._running = True
        logger.info(f"Reactor started (periodic={self.periodic_interval}s, "
                     f"min_act_gap={self._min_act_gap}s)")

        await asyncio.gather(
            self._audio_watch_loop(),
            self._periodic_loop(),
        )

    async def _audio_watch_loop(self) -> None:
        """
        Watch for audio events. Wait for a pause in speech (silence)
        before triggering, so we react to complete thoughts, not fragments.
        """
        last_audio_ts = 0

        try:
            while self._running:
                await asyncio.sleep(1.0)

                # Get recent audio (last 8 seconds for context)
                events = self.collector.get_events(
                    since=time.time() - 8.0, limit=50
                )
                audio_events = [
                    e for e in events
                    if e.source == "microphone" and e.data.get("text")
                ]

                if not audio_events:
                    # No audio at all — if we had buffered speech, it means silence
                    if self._audio_buffer and time.time() - self._audio_silence_start > 2.0:
                        # 2 seconds of silence after speech → trigger
                        combined = " ".join(self._audio_buffer)
                        self._audio_buffer.clear()

                        if len(combined) > 8:  # Substantial speech
                            logger.info(f"[AUDIO TRIGGER] {combined[:80]}")
                            await self._react(trigger="audio", trigger_text=combined)
                    continue

                latest = audio_events[-1]
                latest_ts = latest.timestamp

                if latest_ts > last_audio_ts:
                    # New audio arrived
                    last_audio_ts = latest_ts
                    text = latest.data.get("text", "")
                    if text and len(text) > 2:
                        self._audio_buffer.append(text)
                        # Keep buffer manageable (last ~5 utterances)
                        if len(self._audio_buffer) > 5:
                            self._audio_buffer = self._audio_buffer[-5:]
                    self._audio_silence_start = time.time()

        except asyncio.CancelledError:
            pass

    async def _periodic_loop(self) -> None:
        """Periodic background observation."""
        try:
            await asyncio.sleep(self.periodic_interval)
            while self._running:
                now = time.time()
                if now - self._last_react_time >= self.periodic_interval:
                    await self._react(trigger="periodic")
                await asyncio.sleep(self.periodic_interval)
        except asyncio.CancelledError:
            pass

    async def _react(self, trigger: str = "periodic", trigger_text: str = "") -> None:
        """Run one reaction cycle: snapshot → LLM → overlay."""
        now = time.time()
        self._last_react_time = now

        # Build multimodal content from recent events
        window = 15.0 if trigger == "periodic" else 10.0
        snapshot = self.collector.get_snapshot(window_sec=window)
        if snapshot["total_events"] == 0:
            return

        content = self._build_content(snapshot, trigger, trigger_text)
        if not content:
            return

        # Single LLM call
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self._call_llm, content)
        except Exception as e:
            logger.error(f"Reactor LLM call failed: {e}")
            return

        # Parse response
        result = self._parse_response(response)
        if not result:
            return

        if result.get("should_act"):
            action = result.get("action", "")
            body = result.get("content", "")
            reason = result.get("reason", "")

            # Enforce minimum gap between overlay cards
            # (unless it's been a while)
            if now - self._last_act_time < self._min_act_gap:
                logger.info(f"[THROTTLE] {action} (too soon, {now - self._last_act_time:.0f}s since last)")
                return

            logger.info(f"[ACT] {action}")
            logger.info(f"  → {reason[:80]}")

            self.overlay.close_all()
            self.overlay.show_card(
                title=action[:60],
                body=body,
                card_type="result",
                timeout=45,
            )
            self._last_act_time = now

            # Save to memory
            self.memory.save_decision({
                "action": action,
                "content": body[:200],
                "trigger": trigger,
                "reason": reason,
            })
        else:
            reason = result.get("reason", "no action needed")
            logger.info(f"[OBSERVE] {reason[:80]}")

    def _build_content(
        self, snapshot: dict, trigger: str, trigger_text: str
    ) -> list[dict]:
        """Build multimodal content for single LLM call."""
        content: list[dict] = []

        # Camera frame (most recent — shows where user is looking, expression, etc.)
        frames = snapshot["physiological"]["camera_frames"]
        if frames:
            img_path = frames[-1].get("image_path")
            if img_path and os.path.exists(img_path):
                try:
                    with open(img_path, "rb") as f:
                        img_b64 = base64.standard_b64encode(f.read()).decode()
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64,
                        },
                    })
                    content.append({"type": "text", "text": "[摄像头] 用户当前的样子。注意：观察用户是否在看屏幕，这决定了屏幕信息的重要性。"})
                except Exception:
                    pass

        # Desktop screenshot
        screenshots = snapshot["behavioral"]["desktop_screenshots"]
        if screenshots:
            img_path = screenshots[-1].get("image_path")
            if img_path and os.path.exists(img_path):
                try:
                    with open(img_path, "rb") as f:
                        img_b64 = base64.standard_b64encode(f.read()).decode()
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64,
                        },
                    })
                    content.append({"type": "text", "text": "[桌面截屏] 用户屏幕上的内容。如果用户没在看屏幕，这个信息权重降低。"})
                except Exception:
                    pass

        # Audio transcriptions (complete recent speech)
        transcriptions = snapshot["physiological"]["audio_transcriptions"]
        if transcriptions:
            # Deduplicate: only keep final/long versions
            seen = set()
            lines = []
            for t in transcriptions[-15:]:
                text = t.get("text", "").strip()
                if text and len(text) > 3 and text not in seen:
                    seen.add(text)
                    lines.append(text)
            if lines:
                content.append({
                    "type": "text",
                    "text": "[语音记录]\n" + "\n".join(f"- {l}" for l in lines[-8:]),
                })

        # Browser
        visits = snapshot["behavioral"]["browser_visits"]
        if visits:
            lines = [f"- {v.get('title', '?')} ({v.get('url', '?')})" for v in visits[-3:]]
            content.append({
                "type": "text",
                "text": "[浏览器]\n" + "\n".join(lines),
            })

        if not content:
            return []

        # Context block
        ctx_parts = []

        # Trigger info
        if trigger == "audio" and trigger_text:
            ctx_parts.append(f"[触发原因] 用户说了: \"{trigger_text}\"")
            ctx_parts.append("请判断用户是否在对你说话或表达需求。如果只是和别人闲聊，should_act=false。")
        else:
            ctx_parts.append(f"[触发原因] 定期观察 (每{self.periodic_interval}s)")

        # Time since last action
        if self._last_act_time > 0:
            gap = time.time() - self._last_act_time
            ctx_parts.append(f"[上次行动] {gap:.0f}秒前")

        # Memory context (brief)
        memory_ctx = self.memory.get_context_summary(hours=0.5)
        if memory_ctx:
            ctx_parts.append(f"[最近记忆]\n{memory_ctx}")

        content.append({"type": "text", "text": "\n\n".join(ctx_parts)})

        return content

    def _call_llm(self, content: list[dict]) -> str:
        """Single LLM call (blocking)."""
        client = AnthropicBedrock(
            aws_region=self._region,
            api_key=self._token,
        )
        response = client.messages.create(
            model="apac.anthropic.claude-sonnet-4-20250514-v1:0",
            max_tokens=1024,
            system=REACTOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text

    def _parse_response(self, response: str) -> dict | None:
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
        logger.warning(f"Cannot parse response: {text[:100]}")
        return None

    async def stop(self) -> None:
        self._running = False
