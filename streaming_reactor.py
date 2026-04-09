"""
StreamingReactor — 持续感知引擎。

使用 OpenAI Realtime API (gpt-4o) 实现真正的持续多模态感知：
- 音频直接流式传输（原生理解语气/情绪，无需 ASR 中转）
- 摄像头和桌面截图定期注入对话
- 模型自然地决定何时回复、何时沉默
- 复杂任务路由到 Claude Code (Opus) 执行

架构：
  Microphone ──stream──→ OpenAI Realtime API (gpt-4o)
  Camera/Desktop ──5s──→        ↓
                           持续感知 + 实时决策
                                 ↓
                    语音回复 → 直接说（最快）
                    show_reply → Overlay 弹窗
                    execute_task → Claude Code (Opus)
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import subprocess
import time
import uuid

import numpy as np
from anthropic import AnthropicBedrock

from brain.memory import MemoryStore
from executor.overlay import NativeOverlay

logger = logging.getLogger(__name__)

REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"

# Haiku for vision description
VISION_MODEL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

VISION_PROMPT = """\
你是一个视觉观察助手。简洁地描述你看到的内容，重点关注：
- 用户在做什么（表情、动作、是否在看屏幕）
- 屏幕上显示什么（应用、内容、关键文字）
- 任何值得注意的变化

用一段话描述，不超过100字。如果没什么特别的，就说"无特别变化"。
"""

# Image compression
IMG_SCALE = 0.25
IMG_QUALITY = 60

SYSTEM_INSTRUCTIONS = """\
你是一个坐在用户旁边的聪明朋友。你能听到用户说的话、看到用户的摄像头画面和桌面屏幕。
你是持续在线的，实时感知一切。

## 你的性格
你是一个有分寸的朋友，不是急于表现的助手。

## 感知权重
- 用户在说话 → 最重要，仔细听，理解意图和语气
- 用户看屏幕 → 屏幕内容重要
- 用户没看屏幕 → 摄像头更重要

## 回复规则
- 用户跟你说话时，自然地回复（语音）
- 用户没有跟你说话时，大部分时候保持安静
- 只在发现真正有用的信息时才主动开口
- 像朋友一样说话，简洁自然，用中文

## 工具
- show_reply: 弹窗显示较长文字（总结、翻译、列表等）
- execute_task: 复杂操作（写代码、搜索、发邮件、操作文件等），交给 Claude Code (Opus)

执行层可用的 Skills：
/browse, /deep-research-pro, /desearch-web-search, /send-email, /daily-news,
/macos-calendar, /mac-control, /universal-translate, /summarize-pro,
/slack, /lark-im, /lark-doc, /github, /apple-notes, /apple-reminders,
/spotify-player, /weather, /notion, /trello, /1password
以及更多...执行层可以读写文件、运行代码、操作系统
"""

TOOLS = [
    {
        "type": "function",
        "name": "show_reply",
        "description": "弹窗显示文字给用户。用于展示较长内容：总结、翻译、列表、代码片段等。简短口头回复不需要调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "卡片标题"},
                "text": {"type": "string", "description": "要显示的内容"},
            },
            "required": ["text"],
        },
    },
    {
        "type": "function",
        "name": "execute_task",
        "description": "执行复杂任务（写代码、搜索网页、发邮件、操作文件、控制应用等）。交给 Claude Code (Opus)。Opus 看不到图片，必须用文字描述所有视觉上下文。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "任务描述（一句话）"},
                "prompt": {"type": "string", "description": "给 Claude Code 的详细指令"},
            },
            "required": ["action", "prompt"],
        },
    },
]


class StreamingReactor:
    """Continuous perception engine using OpenAI Realtime API."""

    def __init__(
        self,
        collector,
        overlay: NativeOverlay,
        memory_dir: str = "memory",
        vision_interval: float = 5.0,
    ):
        self.collector = collector
        self.overlay = overlay
        self.memory = MemoryStore(memory_dir=memory_dir)
        self.vision_interval = vision_interval
        self._running = False
        self._ws = None
        self._last_act_time = 0
        self._min_act_gap = 8.0
        self._card_contexts: dict[str, dict] = {}
        self._pil_available = None

        # Bedrock for Haiku vision
        self._bedrock_token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
        self._bedrock_region = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1")

        # Feedback / preference learning
        self._feedback_count_since_learn = 0
        self._last_learn_time = 0

    async def start(self) -> None:
        """Connect to OpenAI Realtime API and start streaming."""
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            logger.error("OPENAI_API_KEY not set")
            return

        self._running = True
        prefs = self.memory.get_preferences()
        logger.info(f"StreamingReactor starting (vision_interval={self.vision_interval}s, "
                     f"preferences={len(prefs.get('rules', []))} rules)")

        while self._running:
            try:
                await self._run_session(api_key)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Realtime session error: {e}")
                if self._running:
                    logger.info("Reconnecting in 3s...")
                    await asyncio.sleep(3)

    async def _run_session(self, api_key: str) -> None:
        """One WebSocket session — reconnects on failure."""
        import websockets

        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        self.overlay.push_thinking([
            {"text": "连接 Realtime API ...", "type": "action"},
        ])

        async with websockets.connect(
            REALTIME_URL,
            additional_headers=headers,
            max_size=20 * 1024 * 1024,
        ) as ws:
            self._ws = ws
            logger.info("Realtime API connected")

            await self._configure_session()

            self.overlay.push_thinking([
                {"text": "持续感知已启动 (streaming)", "type": "action"},
            ])

            try:
                await asyncio.gather(
                    self._stream_audio(),
                    self._update_vision(),
                    self._listen_responses(),
                    self._feedback_loop(),
                )
            except websockets.ConnectionClosed:
                logger.warning("WebSocket connection closed")

    async def _configure_session(self) -> None:
        """Send session config to API."""
        prefs = self.memory.get_preferences()
        rules = prefs.get("rules", [])

        instructions = SYSTEM_INSTRUCTIONS
        if rules:
            rules_text = "\n".join(f"- {r}" for r in rules)
            instructions += f"\n\n## 用户偏好\n{rules_text}\n"

        await self._ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": instructions,
                "voice": "shimmer",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "gpt-4o-mini-transcribe"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 800,
                    "create_response": True,
                },
                "tools": TOOLS,
                "tool_choice": "auto",
            },
        }))
        logger.info("Session configured (server VAD, audio+text)")

    # ── Audio Streaming ──────────────────────────────────────

    async def _stream_audio(self) -> None:
        """Capture 24kHz audio and stream to Realtime API."""
        import sounddevice as sd
        import queue as queue_mod

        audio_queue: queue_mod.Queue[np.ndarray] = queue_mod.Queue()

        def callback(indata, frames, time_info, status):
            audio_queue.put(indata.copy())

        stream = sd.InputStream(
            samplerate=24000,
            channels=1,
            blocksize=2400,  # 100ms chunks
            dtype="float32",
            callback=callback,
        )
        stream.start()
        logger.info("Audio streaming: 24kHz mono → Realtime API")

        try:
            while self._running:
                try:
                    chunk = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: audio_queue.get(timeout=0.5)
                    )
                except queue_mod.Empty:
                    continue

                pcm16 = (
                    (chunk.flatten() * 32768)
                    .clip(-32768, 32767)
                    .astype(np.int16)
                    .tobytes()
                )

                try:
                    await self._ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(pcm16).decode(),
                    }))
                except Exception:
                    break
        finally:
            stream.stop()
            stream.close()
            logger.info("Audio streaming stopped")

    # ── Vision Updates (Haiku describes → text injected) ────

    async def _update_vision(self) -> None:
        """Haiku describes camera+desktop → text injected into Realtime conversation."""
        while self._running:
            await asyncio.sleep(self.vision_interval)

            snapshot = self.collector.get_snapshot(window_sec=10.0)

            # Build image content for Haiku
            haiku_content: list[dict] = []

            frames = snapshot["physiological"]["camera_frames"]
            if frames:
                img_b64 = self._compress_image(frames[-1].get("image_path"))
                if img_b64:
                    haiku_content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
                    })
                    haiku_content.append({"type": "text", "text": "[摄像头]"})

            screenshots = snapshot["behavioral"]["desktop_screenshots"]
            if screenshots:
                img_b64 = self._compress_image(screenshots[-1].get("image_path"))
                if img_b64:
                    haiku_content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
                    })
                    haiku_content.append({"type": "text", "text": "[桌面截屏]"})

            if not haiku_content:
                continue

            # Call Haiku to describe what it sees
            try:
                loop = asyncio.get_event_loop()
                description = await loop.run_in_executor(
                    None, self._describe_vision, haiku_content
                )
            except Exception as e:
                logger.warning(f"Vision describe failed: {e}")
                continue

            if not description or description == "无特别变化":
                continue

            # Browser context
            visits = snapshot["behavioral"]["browser_visits"]
            browser_text = ""
            if visits:
                lines = [f"{v.get('title', '?')}" for v in visits[-2:]]
                browser_text = f" 浏览器: {'; '.join(lines)}"

            # Inject as text message into Realtime conversation
            vision_text = f"[视觉更新] {description}{browser_text}"

            try:
                await self._ws.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": vision_text}],
                    },
                }))
                logger.debug(f"[VISION] {description[:60]}")
                self.overlay.push_thinking([
                    {"text": f"视觉: {description[:40]}", "type": "input"},
                ])
            except Exception as e:
                logger.warning(f"Vision inject failed: {e}")

    def _describe_vision(self, content: list[dict]) -> str:
        """Haiku describes camera+desktop images. Blocking."""
        client = AnthropicBedrock(
            aws_region=self._bedrock_region,
            api_key=self._bedrock_token,
        )
        resp = client.messages.create(
            model=VISION_MODEL,
            max_tokens=150,
            system=VISION_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        return resp.content[0].text.strip()

    # ── Response Listener ────────────────────────────────────

    async def _listen_responses(self) -> None:
        """Process events from the Realtime API."""
        current_tool_name = ""
        current_tool_args = ""
        current_tool_call_id = ""

        async for raw in self._ws:
            if not self._running:
                break

            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")

            # ── VAD events
            if etype == "input_audio_buffer.speech_started":
                self.overlay.push_thinking([
                    {"text": "用户说话中...", "type": "input"},
                ])

            elif etype == "input_audio_buffer.speech_stopped":
                self.overlay.push_thinking([
                    {"text": "语音结束, 思考中...", "type": "reason"},
                ])

            # ── User speech transcript
            elif etype == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "").strip()
                if transcript:
                    logger.info(f"[USER] {transcript}")
                    self.overlay.push_thinking([
                        {"text": f"用户: {transcript[:60]}", "type": "input"},
                    ])

            # ── Model audio transcript (what it's saying)
            elif etype == "response.audio_transcript.done":
                transcript = event.get("transcript", "").strip()
                if transcript:
                    logger.info(f"[JARVIS] {transcript}")
                    self.overlay.push_thinking([
                        {"text": f"回复: {transcript[:60]}", "type": "action"},
                    ])

            # ── Function call building
            elif etype == "response.output_item.added":
                item = event.get("item", {})
                if item.get("type") == "function_call":
                    current_tool_name = item.get("name", "")
                    current_tool_call_id = item.get("call_id", "")
                    current_tool_args = ""

            elif etype == "response.function_call_arguments.delta":
                current_tool_args += event.get("delta", "")

            elif etype == "response.output_item.done":
                item = event.get("item", {})
                if item.get("type") == "function_call":
                    name = item.get("name", current_tool_name)
                    call_id = item.get("call_id", current_tool_call_id)
                    args_str = item.get("arguments", current_tool_args)
                    await self._handle_tool_call(name, args_str, call_id)
                    current_tool_name = ""
                    current_tool_args = ""
                    current_tool_call_id = ""

            # ── Errors
            elif etype == "error":
                err = event.get("error", {})
                logger.error(f"API error: {err.get('message', err)}")
                self.overlay.push_thinking([
                    {"text": f"错误: {str(err.get('message', ''))[:50]}", "type": "error"},
                ])

    # ── Tool Handling ────────────────────────────────────────

    async def _handle_tool_call(self, name: str, args_str: str, call_id: str) -> None:
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            logger.error(f"Bad tool args: {args_str[:100]}")
            await self._send_tool_result(call_id, "参数解析失败")
            return

        if name == "show_reply":
            await self._tool_show_reply(args, call_id)
        elif name == "execute_task":
            await self._tool_execute(args, call_id)
        else:
            await self._send_tool_result(call_id, f"未知工具: {name}")

    async def _tool_show_reply(self, args: dict, call_id: str) -> None:
        text = args.get("text", "")
        title = args.get("title", "Jarvis")
        card_id = uuid.uuid4().hex[:8]

        logger.info(f"[CARD] {title}: {text[:60]}")
        self.overlay.push_thinking([
            {"text": f"弹窗: {title}", "type": "action"},
        ])

        self.overlay.close_all()
        self.overlay.show_card(
            title=title[:60], body=text,
            card_type="result", card_id=card_id, timeout=30,
        )
        self._card_contexts[card_id] = {
            "action": "show_reply", "content": text[:200],
            "trigger": "streaming", "time": time.time(),
        }
        await self._send_tool_result(call_id, "已显示给用户")

    async def _tool_execute(self, args: dict, call_id: str) -> None:
        action = args.get("action", "")
        prompt = args.get("prompt", "")
        now = time.time()

        if now - self._last_act_time < self._min_act_gap:
            await self._send_tool_result(call_id, "操作太频繁，请稍后")
            return

        card_id = uuid.uuid4().hex[:8]
        logger.info(f"[EXEC] {action}")
        self.overlay.push_thinking([
            {"text": f"执行: {action[:40]}", "type": "action"},
            {"text": "Claude Code (Opus) ...", "type": "action"},
        ])

        self.overlay.close_all()
        self.overlay.show_card(
            title=action[:60], body="Thinking ...",
            card_type="thinking", card_id=f"tmp_{card_id}", timeout=120,
        )

        loop = asyncio.get_event_loop()
        body = await loop.run_in_executor(None, self._run_claude_code, prompt)
        if not body:
            body = "(执行无输出)"

        self.overlay.close_all()
        self.overlay.show_card(
            title=action[:60], body=body[:800],
            card_type="result", card_id=card_id, timeout=45,
        )
        self._last_act_time = now

        self.overlay.push_thinking([
            {"text": f"Opus 完成 ({len(body)}字)", "type": "action"},
        ])

        self._card_contexts[card_id] = {
            "action": action, "content": body[:200],
            "trigger": "streaming", "time": now,
        }
        self.memory.save_decision({
            "action": action, "content": body[:200],
            "trigger": "streaming", "reason": "realtime", "card_id": card_id,
        })

        await self._send_tool_result(call_id, body[:500])

    async def _send_tool_result(self, call_id: str, output: str) -> None:
        """Return tool output and let model continue."""
        await self._ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": output,
            },
        }))
        await self._ws.send(json.dumps({"type": "response.create"}))

    # ── Claude Code Execution ────────────────────────────────

    def _run_claude_code(self, prompt: str) -> str:
        """Call Claude Code CLI (Opus). Blocking."""
        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text",
                 "--dangerously-skip-permissions"],
                capture_output=True, text=True, timeout=120,
            )
            output = result.stdout.strip()
            if result.returncode == 0 and output:
                return output
            if result.stderr:
                logger.warning(f"Claude Code stderr: {result.stderr[:200]}")
            return ""
        except subprocess.TimeoutExpired:
            logger.warning("Claude Code timed out")
            return ""
        except FileNotFoundError:
            logger.warning("claude CLI not found")
            return ""

    # ── Image Compression ────────────────────────────────────

    def _compress_image(self, img_path: str | None) -> str | None:
        if not img_path or not os.path.exists(img_path):
            return None
        if self._pil_available is None:
            try:
                from PIL import Image
                self._pil_available = True
            except ImportError:
                self._pil_available = False
        try:
            if self._pil_available:
                from PIL import Image
                img = Image.open(img_path)
                w, h = int(img.width * IMG_SCALE), int(img.height * IMG_SCALE)
                resized = img.resize((w, h))
                buf = io.BytesIO()
                resized.save(buf, format="JPEG", quality=IMG_QUALITY)
                return base64.standard_b64encode(buf.getvalue()).decode()
            else:
                with open(img_path, "rb") as f:
                    return base64.standard_b64encode(f.read()).decode()
        except Exception:
            return None

    # ── Feedback ─────────────────────────────────────────────

    async def _feedback_loop(self) -> None:
        while self._running:
            await asyncio.sleep(5)
            for fb in self.overlay.get_feedback():
                card_id = fb.get("card_id", "")
                ftype = fb.get("feedback", "unknown")
                if ftype == "closed_by_system":
                    continue
                context = self._card_contexts.pop(card_id, {})
                self.memory.save_feedback({
                    "type": ftype, "card_id": card_id,
                    "card_action": context.get("action", ""),
                    "card_content": context.get("content", ""),
                    "source": "overlay_button",
                })
                self._feedback_count_since_learn += 1
                logger.info(f"[FEEDBACK] {ftype}")

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
