"""
Brain Module — 持续推理引擎，读取用户状态和记忆，输出决策。

Watches for new user_status_*.md files, combines with Memory Store context,
calls LLM to reason about how to help the user, and outputs decision JSON.

Brain does NOT:
- Execute any action
- Interact with the user directly
- Modify any system state (except writing decisions)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from anthropic import AnthropicBedrock

from brain.memory import MemoryStore

logger = logging.getLogger(__name__)

BRAIN_SYSTEM_PROMPT = """\
你是一个全能智能助手的"大脑"。你持续观察用户的实时状态，自由思考如何帮助用户。

你会收到两部分信息：
1. **当前用户状态** — 实时多模态感知（摄像头、桌面截屏、语音、浏览器）生成的用户状态描述
2. **记忆上下文** — 过去的决策、执行结果、用户反馈、用户偏好

## 你的任务

像一个无所不能的私人助理一样思考：观察用户正在做什么，推断他需要什么，然后决定你要做什么来帮他。

你没有预设的行动列表。你可以决定做**任何事情**，只要它对用户有帮助。举几个例子（但不限于此）：
- 帮用户搜索信息、总结文章、翻译内容
- 写代码、调试、生成文档
- 提醒用户休息、喝水、站起来走走
- 帮用户整理笔记、组织想法
- 预测用户接下来需要什么，提前准备
- 发现用户遇到困难时主动提供帮助
- 帮用户回忆之前看过的内容
- 或者任何你认为有价值的事情

## 输出格式

输出一个JSON对象（不要包含markdown代码块标记）：

{
  "action": "你要做什么（自由描述）",
  "reason": "为什么这样做（你的推理过程）",
  "plan": "具体怎么执行（分步骤描述）",
  "params": { ... 任何相关参数 ... },
  "priority": "high/medium/low",
  "confidence": 0.0-1.0
}

## 决策原则

1. **自由思考** — 不要局限于固定类型，根据真实情况决定最有价值的行动
2. **不要过度打扰** — 用户专注时，观察即可，不必每次都行动
3. **避免重复** — 查看记忆，不要重复最近已经做过的事
4. **信心校准** — 对自己的判断诚实，不确定就说不确定
5. **像人一样思考** — 想象你是坐在用户旁边的一个聪明朋友，你会怎么帮他？
"""


class Brain:
    """Continuous reasoning loop that watches user status and outputs decisions."""

    def __init__(
        self,
        status_dir: str = "input/user_status",
        decision_dir: str = "brain/decisions",
        memory_dir: str = "memory",
        interval_sec: float = 35.0,
        notifier=None,
    ):
        self.status_dir = Path(status_dir)
        self.decision_dir = Path(decision_dir)
        self.interval_sec = interval_sec
        self._running = False
        self._round = 0
        self._last_status_file: str | None = None
        self._notifier = notifier

        # Memory store
        self.memory = MemoryStore(memory_dir=memory_dir)

        # AWS Bedrock
        self._token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
        self._region = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1")

    async def start(self) -> None:
        """Start the continuous reasoning loop."""
        self.decision_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        logger.info(f"Brain started (every {self.interval_sec}s, region={self._region})")

        try:
            while self._running:
                await asyncio.sleep(self.interval_sec)
                await self._think()
        except asyncio.CancelledError:
            logger.info("Brain stopped")

    async def _think(self) -> None:
        """Run one reasoning round."""
        self._round += 1

        # 1. Read the latest user status
        status_text = self._read_latest_status()
        if not status_text:
            logger.debug(f"Brain round {self._round}: no new status, skipping")
            return

        # 2. Read memory context
        memory_context = self.memory.get_context_summary(hours=1.0)

        # 3. Build the prompt
        prompt = self._build_prompt(status_text, memory_context)

        # 4. Call LLM
        logger.info(f"Brain round {self._round}: thinking...")
        if self._notifier:
            await self._notifier.push_event("brain_thinking", {
                "action": "Analyzing your current state...",
                "reason": f"Round {self._round}",
            })
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self._call_llm, prompt)
        except Exception as e:
            logger.error(f"Brain LLM call failed: {e}")
            return

        # 5. Parse and save decision
        decision = self._parse_decision(response)
        if decision:
            self._save_decision(decision)
            action = decision.get("action", "unknown")
            logger.info(
                f"Brain round {self._round}: {action} "
                f"(confidence={decision.get('confidence', '?')}, "
                f"priority={decision.get('priority', '?')})"
            )
            logger.info(f"  Reason: {decision.get('reason', '')[:150]}")
        else:
            logger.warning(f"Brain round {self._round}: failed to parse decision")
            logger.debug(f"Raw response: {response[:300]}")

    def _read_latest_status(self) -> str | None:
        """Read the most recent user_status file. Returns None if no new file."""
        if not self.status_dir.exists():
            return None

        status_files = sorted(self.status_dir.glob("status_*.md"))
        if not status_files:
            return None

        latest = status_files[-1]
        latest_name = latest.name

        # Skip if we already processed this file
        if latest_name == self._last_status_file:
            return None

        self._last_status_file = latest_name
        return latest.read_text(encoding="utf-8")

    def _build_prompt(self, status_text: str, memory_context: str) -> str:
        """Build the user message for the LLM."""
        parts = [f"## 当前用户状态\n\n{status_text}"]

        if memory_context:
            parts.append(f"## 记忆上下文\n\n{memory_context}")
        else:
            parts.append("## 记忆上下文\n\n（暂无历史记录，这是第一轮推理）")

        parts.append("请根据以上信息，输出你的决策JSON。")
        return "\n\n".join(parts)

    def _call_llm(self, prompt: str) -> str:
        """Call Claude via AWS Bedrock (blocking, run in executor)."""
        client = AnthropicBedrock(
            aws_region=self._region,
            api_key=self._token,
        )
        response = client.messages.create(
            model="apac.anthropic.claude-sonnet-4-20250514-v1:0",
            max_tokens=1024,
            system=BRAIN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def _parse_decision(self, response: str) -> dict | None:
        """Parse the LLM response into a decision dict."""
        text = response.strip()

        # Strip markdown code block if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (``` markers)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    decision = json.loads(text[start:end])
                except json.JSONDecodeError:
                    return None
            else:
                return None

        # Validate required fields
        if "action" not in decision:
            return None

        # Add metadata
        decision["_round"] = self._round
        decision["_timestamp"] = time.time()
        decision["_status_file"] = self._last_status_file

        return decision

    def _save_decision(self, decision: dict) -> None:
        """Save decision to file and memory store."""
        ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
        filepath = self.decision_dir / f"decision_{ts}.json"

        filepath.write_text(
            json.dumps(decision, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Also save to memory store
        self.memory.save_decision(decision)
        logger.debug(f"Decision saved → {filepath.name}")

    async def stop(self) -> None:
        self._running = False
