"""
Executor — 执行 Brain 的决策，并通过 UI 实时展示给用户。

Flow:
1. Watch brain/decisions/ for new decision files
2. Push "brain decided" event to UI
3. Call LLM to actually execute the plan
4. Push result to UI (overlay + macOS notification)
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
from executor.notifier import Notifier

logger = logging.getLogger(__name__)

EXECUTOR_SYSTEM_PROMPT = """\
你是一个全能 AI 助手的执行模块。你会收到一个"决策"，描述了要为用户做什么。

你的任务：**真正执行这个决策**，产出对用户有价值的内容。

## 执行原则

1. **产出实际内容** — 不要只说"我建议..."，而是直接做出来。比如：
   - 如果决策是"总结文章"，直接写出总结
   - 如果决策是"给出代码建议"，直接写出代码
   - 如果决策是"准备资源"，直接列出资源和关键信息

2. **简洁有力** — 用户在忙，内容要精炼、可操作

3. **中文输出** — 除非涉及代码或英文术语

4. **格式清晰** — 使用 markdown 格式，标题、列表、代码块
"""


class Executor:
    """Watches for Brain decisions and executes them."""

    def __init__(
        self,
        notifier: Notifier,
        decision_dir: str = "brain/decisions",
        result_dir: str = "executor/results",
        memory_dir: str = "memory",
        interval_sec: float = 5.0,
    ):
        self.notifier = notifier
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
        """Execute a single decision."""
        action = decision.get("action", "unknown")
        reason = decision.get("reason", "")
        plan = decision.get("plan", "")
        priority = decision.get("priority", "medium")
        confidence = decision.get("confidence", 0)

        # 1. Notify UI: Brain decided
        await self.notifier.push_event("brain_decision", {
            "action": action,
            "reason": reason,
            "priority": priority,
            "confidence": confidence,
        })

        await asyncio.sleep(1.5)  # Brief pause so user can see the decision

        # 2. Skip low-confidence or no_action decisions
        if confidence < 0.5 or action == "no_action":
            await self.notifier.push_event("status_update", {
                "summary": f"Observing... ({action})",
            })
            return

        # 3. Notify UI: Executing
        await self.notifier.push_event("executing", {
            "action": action,
            "plan": plan,
        })

        # 4. Call LLM to produce actual content
        logger.info(f"Executing: {action}")
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._call_llm, decision
            )
        except Exception as e:
            logger.error(f"Execution LLM call failed: {e}")
            await self.notifier.push_event("execution_error", {
                "message": str(e),
            })
            return

        # 5. Notify UI: Result
        await self.notifier.push_event("execution_complete", {
            "action": action,
            "result": result,
            "title": f"AI: {action[:50]}",
            "message": result[:100],
        })

        # 6. Save result
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

        # Save to results dir
        filepath = self.result_dir / f"result_{ts}.json"
        filepath.write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Save to memory
        self.memory.save_result(result_data)

    async def stop(self) -> None:
        self._running = False
