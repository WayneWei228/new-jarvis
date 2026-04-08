"""
Reactor — 事件驱动的快速响应引擎。

单次 LLM 调用同时完成：感知分析 + 推理决策 + 产出内容。

Two trigger modes:
1. AUDIO    — 积累完整语音后触发（等说完再反应）
2. PERIODIC — 每 15s 背景观察一轮

反馈系统：
- 显式反馈：overlay 按钮（有用/关闭）
- 语音反馈：LLM 检测用户对 AI 行为的评价
- 隐式反馈：卡片超时 = 用户没在意
- 偏好学习：定期 LLM 分析反馈模式 → 更新 preferences.json
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import time
import uuid

from anthropic import AnthropicBedrock

from input import InputCollector
from brain.memory import MemoryStore
from executor.overlay import NativeOverlay

logger = logging.getLogger(__name__)

# Base system prompt — behavioral rules come from preferences, not hardcoded
REACTOR_BASE_PROMPT = """\
你是一个坐在用户旁边的聪明朋友。你能看到用户的摄像头画面、桌面屏幕、听到他们说的话、知道他们在浏览什么网页。

## 你的性格

你是一个有分寸的朋友，不是一个急于表现的助手。
你的分寸感不是来自固定规则，而是来自对这个用户的了解。

## 感知权重

根据用户的身体语言动态调整你关注的信息：
- **用户在看屏幕** → 屏幕内容是最重要的（正在读什么、写什么、看什么）
- **用户没看屏幕（在聊天、走动、吃东西）** → 语音和摄像头更重要，屏幕信息几乎忽略
- **用户在说话** → 仔细听他在说什么，判断是否有你能帮上的需求
"""

REACTOR_OUTPUT_PROMPT = """\
## 输出格式

输出 JSON（不要 markdown 代码块）：

{
  "should_act": true/false,
  "action": "你要做什么（一句话）",
  "execution_prompt": "给执行AI的详细指令（见下方规则）",
  "reason": "简短说明判断依据",
  "meta_feedback": "如果用户在对你/AI的行为给反馈（比如'别烦我'、'这个有用'、'你可以多说点'、'不要打断'），记录下来。其他情况留空字符串"
}

## execution_prompt 规则（只在 should_act=true 时需要）

你的决策会交给 Claude Opus（最强模型）来执行。Opus 看不到摄像头和屏幕，所以你需要：

- **描述完整上下文** — 用户在做什么、看到了什么关键内容、说了什么
- **任务要明确** — 具体要产出什么（总结、翻译、代码修复、建议等）
- **如果涉及文件** — 给出文件路径，Opus 可以直接读取和操作
- **语言** — 用中文指令，除非任务本身需要英文
- **控制长度** — 告诉 Opus 输出要简洁（除非用户需要详细内容）
"""


class Reactor:
    """Event-driven fast response engine with preference learning."""

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
        self._last_act_time = 0
        self._min_act_gap = 15.0
        self._audio_buffer: list[str] = []
        self._audio_silence_start: float = 0

        # Card context tracking for feedback matching
        self._card_contexts: dict[str, dict] = {}

        # Preference learning state
        self._feedback_count_since_learn = 0
        self._last_learn_time = 0
        self._learn_interval = 1800.0  # 30 minutes
        self._learn_feedback_threshold = 5

        # AWS Bedrock
        self._token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
        self._region = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1")

    async def start(self) -> None:
        """Start the reactor with two concurrent loops."""
        self._running = True
        prefs = self.memory.get_preferences()
        rule_count = len(prefs.get("rules", []))
        logger.info(f"Reactor started (periodic={self.periodic_interval}s, "
                     f"preferences={rule_count} rules)")

        await asyncio.gather(
            self._audio_watch_loop(),
            self._periodic_loop(),
        )

    async def _audio_watch_loop(self) -> None:
        """Watch for audio events with silence-based triggering."""
        last_audio_ts = 0

        try:
            while self._running:
                await asyncio.sleep(1.0)

                events = self.collector.get_events(
                    since=time.time() - 8.0, limit=50
                )
                audio_events = [
                    e for e in events
                    if e.source == "microphone" and e.data.get("text")
                ]

                if not audio_events:
                    if self._audio_buffer and time.time() - self._audio_silence_start > 2.0:
                        combined = " ".join(self._audio_buffer)
                        self._audio_buffer.clear()

                        if len(combined) > 8:
                            logger.info(f"[AUDIO TRIGGER] {combined[:80]}")
                            await self._react(trigger="audio", trigger_text=combined)
                    continue

                latest = audio_events[-1]
                latest_ts = latest.timestamp

                if latest_ts > last_audio_ts:
                    last_audio_ts = latest_ts
                    text = latest.data.get("text", "")
                    if text and len(text) > 2:
                        self._audio_buffer.append(text)
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
        """Run one reaction cycle: collect feedback → snapshot → LLM → overlay."""
        self._react_round = getattr(self, "_react_round", 0) + 1

        # 1. Collect any pending feedback from overlay
        self._collect_feedback()

        # 2. Maybe run preference learning
        await self._maybe_learn_preferences()

        now = time.time()
        self._last_react_time = now

        # ── Thinking: cycle start ──
        trigger_label = f"语音: {trigger_text[:40]}" if trigger == "audio" else "周期观察"
        self.overlay.push_thinking([
            {"text": f"── Cycle #{self._react_round} · {trigger_label} ──", "type": "separator"},
        ])

        # 3. Build multimodal content from recent events
        window = 15.0 if trigger == "periodic" else 10.0
        snapshot = self.collector.get_snapshot(window_sec=window)
        if snapshot["total_events"] == 0:
            self.overlay.push_thinking([
                {"text": "无输入事件，跳过", "type": "input"},
            ])
            return

        # ── Thinking: input summary ──
        self._push_input_summary(snapshot)

        content = self._build_content(snapshot, trigger, trigger_text)
        if not content:
            return

        # 4. Single LLM call with dynamic system prompt
        self.overlay.push_thinking([
            {"text": "调用 LLM ...", "type": "reason"},
        ])

        try:
            system_prompt = self._build_system_prompt()
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, self._call_llm, content, system_prompt
            )
        except Exception as e:
            logger.error(f"Reactor LLM call failed: {e}")
            self.overlay.push_thinking([
                {"text": f"LLM 调用失败: {e}", "type": "error"},
            ])
            return

        # 5. Parse response
        result = self._parse_response(response)
        if not result:
            self.overlay.push_thinking([
                {"text": "无法解析 LLM 响应", "type": "error"},
            ])
            return

        # 6. Handle meta-feedback (user commenting on AI behavior)
        meta = result.get("meta_feedback", "")
        if meta and len(meta.strip()) > 2:
            logger.info(f"[META FEEDBACK] {meta}")
            self.memory.save_feedback({
                "type": "meta",
                "content": meta,
                "trigger": trigger,
                "source": "voice",
            })
            self._feedback_count_since_learn += 1
            self.overlay.push_thinking([
                {"text": f"检测到用户反馈: {meta}", "type": "feedback"},
            ])

        # 7. Act or observe
        reason = result.get("reason", "")

        if result.get("should_act"):
            action = result.get("action", "")
            execution_prompt = result.get("execution_prompt", "")

            if now - self._last_act_time < self._min_act_gap:
                logger.info(f"[THROTTLE] {action} ({now - self._last_act_time:.0f}s since last)")
                self.overlay.push_thinking([
                    {"text": f"想行动但被节流: {action}", "type": "decision"},
                ])
                return

            card_id = uuid.uuid4().hex[:8]
            logger.info(f"[ACT] {action} (card={card_id})")
            logger.info(f"  → {reason[:80]}")

            self.overlay.push_thinking([
                {"text": f"推理: {reason[:80]}", "type": "reason"},
                {"text": f"行动: {action}", "type": "action"},
                {"text": "调用 Claude Code (Opus) ...", "type": "action"},
            ])

            # Show thinking card immediately
            self.overlay.close_all()
            self.overlay.show_card(
                title=action[:60],
                body="Thinking ...",
                card_type="thinking",
                card_id=f"tmp_{card_id}",
                timeout=60,
            )

            # Execute with Claude Code (Opus)
            body = ""
            if execution_prompt:
                try:
                    loop = asyncio.get_event_loop()
                    body = await loop.run_in_executor(
                        None, self._run_claude_code, execution_prompt
                    )
                except Exception as e:
                    logger.error(f"Claude Code execution failed: {e}")

            if not body:
                body = execution_prompt  # Fallback: show the prompt itself

            # Replace thinking card with result
            self.overlay.close_all()
            self.overlay.show_card(
                title=action[:60],
                body=body[:800],
                card_type="result",
                card_id=card_id,
                timeout=45,
            )
            self._last_act_time = now

            self.overlay.push_thinking([
                {"text": f"Opus 完成 ({len(body)}字)", "type": "action"},
            ])

            self._card_contexts[card_id] = {
                "action": action,
                "content": body[:200],
                "trigger": trigger,
                "trigger_text": trigger_text[:100],
                "time": now,
            }

            self.memory.save_decision({
                "action": action,
                "content": body[:200],
                "trigger": trigger,
                "reason": reason,
                "card_id": card_id,
            })

            stale = [cid for cid, ctx in self._card_contexts.items()
                     if now - ctx["time"] > 300]
            for cid in stale:
                del self._card_contexts[cid]
        else:
            logger.info(f"[OBSERVE] {reason[:80]}")
            self.overlay.push_thinking([
                {"text": f"观察: {reason[:60]}", "type": "decision"},
            ])

    def _push_input_summary(self, snapshot: dict) -> None:
        """Push a summary of collected inputs to the thinking panel."""
        entries = []

        frames = snapshot["physiological"]["camera_frames"]
        if frames:
            entries.append({"text": f"摄像头: {len(frames)} 帧", "type": "input"})

        screenshots = snapshot["behavioral"]["desktop_screenshots"]
        if screenshots:
            entries.append({"text": f"桌面截屏: {len(screenshots)} 张", "type": "input"})

        transcriptions = snapshot["physiological"]["audio_transcriptions"]
        if transcriptions:
            texts = [t.get("text", "") for t in transcriptions[-3:] if t.get("text")]
            if texts:
                preview = " | ".join(t[:30] for t in texts)
                entries.append({"text": f"语音: {preview}", "type": "input"})

        visits = snapshot["behavioral"]["browser_visits"]
        if visits:
            title = visits[-1].get("title", "?")[:40]
            entries.append({"text": f"浏览器: {title}", "type": "input"})

        if entries:
            self.overlay.push_thinking(entries)

    # ── Feedback System ──────────────────────────────────────

    def _collect_feedback(self) -> None:
        """Collect feedback from overlay buttons and save to memory."""
        feedbacks = self.overlay.get_feedback()
        for fb in feedbacks:
            card_id = fb.get("card_id", "")
            feedback_type = fb.get("feedback", "unknown")

            # Skip system-generated events
            if feedback_type == "closed_by_system":
                continue

            # Match to card context
            context = self._card_contexts.pop(card_id, {})

            self.memory.save_feedback({
                "type": feedback_type,  # helpful, dismissed, expired
                "card_id": card_id,
                "card_action": context.get("action", ""),
                "card_content": context.get("content", ""),
                "card_trigger": context.get("trigger", ""),
                "source": "overlay_button",
            })
            self._feedback_count_since_learn += 1

            logger.info(f"[FEEDBACK] {feedback_type} for '{context.get('action', card_id)}'")
            self.overlay.push_thinking([
                {"text": f"用户反馈: {feedback_type} → {context.get('action', card_id)[:40]}", "type": "feedback"},
            ])

    async def _maybe_learn_preferences(self) -> None:
        """Periodically synthesize feedback into preference rules via LLM."""
        now = time.time()
        should_learn = (
            self._feedback_count_since_learn >= self._learn_feedback_threshold
            or (
                now - self._last_learn_time > self._learn_interval
                and self._feedback_count_since_learn > 0
            )
        )
        if not should_learn:
            return

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._learn_preferences)
            self._feedback_count_since_learn = 0
            self._last_learn_time = now
        except Exception as e:
            logger.error(f"Preference learning failed: {e}")

    def _learn_preferences(self) -> None:
        """Use LLM to analyze feedback patterns and update preferences."""
        recent_feedback = self.memory.get_recent_feedback(hours=72.0, limit=50)
        if not recent_feedback:
            return

        current_prefs = self.memory.get_preferences()
        current_rules = current_prefs.get("rules", [])

        # Format feedback for LLM
        feedback_lines = []
        for f in recent_feedback:
            ftype = f.get("type", "?")
            if ftype == "meta":
                feedback_lines.append(f"- [语音反馈] {f.get('content', '')}")
            else:
                action = f.get("card_action", "")
                trigger = f.get("card_trigger", "")
                feedback_lines.append(
                    f"- [{ftype}] 触发={trigger}, 内容=\"{action}\""
                )

        feedback_text = "\n".join(feedback_lines) or "（无反馈）"
        rules_text = "\n".join(f"- {r}" for r in current_rules) if current_rules else "（暂无）"

        prompt = f"""你是一个用户偏好分析器。根据用户与AI助手的交互反馈，提取和更新用户偏好规则。

## 反馈类型说明
- helpful = 用户点了"有用"按钮（正面）
- dismissed = 用户点了"关闭"按钮（负面，不想要这个）
- expired = 卡片超时自动消失（用户没注意或不在意）
- 语音反馈 = 用户口头对AI行为的评价

## 最近反馈记录
{feedback_text}

## 当前偏好规则
{rules_text}

## 任务
分析以上反馈，提取模式，输出更新后的偏好规则。

要求：
- 从反馈中提取行为模式，不是逐条复述
- 如果新反馈否定了旧规则，移除旧规则
- 规则要具体、可操作（"用户喜欢X" 比 "注意用户偏好" 好）
- 不超过 10 条规则
- 输出 JSON：{{"rules": ["规则1", "规则2", ...]}}"""

        try:
            client = AnthropicBedrock(
                aws_region=self._region,
                api_key=self._token,
            )
            response = client.messages.create(
                model="global.anthropic.claude-opus-4-6-v1",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            # Parse JSON
            result = None
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    try:
                        result = json.loads(text[start:end])
                    except json.JSONDecodeError:
                        pass

            if result and "rules" in result:
                rules = result["rules"]
                self.memory.update_preferences({
                    "rules": rules,
                    "last_synthesized": time.time(),
                    "total_feedback_analyzed": current_prefs.get(
                        "total_feedback_analyzed", 0
                    ) + len(recent_feedback),
                })
                logger.info(f"[LEARN] Updated preferences: {len(rules)} rules")
                for r in rules:
                    logger.info(f"  • {r}")
                self.overlay.push_thinking([
                    {"text": f"偏好学习: 更新了 {len(rules)} 条规则", "type": "action"},
                ])

        except Exception as e:
            logger.error(f"Preference learning LLM call failed: {e}")

    # ── Dynamic System Prompt ────────────────────────────────

    def _build_system_prompt(self) -> str:
        """Build system prompt with dynamic user preferences."""
        prefs = self.memory.get_preferences()
        rules = prefs.get("rules", [])

        if rules:
            rules_text = "\n".join(f"- {r}" for r in rules)
            prefs_section = f"""
## 用户偏好（从过往互动中学到的）

{rules_text}

这些偏好来自用户的真实反馈，请据此调整你的行为。偏好优先于默认假设。
"""
        else:
            prefs_section = """
## 用户偏好

暂无偏好记录 — 你刚开始和这个用户互动。
默认策略：保持适度主动，观察用户反应。
当你不确定时，可以尝试行动，通过用户反馈来学习。
"""

        return REACTOR_BASE_PROMPT + prefs_section + REACTOR_OUTPUT_PROMPT

    # ── Content Building ─────────────────────────────────────

    def _build_content(
        self, snapshot: dict, trigger: str, trigger_text: str
    ) -> list[dict]:
        """Build multimodal content for single LLM call."""
        content: list[dict] = []

        # Camera frame
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

        # Audio transcriptions
        transcriptions = snapshot["physiological"]["audio_transcriptions"]
        if transcriptions:
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

        if trigger == "audio" and trigger_text:
            ctx_parts.append(f"[触发原因] 用户说了: \"{trigger_text}\"")
            ctx_parts.append("请判断用户是否在对你说话或表达需求。注意也检测用户是否在对你的行为给反馈。")
        else:
            ctx_parts.append(f"[触发原因] 定期观察 (每{self.periodic_interval}s)")

        if self._last_act_time > 0:
            gap = time.time() - self._last_act_time
            ctx_parts.append(f"[上次行动] {gap:.0f}秒前")

        memory_ctx = self.memory.get_context_summary(hours=0.5)
        if memory_ctx:
            ctx_parts.append(f"[最近记忆]\n{memory_ctx}")

        content.append({"type": "text", "text": "\n\n".join(ctx_parts)})

        return content

    # ── Claude Code Execution ────────────────────────────────

    def _run_claude_code(self, prompt: str) -> str:
        """Call Claude Code CLI (Opus) for high-quality execution. Blocking."""
        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = result.stdout.strip()
            if result.returncode == 0 and output:
                return output
            if result.stderr:
                logger.warning(f"Claude Code stderr: {result.stderr[:200]}")
            return ""
        except subprocess.TimeoutExpired:
            logger.warning("Claude Code timed out (60s)")
            return ""
        except FileNotFoundError:
            logger.warning("claude CLI not found — install Claude Code")
            return ""

    # ── LLM Call ─────────────────────────────────────────────

    def _call_llm(self, content: list[dict], system_prompt: str) -> str:
        """Single LLM call (blocking)."""
        client = AnthropicBedrock(
            aws_region=self._region,
            api_key=self._token,
        )
        response = client.messages.create(
            model="global.anthropic.claude-opus-4-6-v1",
            max_tokens=1024,
            system=system_prompt,
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
        # Collect final feedback before stopping
        self._collect_feedback()
        self._running = False
