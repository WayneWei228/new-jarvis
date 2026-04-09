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

import anthropic
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
        profile: str = "",
    ):
        self.collector = collector
        self.overlay = overlay
        self.memory = MemoryStore(memory_dir=memory_dir)
        self.tick_interval = tick_interval

        # Load user profile
        self._profile = self._load_profile(profile)
        self._running = False
        self._react_round = 0
        self._last_act_time = 0
        self._min_act_gap = 10.0

        # Card context tracking for feedback
        self._card_contexts: dict[str, dict] = {}

        # Preference learning
        self._feedback_count_since_learn = 0
        self._last_learn_time = 0

        # Gemini client (observation)
        self._gemini = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))

        # Anthropic client (execution, if needed)
        # self._opus = anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "ap-northeast-1"))

        # Tick overlap protection
        self._tick_in_progress = False

        # Lazy-load Pillow for image compression
        self._pil_available = None

        # Designer workflow: accumulated bookmarks for trigger detection
        self._design_bookmarks: list[dict] = []
        self._design_doc_triggered = False

        # Conversation history — rolling log of Jarvis actions/replies visible to Gemini
        self._conversation_history: list[dict] = []  # {time, role, text}
        self._history_max = 30  # keep last 30 entries

    @staticmethod
    def _load_profile(name: str) -> dict:
        """Load a user profile from profiles/<name>.json."""
        if not name:
            return {}
        from pathlib import Path
        profile_path = Path(__file__).parent / "profiles" / f"{name}.json"
        if profile_path.exists():
            with open(profile_path, "r", encoding="utf-8") as f:
                profile = json.load(f)
            logger.info(f"Profile loaded: {profile.get('name', name)}")
            return profile
        logger.warning(f"Profile not found: {profile_path}")
        return {}

    def _build_user_section(self) -> str:
        """Build the '你对这个用户的了解' section from profile."""
        if not self._profile:
            return ""

        lines = ["## 你对这个用户的了解\n"]

        user = self._profile.get("user", {})
        if user.get("role"):
            lines.append(f"你知道他是{user['role']}。")
        if user.get("context"):
            lines.append(user["context"])
        for habit in user.get("habits", []):
            lines.append(f"你见过他的工作模式：{habit}")
        for tool in user.get("tools", []):
            lines.append(f"他{tool}。")

        personality = self._profile.get("personality", {})
        if personality.get("intuition"):
            lines.append("\n作为朋友，你能做的：")
            for item in personality["intuition"]:
                lines.append(f"- {item}")
        if personality.get("toolchain"):
            lines.append(f"\n你了解他的工具链：{'、'.join(personality['toolchain'])}")

        lines.append("\n这些不是规则，是你作为朋友的直觉。用你自己的判断。")
        return "\n".join(lines)

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

        # Check for new design bookmarks (accumulate across ticks)
        await self._check_design_bookmark_trigger(snapshot)

        # Record user speech to conversation history (deduplicated)
        self._record_user_speech(snapshot)

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

    # ── Conversation History ────────────────────────────────

    def _record_history(self, role: str, text: str, **extra) -> None:
        """Append to rolling conversation history visible to Gemini."""
        entry = {"time": time.time(), "role": role, "text": text}
        entry.update(extra)
        self._conversation_history.append(entry)
        # Trim to max
        if len(self._conversation_history) > self._history_max:
            self._conversation_history = self._conversation_history[-self._history_max:]

    def _format_history(self) -> str:
        """Format recent history as text block for Gemini context."""
        if not self._conversation_history:
            return ""
        now = time.time()
        lines = []
        for entry in self._conversation_history:
            age = now - entry["time"]
            if age > 1800:  # skip entries older than 30 min
                continue
            ago = f"{int(age)}秒前" if age < 60 else f"{int(age/60)}分钟前"
            role = entry["role"]
            text = entry["text"]
            if role == "jarvis_reply":
                lines.append(f"- [{ago}] 你回复了: {text[:100]}")
            elif role == "jarvis_action":
                lines.append(f"- [{ago}] 你执行了: {text[:150]}")
            elif role == "user_speech":
                lines.append(f"- [{ago}] 用户说: {text[:100]}")
            elif role == "user_feedback":
                lines.append(f"- [{ago}] 用户反馈: {text[:60]}")
        if not lines:
            return ""
        return "[对话历史]\n" + "\n".join(lines[-15:])  # last 15 entries

    _last_recorded_speech: set = set()

    def _record_user_speech(self, snapshot: dict) -> None:
        """Record final (confirmed) user speech to conversation history, deduplicated."""
        transcriptions = snapshot["physiological"]["audio_transcriptions"]
        if not transcriptions:
            return
        now = time.time()
        for t in transcriptions[-5:]:
            text = t.get("text", "").strip()
            confidence = t.get("confidence", 1.0)
            age = now - t.get("timestamp", 0)
            # Only record confirmed speech, not in-progress
            if text and len(text) > 3 and (confidence >= 0.9 or age > 2.0):
                # Dedup by text content
                if text not in self._last_recorded_speech:
                    self._last_recorded_speech.add(text)
                    self._record_history("user_speech", text)
                    # Keep dedup set bounded
                    if len(self._last_recorded_speech) > 50:
                        self._last_recorded_speech = set(list(self._last_recorded_speech)[-30:])

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
        self._record_history("jarvis_reply", reply_text)

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

    # ── Designer Workflow Auto-Trigger ──────────────────

    async def _check_design_bookmark_trigger(self, snapshot: dict) -> None:
        """Accumulate design bookmarks across ticks. Auto-trigger Feishu doc when threshold hit."""
        if self._design_doc_triggered:
            return

        workflow = self._profile.get("workflow", {})
        if not workflow.get("enabled"):
            return

        design_sites = workflow.get("design_sites", [])
        threshold = workflow.get("bookmark_threshold", 3)

        # Check new bookmarks from this tick's snapshot
        new_bookmarks = snapshot["behavioral"].get("browser_bookmarks", [])
        for bm in new_bookmarks:
            url = bm.get("url", "")
            title = bm.get("title", "")
            # Check if already tracked
            if any(b["url"] == url for b in self._design_bookmarks):
                continue
            # Accept ALL bookmarks (not just design sites) — user is curating
            self._design_bookmarks.append({"url": url, "title": title, "timestamp": bm.get("timestamp", time.time())})
            logger.info(f"[DESIGNER] Bookmark tracked: {title[:40]} ({len(self._design_bookmarks)}/{threshold})")

        # Also check wider window for bookmarks we may have missed
        wide_snapshot = self.collector.get_snapshot(window_sec=300.0)
        for bm in wide_snapshot["behavioral"].get("browser_bookmarks", []):
            url = bm.get("url", "")
            title = bm.get("title", "")
            if any(b["url"] == url for b in self._design_bookmarks):
                continue
            self._design_bookmarks.append({"url": url, "title": title, "timestamp": bm.get("timestamp", time.time())})

        if len(self._design_bookmarks) >= threshold:
            logger.info(f"[DESIGNER] {len(self._design_bookmarks)} bookmarks accumulated, triggering doc")
            self._design_doc_triggered = True
            await self._trigger_design_feishu_doc()

    async def _trigger_design_feishu_doc(self) -> None:
        """Create one Feishu doc per bookmark, show all links, auto-open."""
        bookmarks = self._design_bookmarks
        card_id = uuid.uuid4().hex[:8]
        now = time.time()

        titles = "、".join(b["title"][:15] for b in bookmarks[:3])
        self.overlay.push_thinking([
            {"text": f"他收藏了好几个灵感 ({titles}...)，帮他整理一下", "type": "reason"},
        ])
        self.overlay.close_all()
        self.overlay.show_card(
            title="帮你整理灵感中...", body=f"正在逐个分析 {len(bookmarks)} 个收藏",
            card_type="thinking", card_id=f"tmp_{card_id}", timeout=180,
        )

        # Create one doc per bookmark (blocking)
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, self._create_per_bookmark_docs, bookmarks)

        # Clear bookmarks from content so Gemini doesn't re-trigger
        self._design_bookmarks.clear()

        self.overlay.close_all()
        success = [r for r in results if r.get("doc_url")]
        if success:
            lines = [f"整理好了 {len(success)} 个灵感文档:\n"]
            for r in success:
                lines.append(f"[{r['title']}]({r['doc_url']})")
            body = self._make_urls_clickable("\n".join(lines))
            self.overlay.show_card(
                title="灵感整理完成", body=body,
                card_type="result", card_id=card_id, timeout=90,
            )
            # Auto-open all docs & record to history
            for r in success:
                subprocess.Popen(["open", r["doc_url"]])
                self._record_history(
                    "jarvis_action",
                    f"为「{r['title']}」创建了飞书灵感文档: {r['doc_url']}",
                    doc_url=r["doc_url"], doc_title=r["title"],
                )
            logger.info(f"[DESIGNER] {len(success)} docs created and opened")
        else:
            self.overlay.show_card(
                title="整理失败", body="飞书文档创建出了点问题",
                card_type="warning", card_id=card_id, timeout=30,
            )

        self._last_act_time = time.time()
        self._card_contexts[card_id] = {
            "action": "design_feishu_doc", "content": f"{len(success)} docs",
            "trigger": "bookmarks", "time": now,
        }

    def _create_per_bookmark_docs(self, bookmarks: list[dict]) -> list[dict]:
        """Create one Feishu doc per bookmark using ThreadPool for parallelism."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        cwd = os.path.dirname(__file__) or "."

        def process_one(bm: dict) -> dict:
            url = bm["url"]
            title = bm["title"]
            logger.info(f"[DESIGNER] Processing: {title}")
            screenshot_path = None
            tmp_md = None

            try:
                # Phase 1: Fetch content + screenshot in parallel via threads
                content = self._fetch_url_content(url)
                screenshot_path = self._take_screenshot(url, title)

                # Phase 2: Gemini analysis (with screenshot image for JS-heavy pages)
                markdown = self._gemini_analyze(content, title, url, screenshot_path)
                if not markdown:
                    return {"title": title, "doc_url": None}

                # Phase 3: Create Feishu doc
                tmp_md = os.path.join(cwd, f"_tmp_{uuid.uuid4().hex[:6]}.md")
                with open(tmp_md, "w", encoding="utf-8") as f:
                    f.write(markdown)

                r = subprocess.run(
                    ["lark-cli", "docs", "+create", "--as", "user",
                     "--title", f"{title} - 灵感分析",
                     "--markdown", f"@{os.path.basename(tmp_md)}"],
                    capture_output=True, text=True, timeout=30, cwd=cwd,
                )
                if r.returncode != 0:
                    logger.error(f"lark-cli failed for {title}: {r.stderr[:100]}")
                    return {"title": title, "doc_url": None}

                out = json.loads(r.stdout)
                doc_url = out.get("data", {}).get("doc_url", "")
                doc_id = out.get("data", {}).get("doc_id", "")

                # Phase 4: Insert screenshot
                if doc_id and screenshot_path and os.path.exists(screenshot_path):
                    import shutil
                    ss_name = f"_ss_{uuid.uuid4().hex[:6]}.png"
                    ss_dest = os.path.join(cwd, ss_name)
                    shutil.copy2(screenshot_path, ss_dest)
                    subprocess.run(
                        ["lark-cli", "docs", "+media-insert", "--as", "user",
                         "--doc", doc_id, "--file", ss_name,
                         "--type", "image", "--align", "center",
                         "--caption", title[:50]],
                        capture_output=True, timeout=60, cwd=cwd,
                    )
                    try:
                        os.unlink(ss_dest)
                    except OSError:
                        pass

                logger.info(f"[DESIGNER] Doc created: {title} → {doc_url}")
                return {"title": title, "doc_url": doc_url}

            except Exception as e:
                logger.error(f"Doc creation failed for {title}: {e}")
                return {"title": title, "doc_url": None}
            finally:
                for p in [tmp_md, screenshot_path]:
                    if p and os.path.exists(p):
                        try:
                            os.unlink(p)
                        except OSError:
                            pass

        # Process all bookmarks in parallel (max 3 concurrent)
        results = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(process_one, bm): bm for bm in bookmarks}
            for future in as_completed(futures):
                results.append(future.result())

        # Sort results to match original bookmark order
        bm_order = {bm["url"]: i for i, bm in enumerate(bookmarks)}
        results.sort(key=lambda r: bm_order.get(
            next((bm["url"] for bm in bookmarks if bm["title"] == r["title"]), ""), 99
        ))
        return results

    def _gemini_analyze(self, content: str, title: str, url: str, screenshot_path: str | None) -> str | None:
        """Generate Lark markdown via Gemini Flash. Sends screenshot as image for JS-heavy pages."""
        text_prompt = f"""为以下网页生成一份 Lark-flavored Markdown 设计灵感分析文档。

标题: {title}
URL: {url}
页面内容:
{content[:3000] if content else '(JS渲染页面，请根据截图分析)'}

要求：
1. 开头 <callout> 概述这个作品的核心设计亮点
2. 基础信息（标题、URL、平台）用 <callout emoji="📋" background-color="light-green">
3. 详细分析：视觉风格、配色方案、布局结构、交互设计、技术栈
4. <callout emoji="💡" background-color="light-yellow"> 技术要点和可借鉴之处
5. 尾部 <callout emoji="🔗" background-color="light-purple"> 原始链接

只输出 Lark Markdown，不要代码块包裹。"""

        # Build multimodal parts — include screenshot for visual analysis
        parts = [gtypes.Part(text=text_prompt)]
        if screenshot_path and os.path.exists(screenshot_path):
            try:
                with open(screenshot_path, "rb") as f:
                    img_data = f.read()
                parts.insert(0, gtypes.Part(
                    inline_data=gtypes.Blob(mime_type="image/png", data=img_data)
                ))
            except Exception:
                pass

        # Retry on transient SSL/network errors
        for attempt in range(3):
            try:
                resp = self._gemini.models.generate_content(
                    model=OBSERVE_MODEL,
                    contents=[gtypes.Content(role="user", parts=parts)],
                    config=gtypes.GenerateContentConfig(max_output_tokens=4000, temperature=0.3),
                )
                return resp.text
            except Exception as e:
                if attempt < 2 and any(k in str(e) for k in ("SSL", "EOF", "Connection", "reset")):
                    logger.warning(f"Gemini retry {attempt+1}/2 for {title}: {e}")
                    time.sleep(2)
                    continue
                logger.error(f"Gemini failed for {title}: {e}")
                return None

    def _fetch_url_content(self, url: str) -> str:
        """Fetch URL content via curl. Blocking."""
        try:
            result = subprocess.run(
                ["curl", "-sL", "--max-time", "10", url],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout:
                # Strip HTML tags for a rough text extraction
                import re
                text = re.sub(r'<script[^>]*>.*?</script>', '', result.stdout, flags=re.DOTALL)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                return text[:3000]
        except Exception:
            pass
        return ""

    def _take_screenshot(self, url: str, title: str) -> str | None:
        """Take headless Chrome screenshot. Blocking. Returns path or None."""
        import tempfile
        screenshot_path = tempfile.mktemp(suffix=".png", prefix="jarvis_ss_")
        try:
            result = subprocess.run(
                ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "--headless", "--disable-gpu",
                 f"--screenshot={screenshot_path}",
                 "--window-size=1440,900",
                 "--virtual-time-budget=8000",
                 url],
                capture_output=True, timeout=20,
            )
            if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                return screenshot_path
        except Exception:
            pass
        if os.path.exists(screenshot_path):
            os.unlink(screenshot_path)
        return None

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

        # Extract URLs and convert to clickable markdown links
        body = self._make_urls_clickable(body)

        # Show result
        self.overlay.close_all()
        self.overlay.show_card(
            title=action[:60], body=body[:800],
            card_type="result", card_id=card_id, timeout=45,
        )
        self._last_act_time = now
        self._record_history("jarvis_action", f"{action}: {body[:150]}")

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
                capture_output=True, text=True, timeout=300,
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

        # Browser visits
        visits = snapshot["behavioral"]["browser_visits"]
        if visits:
            lines = [f"- {v.get('title', '?')} ({v.get('url', '?')})" for v in visits[-5:]]
            content.append({"type": "text", "text": "[浏览器]\n" + "\n".join(lines)})

        # Browser bookmarks — use accumulated list from designer workflow tracking
        if self._design_bookmarks:
            bm_lines = [f"- {b['title']} ({b['url']})" for b in self._design_bookmarks[-10:]]
            content.append({"type": "text", "text": f"[收藏] 用户已收藏 {len(self._design_bookmarks)} 个页面:\n" + "\n".join(bm_lines)})
        else:
            bookmarks = snapshot["behavioral"].get("browser_bookmarks", [])
            if bookmarks:
                bm_lines = [f"- {b.get('title', '?')} ({b.get('url', '?')})" for b in bookmarks[-10:]]
                content.append({"type": "text", "text": f"[收藏] 用户最近收藏了 {len(bookmarks)} 个页面:\n" + "\n".join(bm_lines)})

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
        sections = [SYSTEM_PROMPT_BASE]

        # User profile
        user_section = self._build_user_section()
        if user_section:
            sections.append(user_section)

        # Learned preferences
        prefs = self.memory.get_preferences()
        rules = prefs.get("rules", [])
        if rules:
            rules_text = "\n".join(f"- {r}" for r in rules)
            sections.append(f"\n## 用户偏好（从互动中学到的）\n\n{rules_text}\n\n偏好优先于默认假设。\n")
        else:
            sections.append("\n## 用户偏好\n\n暂无。保持适度主动，通过反馈学习。\n")

        # Workflow state from profile
        workflow_ctx = self._get_workflow_context()
        if workflow_ctx:
            sections.append(f"\n## 当前工作流状态\n\n{workflow_ctx}\n")

        # Conversation history
        history = self._format_history()
        if history:
            sections.append(f"\n{history}\n")

        sections.append(SYSTEM_PROMPT_OUTPUT)
        return "\n".join(sections)

    def _get_workflow_context(self) -> str:
        """Check recent activity against profile workflow config and return context hints."""
        workflow = self._profile.get("workflow", {})
        if not workflow.get("enabled"):
            return ""

        target_sites = workflow.get("design_sites", [])
        threshold = workflow.get("bookmark_threshold", 3)

        snapshot = self.collector.get_snapshot(window_sec=120.0)
        bookmarks = snapshot["behavioral"].get("browser_bookmarks", [])
        visits = snapshot["behavioral"].get("browser_visits", [])

        # Count workflow-related bookmarks
        related_bookmarks = [
            bm for bm in bookmarks
            if any(site in bm.get("url", "") for site in target_sites)
        ]

        # Count workflow-related visits
        related_visits = [
            v for v in visits
            if any(site in v.get("url", "") for site in target_sites)
        ]

        # Check if user is viewing a Feishu doc
        viewing_feishu = any(
            "feishu.cn/docx" in v.get("url", "") or "larksuite.com/docx" in v.get("url", "")
            for v in visits[-3:]
        ) if visits else False

        parts = []
        if related_bookmarks:
            parts.append(f"他收藏了 {len(related_bookmarks)} 个相关页面")
            if len(related_bookmarks) >= threshold:
                parts.append("收藏不少了，可以考虑帮他整理一下")
        if related_visits:
            parts.append(f"他一直在逛相关网站")
        if viewing_feishu:
            parts.append("他在看飞书文档 — 留意一下他对内容的反应")

        return "\n".join(parts)

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

    # ── URL Processing ───────────────────────────────────────

    @staticmethod
    def _make_urls_clickable(text: str) -> str:
        """Convert bare URLs in text to markdown [title](url) links for overlay."""
        import re
        # Don't touch URLs that are already in markdown link format
        # Match bare URLs not already inside [...](...)
        def replace_url(m):
            url = m.group(0)
            if "feishu.cn" in url or "larksuite.com" in url:
                return f"[查看飞书文档]({url})"
            return f"[打开链接]({url})"

        # Skip URLs already in markdown links
        parts = re.split(r'(\[[^\]]+\]\([^)]+\))', text)
        result = []
        for part in parts:
            if part.startswith('[') and '](' in part:
                result.append(part)  # Already a markdown link
            else:
                result.append(re.sub(r'https?://[^\s<>\'")\]]+', replace_url, part))
        return ''.join(result)

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
