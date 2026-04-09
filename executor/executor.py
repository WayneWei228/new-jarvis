"""
Executor — 执行 Brain 的决策，通过原生浮动窗口实时展示给用户。

Flow:
1. Watch brain/decisions/ for new decision files
2. Show "thinking" card on native overlay
3. Call LLM to actually execute the plan
4. Show result card (summary, translation, suggestion, etc.)
5. Save result to memory + results/
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
from executor.overlay import NativeOverlay
from executor.skill_registry import get_registry

logger = logging.getLogger(__name__)

EXECUTOR_SYSTEM_PROMPT = """\
你是一个全能 AI 助手的执行模块。你会收到一个"决策"，描述了要为用户做什么。

你的任务：**真正执行这个决策**，产出对用户有价值的内容。

## 执行原则

1. **产出实际内容** — 不要只说"我建议..."，而是直接做出来。比如：
   - 如果决策是"总结文章"，直接写出总结
   - 如果决策是"给出代码建议"，直接写出代码
   - 如果决策是"准备资源"，直接列出资源和关键信息

2. **简洁有力** — 用户在忙，内容要精炼、可操作，控制在300字以内

3. **中文输出** — 除非涉及代码或英文术语

4. **格式清晰** — 用换行和符号分隔，便于快速扫读
"""


class Executor:
    """Watches for Brain decisions, executes them, shows results via native overlay."""

    def __init__(
        self,
        overlay: NativeOverlay,
        decision_dir: str = "brain/decisions",
        result_dir: str = "executor/results",
        memory_dir: str = "memory",
        interval_sec: float = 5.0,
    ):
        self.overlay = overlay
        self.decision_dir = Path(decision_dir)
        self.result_dir = Path(result_dir)
        self.interval_sec = interval_sec
        self._running = False
        self._processed: set[str] = set()

        self.memory = MemoryStore(memory_dir=memory_dir)

        # AWS Bedrock
        self._token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
        self._region = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1")

    async def start(self) -> None:
        """Start watching for new decisions."""
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self._running = True

        # Mark existing decisions as already processed
        if self.decision_dir.exists():
            for f in self.decision_dir.glob("decision_*.json"):
                self._processed.add(f.name)

        logger.info(f"Executor started (polling every {self.interval_sec}s, "
                     f"{len(self._processed)} existing decisions skipped)")

        try:
            while self._running:
                await asyncio.sleep(self.interval_sec)
                await self._check_new_decisions()
        except asyncio.CancelledError:
            logger.info("Executor stopped")

    async def _check_new_decisions(self) -> None:
        """Check for new decision files and execute them."""
        if not self.decision_dir.exists():
            return

        for f in sorted(self.decision_dir.glob("decision_*.json")):
            if f.name in self._processed:
                continue
            self._processed.add(f.name)

            try:
                decision = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Cannot read {f.name}: {e}")
                continue

            await self._execute(decision, f.name)

    async def _execute(self, decision: dict, filename: str) -> None:
        """Execute a single decision.

        Strategy:
        1. Check if decision specifies a skill in params or can be detected from action
        2. If skill match → call skill directly
        3. Otherwise → call LLM to produce content
        """
        action = decision.get("action", "unknown")
        reason = decision.get("reason", "")
        plan = decision.get("plan", "")
        priority = decision.get("priority", "medium")
        confidence = decision.get("confidence", 0)
        params = decision.get("params", {})

        # Skip low-confidence or no_action
        if confidence < 0.5 or "no_action" in action.lower():
            logger.info(f"Skipping: {action} (confidence={confidence})")
            return

        # 1. Show "thinking" card
        self.overlay.show_card(
            title=action[:60],
            body=reason,
            card_type="thinking",
            action="thinking...",
            timeout=15,
        )

        # 2. Try to match skill from decision
        skill_registry = get_registry()
        skill_id = params.get("skill")  # Explicit skill in params
        result = None

        if not skill_id:
            # Try to auto-detect skill from action text
            matches = skill_registry.find_by_trigger(action)
            if matches:
                skill_id, skill_meta = matches[0]
                logger.info(f"Auto-detected skill: {skill_id} from action")

        # 3a. If skill matched, call it directly
        if skill_id and skill_registry.get(skill_id):
            logger.info(f"Executing skill: {skill_id}")
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, skill_registry.call, skill_id, params
                )
                logger.info(f"Skill {skill_id} returned: {len(result) if result else 0} chars")
            except Exception as e:
                logger.error(f"Skill execution failed: {e}")
                result = None

        # 3b. If no skill or skill failed, fall back to LLM
        if not result:
            logger.info(f"Executing via LLM: {action}")
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self._call_llm, decision
                )
            except Exception as e:
                logger.error(f"Execution LLM call failed: {e}")
                self.overlay.show_card(
                    title="Error",
                    body=str(e)[:200],
                    card_type="warning",
                    timeout=10,
                )
                return

        # 4. Close thinking card, show result
        self.overlay.close_all()
        self.overlay.show_card(
            title=action[:60],
            body=result,
            card_type="result",
            action=priority,
            confidence=confidence,
            timeout=60,  # Results stay longer
        )

        # 5. Save result
        self._save_result(decision, result, filename)
        logger.info(f"Executed: {action} ({len(result)} chars)")

    def _call_llm(self, decision: dict) -> str:
        """Call LLM to execute the decision (blocking)."""
        action = decision.get("action", "")
        reason = decision.get("reason", "")
        plan = decision.get("plan", "")
        params = json.dumps(decision.get("params", {}), ensure_ascii=False)

        prompt = f"""## 要执行的决策

**行动**: {action}
**原因**: {reason}
**计划**: {plan}
**参数**: {params}

请直接执行以上决策，产出对用户有价值的内容。"""

        client = AnthropicBedrock(
            aws_region=self._region,
            api_key=self._token,
        )
        response = client.messages.create(
            model="apac.anthropic.claude-sonnet-4-20250514-v1:0",
            max_tokens=2048,
            system=EXECUTOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def _save_result(self, decision: dict, result: str, decision_file: str) -> None:
        """Save execution result to file and memory."""
        ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")

        result_data = {
            "action": decision.get("action"),
            "decision_file": decision_file,
            "result": result,
            "status": "success",
            "timestamp": time.time(),
        }

        filepath = self.result_dir / f"result_{ts}.json"
        filepath.write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.memory.save_result(result_data)

    async def stop(self) -> None:
        self._running = False
