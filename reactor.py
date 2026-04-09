"""
Reactor — 3 秒 tick 的实时感知引擎。

架构：
  Haiku (3s tick, 快, 带 vision) → 观察/决策
  Claude Code (Opus, 按需) → 执行

每 3 秒：
  1. 抓最新截屏 + 摄像头（压缩到 ~25%）+ 语音 + 浏览器
  2. 全部喂给 Haiku → 继续观察 or 行动
  3. 如果行动 → Claude Code (Opus) 执行

反馈系统：overlay 按钮 + 语音 meta-feedback → 偏好学习
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

from google import genai
from google.genai import types as gtypes

from input import InputCollector
from brain.memory import MemoryStore
from executor.overlay import NativeOverlay

logger = logging.getLogger(__name__)

# Models — Gemini Flash (fast + cheap + vision)
OBSERVE_MODEL = "gemini-3-flash-preview"
LEARN_MODEL = "gemini-3-flash-preview"

# Image compression target
IMG_SCALE = 0.25
IMG_QUALITY = 60

SYSTEM_PROMPT_BASE = """\
你是一个坐在用户旁边的聪明朋友。你能看到用户的摄像头画面、桌面屏幕（全屏+光标附近特写）、听到他们说的话、知道他们在浏览什么网页。
每 3 秒你会收到一次最新的多模态输入。

## 你的性格
你是一个有分寸的朋友，不是急于表现的助手。
你的分寸感来自对这个用户的了解。

## 感知层级（按重要性排序）

### 1. 语音（最高优先）
- 语音分两种标记：
  - **[语音（已说完）]** — 确认的完整语句，可以完全信赖
  - **[正在说...]** — 用户还没说完，但你可以看到目前说了什么
- 当看到 [正在说...]：
  - 如果意图已经很明确（比如"帮我打开..."），可以直接响应，不用等说完
  - 如果还不确定用户要什么，选择 observe 等下一轮
  - 不要因为用户在说话就完全沉默 — 你有判断力
- 判断：是在跟你说话？还是在跟别人说话？还是自言自语？
- 注意语气：困惑、着急、随意闲聊、命令式
- 如果用户明确提出需求（"帮我..."、"你能不能..."），必须响应

### 2. 光标焦点区域（用户正在关注的内容）
- 你会收到一张光标附近的特写截图 — 这是用户此刻最关注的内容
- 仔细阅读光标周围的文字、代码、UI 元素
- 光标位置信息（坐标）也会提供，结合全屏截图理解上下文
- 关注：用户是否在编辑文字？在看错误信息？在浏览网页？在填表？

### 3. 全屏桌面截图
- 提供整体上下文：用户在用什么应用？打开了什么窗口？
- 结合光标特写理解完整场景
- 注意：窗口标题栏、标签页标题、文件路径、错误弹窗

### 4. 摄像头画面
- 用户的物理状态：在看屏幕吗？表情如何？
- 如果用户没看屏幕 → 降低屏幕信息权重
- 如果用户看起来困惑或沮丧 → 提高主动帮助的倾向

### 5. 浏览器历史
- 用户最近在浏览什么网页
- 结合屏幕内容判断用户在研究什么话题

## 屏幕分析要点
- **代码编辑器**：关注光标所在行附近的代码，注意语法错误、红色波浪线、报错信息
- **终端**：关注最后几行输出，特别是错误信息（error, failed, exception）
- **浏览器**：关注页面标题、正在阅读的段落、搜索关键词
- **聊天应用**：关注最新消息，但注意隐私，不要主动提及私人对话内容
- **文档/PPT**：关注用户正在编辑的部分

## 行动判断（重要！）

### 默认状态是 observe（90%+ 的时间）
用户在正常工作、跟朋友聊天、浏览网页 → 保持沉默，不要打扰。

### 什么时候不该回复
- 用户在跟别人（朋友、同事）说话，不是在跟你说 → observe
- 用户在正常写代码、看视频、浏览网页 → observe
- 没有明确的求助信号 → observe
- 你不确定用户是不是在跟你说话 → observe

### 什么时候用 reply（少用）
- 用户明确在跟你对话（叫你名字、看着摄像头说话、上下文明显是对你说的）
- 用户遇到了明显的报错，且已经卡住一会了（不是刚出现就插嘴）

### 什么时候用 execute（更少用，但价值最高）
- 用户明确要求做某事（"帮我..."、"你能不能..."）
- 你观察到一个真正有价值的机会：用户反复做同一操作、明显遗漏了什么重要信息
- execute 是你最有价值的能力 — 不是回复几句话，而是真正帮用户做事

### 核心原则
多观察，少说话，多做事。
一次有用的 execute 比十次 reply 更有价值。
宁可沉默十轮，也不要说一句废话。
"""

SYSTEM_PROMPT_OUTPUT = """\
## 输出格式

输出 JSON（不要 markdown 代码块）：

{
  "action_type": "observe" / "reply" / "execute",
  "reply": "直接回复内容（action_type=reply 时必填）",
  "action": "执行任务描述（action_type=execute 时必填）",
  "execution_prompt": "给 Claude Code (Opus) 的详细指令",
  "reason": "简短判断依据",
  "meta_feedback": "用户对AI行为的反馈（'别烦我'/'这个不错'等），没有则留空"
}

## action_type 选择规则

**observe** — 继续观察，不打扰用户
**reply** — 简单回复：闲聊、回答问题、提供信息、简短建议。直接弹窗显示，速度最快。
**execute** — 复杂任务：写代码、操作文件、搜索网页、发邮件、控制应用、深度研究等。交给 Claude Code (Opus) 执行。

判断标准：如果回复只需要文字（不需要执行任何操作），用 reply。需要动手做事的，用 execute。

## reply 规则（action_type=reply 时）
- 直接写回复内容，会弹窗显示给用户
- 像朋友一样自然地说话
- 不要太长，200字以内

## execution_prompt 规则（action_type=execute 时必填）
这个 prompt 会发给 Claude Code (Opus) 执行。Opus 看不到摄像头和屏幕，所以你必须：
- 用文字描述你从图片中看到的所有相关细节
- 明确要产出什么（总结、翻译、代码修复等）
- 如果涉及文件，给出路径，Opus 可以直接读取
- 简洁但完整

## 执行层可用的 Skills（通过 Claude Code）
以下是执行层可以使用的能力，写 execution_prompt 时可以指定使用：
- /browse — 网页浏览和搜索
- /deep-research-pro — 深度研究
- /desearch-web-search — 网页搜索
- /send-email — 发送邮件
- /daily-news — 获取新闻
- /macos-calendar — 日历管理
- /mac-control — macOS 自动化（AppleScript, cliclick）
- /universal-translate — 翻译
- /summarize-pro — 总结
- /slack — Slack 消息
- /lark-im — 飞书消息
- /lark-doc — 飞书文档
- /lark-calendar — 飞书日历
- /github — GitHub 操作
- /apple-notes — Apple 备忘录
- /apple-reminders — Apple 提醒事项
- /spotify-player — Spotify 播放控制
- /weather — 天气查询
- /notion — Notion 操作
- /trello — Trello 看板
- /1password — 密码管理
- 以及更多...执行层可以读写文件、运行代码、操作系统
"""


class Reactor:
    """3-second tick observation engine with Haiku + Opus execution."""

    def __init__(
        self,
        collector: InputCollector,
        overlay: NativeOverlay,
        memory_dir: str = "memory",
        tick_interval: float = 3.0,
    ):
        self.collector = collector
        self.overlay = overlay
        self.memory = MemoryStore(memory_dir=memory_dir)
        self.tick_interval = tick_interval
        self._running = False
        self._react_round = 0
        self._last_act_time = 0
        self._min_act_gap = 10.0

        # Card context tracking for feedback
        self._card_contexts: dict[str, dict] = {}

        # Preference learning
        self._feedback_count_since_learn = 0
        self._last_learn_time = 0

        # Gemini client
        self._gemini = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))

        # Tick overlap protection
        self._tick_in_progress = False

        # Lazy-load Pillow for image compression
        self._pil_available = None

    async def start(self) -> None:
        self._running = True
        prefs = self.memory.get_preferences()
        logger.info(f"Reactor started (tick={self.tick_interval}s, "
                     f"observe={OBSERVE_MODEL.split('.')[-1]}, "
                     f"preferences={len(prefs.get('rules', []))} rules)")
        await self._tick_loop()

    async def _tick_loop(self) -> None:
        """Single unified loop — every tick_interval seconds."""
        try:
            while self._running:
                await self._tick()
                await asyncio.sleep(self.tick_interval)
        except asyncio.CancelledError:
            pass

    async def _tick(self) -> None:
        """One observation cycle."""
        if self._tick_in_progress:
            return  # Skip if previous tick still running

        self._react_round += 1
        self._tick_in_progress = True

        try:
            await self._tick_inner()
        finally:
            self._tick_in_progress = False

    async def _tick_inner(self) -> None:
        # Collect pending feedback
        self._collect_feedback()

        # Maybe learn preferences (background, non-blocking check)
        await self._maybe_learn_preferences()

        # Grab latest inputs
        snapshot = self.collector.get_snapshot(window_sec=5.0)
        if snapshot["total_events"] == 0:
            return


        # Build multimodal content
        content = self._build_content(snapshot)
        if not content:
            return

        # Push to thinking panel
        self.overlay.push_thinking([
            {"text": f"── Tick #{self._react_round} ──", "type": "separator"},
        ])
        self._push_input_summary(snapshot)

        # Call Haiku
        self.overlay.push_thinking([
            {"text": "Haiku 观察中 ...", "type": "reason"},
        ])

        try:
            system_prompt = self._build_system_prompt()
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, self._call_observe, content, system_prompt
            )
        except Exception as e:
            logger.error(f"Observe failed: {e}")
            self.overlay.push_thinking([
                {"text": f"观察失败: {e}", "type": "error"},
            ])
            return

        result = self._parse_response(response)
        if not result:
            self.overlay.push_thinking([
                {"text": "无法解析响应", "type": "error"},
            ])
            return

        # Meta-feedback
        meta = result.get("meta_feedback", "")
        if meta and len(meta.strip()) > 2:
            logger.info(f"[META] {meta}")
            self.memory.save_feedback({
                "type": "meta", "content": meta, "source": "voice",
            })
            self._feedback_count_since_learn += 1
            self.overlay.push_thinking([
                {"text": f"用户反馈: {meta}", "type": "feedback"},
            ])

        # Decide based on action_type
        reason = result.get("reason", "")
        action_type = result.get("action_type", "observe")

        # Backward compat: old should_act format
        if "should_act" in result and "action_type" not in result:
            action_type = "execute" if result.get("should_act") else "observe"

        if action_type == "reply":
            reply_text = result.get("reply", "")
            if reply_text:
                logger.info(f"[REPLY] {reply_text[:60]}")
                self.overlay.push_thinking([
                    {"text": f"推理: {reason[:60]}", "type": "reason"},
                    {"text": f"直接回复", "type": "action"},
                ])
                await self._direct_reply(reply_text, reason)
            else:
                self.overlay.push_thinking([
                    {"text": f"观察: {reason[:50]}", "type": "decision"},
                ])

        elif action_type == "execute":
            action = result.get("action", "")
            execution_prompt = result.get("execution_prompt", "")
            now = time.time()

            if now - self._last_act_time < self._min_act_gap:
                logger.info(f"[THROTTLE] {action}")
                self.overlay.push_thinking([
                    {"text": f"节流: {action[:40]}", "type": "decision"},
                ])
                return

            await self._execute(action, execution_prompt, reason)

        else:  # observe
            logger.debug(f"[OBSERVE] {reason[:60]}")
            self.overlay.push_thinking([
                {"text": f"观察: {reason[:50]}", "type": "decision"},
            ])

    # ── Direct Reply (fast, no Claude Code) ────────────────

    async def _direct_reply(self, reply_text: str, reason: str) -> None:
        """Haiku replies directly via overlay card — no Opus needed."""
        card_id = uuid.uuid4().hex[:8]
        now = time.time()

        self.overlay.close_all()
        self.overlay.show_card(
            title="Jarvis", body=reply_text,
            card_type="result", card_id=card_id, timeout=30,
        )
        self._last_act_time = now

        self.overlay.push_thinking([
            {"text": f"直接回复 ({len(reply_text)}字)", "type": "action"},
        ])

        self._card_contexts[card_id] = {
            "action": "direct_reply", "content": reply_text[:200],
            "trigger": "tick", "time": now,
        }
        self.memory.save_decision({
            "action": "direct_reply", "content": reply_text[:200],
            "trigger": "tick", "reason": reason, "card_id": card_id,
        })

    # ── Execution (Claude Code / Opus) ───────────────────

    async def _execute(self, action: str, execution_prompt: str, reason: str) -> None:
        """Haiku decided to act → Claude Code (Opus) executes."""
        card_id = uuid.uuid4().hex[:8]
        now = time.time()

        logger.info(f"[ACT] {action} (card={card_id})")
        self.overlay.push_thinking([
            {"text": f"推理: {reason[:60]}", "type": "reason"},
            {"text": f"行动: {action}", "type": "action"},
            {"text": "Claude Code (Opus) 执行中 ...", "type": "action"},
        ])

        # Show thinking card
        self.overlay.close_all()
        self.overlay.show_card(
            title=action[:60], body="Thinking ...",
            card_type="thinking", card_id=f"tmp_{card_id}", timeout=60,
        )

        # Execute
        body = ""
        if execution_prompt:
            try:
                loop = asyncio.get_event_loop()
                body = await loop.run_in_executor(
                    None, self._run_claude_code, execution_prompt
                )
            except Exception as e:
                logger.error(f"Execution failed: {e}")

        if not body:
            body = execution_prompt

        # Show result
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
            "trigger": "tick", "time": now,
        }
        self.memory.save_decision({
            "action": action, "content": body[:200],
            "trigger": "tick", "reason": reason, "card_id": card_id,
        })

        # Cleanup stale contexts
        stale = [c for c, v in self._card_contexts.items() if now - v["time"] > 300]
        for c in stale:
            del self._card_contexts[c]

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

    # ── Content Building ─────────────────────────────────────

    def _build_content(self, snapshot: dict) -> list[dict]:
        """Build compressed multimodal content for Haiku."""
        content: list[dict] = []

        # Camera (compressed)
        frames = snapshot["physiological"]["camera_frames"]
        if frames:
            img_b64 = self._compress_image(frames[-1].get("image_path"))
            if img_b64:
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
                })
                content.append({"type": "text", "text": "[摄像头] 用户面部/姿态。注意：是否在看屏幕？表情如何？"})

        # Desktop screenshot (compressed) + cursor focus area
        screenshots = snapshot["behavioral"]["desktop_screenshots"]
        if screenshots:
            img_path = screenshots[-1].get("image_path")
            img_b64 = self._compress_image(img_path)
            if img_b64:
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
                })

                # Get cursor position and crop focus area
                cursor_x, cursor_y = self._get_cursor_position()
                cursor_text = f"[桌面全屏] 光标位置: ({cursor_x}, {cursor_y})"

                # Crop around cursor for detail view
                cursor_crop_b64 = self._crop_cursor_area(img_path, cursor_x, cursor_y)
                if cursor_crop_b64:
                    content.append({"type": "text", "text": cursor_text})
                    content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": cursor_crop_b64},
                    })
                    content.append({"type": "text", "text": "[光标特写] 用户正在关注的区域。仔细阅读这里的文字和内容。"})
                else:
                    content.append({"type": "text", "text": cursor_text})

        # Audio — distinguish final vs in-progress speech
        transcriptions = snapshot["physiological"]["audio_transcriptions"]
        if transcriptions:
            now = time.time()
            seen = set()
            final_lines = []
            speaking_line = None

            for t in transcriptions[-10:]:
                text = t.get("text", "").strip()
                if not text or len(text) < 2 or text in seen:
                    continue
                seen.add(text)
                age = now - t.get("timestamp", 0)
                confidence = t.get("confidence", 1.0)

                if confidence >= 0.9 or age > 2.0:
                    final_lines.append(text)
                else:
                    speaking_line = text  # Latest in-progress

            parts = []
            if final_lines:
                parts.append("[语音（已说完）]\n" + "\n".join(f"- {l}" for l in final_lines[-5:]))
            if speaking_line:
                parts.append(f"[正在说...] {speaking_line}")

            if parts:
                content.append({"type": "text", "text": "\n".join(parts)})

        # Browser
        visits = snapshot["behavioral"]["browser_visits"]
        if visits:
            lines = [f"- {v.get('title', '?')} ({v.get('url', '?')})" for v in visits[-2:]]
            content.append({"type": "text", "text": "[浏览器]\n" + "\n".join(lines)})

        if not content:
            return []

        # Context
        ctx = []
        if self._last_act_time > 0:
            ctx.append(f"[上次行动] {time.time() - self._last_act_time:.0f}秒前")

        memory_ctx = self.memory.get_context_summary(hours=0.5)
        if memory_ctx:
            ctx.append(f"[记忆]\n{memory_ctx}")

        if ctx:
            content.append({"type": "text", "text": "\n\n".join(ctx)})

        return content

    def _compress_image(self, img_path: str | None) -> str | None:
        """Compress image to ~25% size for fast Haiku calls."""
        if not img_path or not os.path.exists(img_path):
            return None

        # Lazy check for Pillow
        if self._pil_available is None:
            try:
                from PIL import Image
                self._pil_available = True
            except ImportError:
                self._pil_available = False
                logger.warning("Pillow not installed — sending full-size images")

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

    def _get_cursor_position(self) -> tuple[int, int]:
        """Get macOS cursor position. Returns (x, y) in screen coordinates."""
        try:
            from AppKit import NSEvent, NSScreen
            loc = NSEvent.mouseLocation()
            # NSEvent gives bottom-left origin, convert to top-left
            screen_h = NSScreen.mainScreen().frame().size.height
            return int(loc.x), int(screen_h - loc.y)
        except Exception:
            return 0, 0

    def _crop_cursor_area(
        self, img_path: str | None, cursor_x: int, cursor_y: int,
        crop_size: int = 500, output_size: int = 300,
    ) -> str | None:
        """Crop and zoom the area around cursor from the full screenshot."""
        if not img_path or not os.path.exists(img_path) or not self._pil_available:
            return None
        if cursor_x == 0 and cursor_y == 0:
            return None
        try:
            from PIL import Image
            img = Image.open(img_path)

            # Scale cursor position to image coordinates
            # Screenshot might be Retina (2x), adjust
            scale = img.width / self._get_screen_width()

            cx = int(cursor_x * scale)
            cy = int(cursor_y * scale)
            half = int(crop_size * scale / 2)

            # Clamp to image bounds
            left = max(0, cx - half)
            top = max(0, cy - half)
            right = min(img.width, cx + half)
            bottom = min(img.height, cy + half)

            cropped = img.crop((left, top, right, bottom))
            resized = cropped.resize((output_size, output_size))

            buf = io.BytesIO()
            resized.save(buf, format="JPEG", quality=60)
            return base64.standard_b64encode(buf.getvalue()).decode()
        except Exception:
            return None

    def _get_screen_width(self) -> int:
        """Get main screen logical width."""
        try:
            from AppKit import NSScreen
            return int(NSScreen.mainScreen().frame().size.width)
        except Exception:
            return 1920

    def _push_input_summary(self, snapshot: dict) -> None:
        entries = []
        frames = snapshot["physiological"]["camera_frames"]
        if frames:
            entries.append({"text": f"摄像头: {len(frames)}帧", "type": "input"})
        screenshots = snapshot["behavioral"]["desktop_screenshots"]
        if screenshots:
            entries.append({"text": f"截屏: {len(screenshots)}张", "type": "input"})
        transcriptions = snapshot["physiological"]["audio_transcriptions"]
        if transcriptions:
            texts = [t.get("text", "") for t in transcriptions[-2:] if t.get("text")]
            if texts:
                entries.append({"text": f"语音: {' | '.join(t[:25] for t in texts)}", "type": "input"})
        if entries:
            self.overlay.push_thinking(entries)

    # ── Observe LLM (Haiku) ──────────────────────────────────

    def _call_observe(self, content: list[dict], system_prompt: str) -> str:
        """Gemini Flash observation call. Blocking."""
        # Convert Anthropic-style content to Gemini Parts
        parts = []
        for item in content:
            if item.get("type") == "text":
                parts.append(gtypes.Part(text=item["text"]))
            elif item.get("type") == "image":
                src = item["source"]
                parts.append(gtypes.Part(
                    inline_data=gtypes.Blob(
                        mime_type=src["media_type"],
                        data=base64.standard_b64decode(src["data"]),
                    )
                ))

        response = self._gemini.models.generate_content(
            model=OBSERVE_MODEL,
            contents=[gtypes.Content(role="user", parts=parts)],
            config=gtypes.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=12000,
                temperature=0.3,
            ),
        )
        return response.text

    # ── System Prompt ────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        prefs = self.memory.get_preferences()
        rules = prefs.get("rules", [])

        if rules:
            rules_text = "\n".join(f"- {r}" for r in rules)
            section = f"\n## 用户偏好（从互动中学到的）\n\n{rules_text}\n\n偏好优先于默认假设。\n"
        else:
            section = "\n## 用户偏好\n\n暂无。保持适度主动，通过反馈学习。\n"

        return SYSTEM_PROMPT_BASE + section + SYSTEM_PROMPT_OUTPUT

    # ── Feedback & Preference Learning ───────────────────────

    def _collect_feedback(self) -> None:
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
            logger.info(f"[FEEDBACK] {ftype} → {context.get('action', card_id)[:40]}")
            self.overlay.push_thinking([
                {"text": f"反馈: {ftype} → {context.get('action', card_id)[:30]}", "type": "feedback"},
            ])

    async def _maybe_learn_preferences(self) -> None:
        now = time.time()
        if not (
            self._feedback_count_since_learn >= 5
            or (now - self._last_learn_time > 1800 and self._feedback_count_since_learn > 0)
        ):
            return
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._learn_preferences)
            self._feedback_count_since_learn = 0
            self._last_learn_time = now
        except Exception as e:
            logger.error(f"Preference learning failed: {e}")

    def _learn_preferences(self) -> None:
        recent = self.memory.get_recent_feedback(hours=72.0, limit=50)
        if not recent:
            return
        prefs = self.memory.get_preferences()
        current_rules = prefs.get("rules", [])

        lines = []
        for f in recent:
            if f.get("type") == "meta":
                lines.append(f"- [语音] {f.get('content', '')}")
            else:
                lines.append(f"- [{f.get('type')}] {f.get('card_action', '')}")

        rules_text = "\n".join(f"- {r}" for r in current_rules) if current_rules else "（暂无）"
        prompt = f"""分析用户反馈，更新偏好规则。

反馈记录:
{chr(10).join(lines)}

当前规则:
{rules_text}

要求: 提取模式，不超过10条，输出 JSON: {{"rules": ["...", "..."]}}"""

        try:
            resp = self._gemini.models.generate_content(
                model=LEARN_MODEL,
                contents=prompt,
                config=gtypes.GenerateContentConfig(
                    max_output_tokens=12000,
                    temperature=0.2,
                ),
            )
            text = resp.text.strip()
            result = None
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                s, e = text.find("{"), text.rfind("}") + 1
                if s >= 0 and e > s:
                    try:
                        result = json.loads(text[s:e])
                    except json.JSONDecodeError:
                        pass
            if result and "rules" in result:
                self.memory.update_preferences({
                    "rules": result["rules"],
                    "last_synthesized": time.time(),
                })
                logger.info(f"[LEARN] {len(result['rules'])} rules")
                self.overlay.push_thinking([
                    {"text": f"偏好更新: {len(result['rules'])}条规则", "type": "action"},
                ])
        except Exception as e:
            logger.error(f"Learn LLM failed: {e}")

    # ── Response Parsing ─────────────────────────────────────

    def _parse_response(self, response: str) -> dict | None:
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            s = text.find("{")
            e = text.rfind("}") + 1
            if s >= 0 and e > s:
                try:
                    return json.loads(text[s:e])
                except json.JSONDecodeError:
                    pass
        logger.warning(f"Cannot parse: {text[:100]}")
        return None

    async def stop(self) -> None:
        self._collect_feedback()
        self._running = False
