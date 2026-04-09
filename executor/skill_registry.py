"""
Skill Registry — 管理所有可调用的 skills。

每个 skill 可以通过 CLI、环境变量或 stdin 调用。
Executor 使用这个注册表来决定是否调用 skill，以及如何调用。
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Skill 元数据 — 定义每个 skill 如何被调用
SKILLS = {
    "send-email": {
        "name": "发送邮件",
        "description": "Send emails via SMTP with optional attachments",
        "trigger": ["email", "邮件", "发送邮件"],
        "cli": "python3 ~/.openclaw/workspace/skills/send-email/send_email.py",
        "params": ["recipient", "subject", "body", "attachment"],
        "type": "action",
    },
    "daily-news": {
        "name": "每日新闻",
        "description": "Get trending news from Baidu & Google Trends",
        "trigger": ["news", "新闻", "热点"],
        "cli": 'python "{skill_dir}/daily_news.py"',
        "params": [],
        "type": "query",
    },
    "summarize-pro": {
        "name": "内容总结",
        "description": "Summarize text in multiple formats (TL;DR, bullets, etc)",
        "trigger": ["summarize", "总结", "概括"],
        "cli": None,  # Conversational, no direct CLI
        "params": ["text", "format"],
        "type": "transform",
    },
    "universal-translate": {
        "name": "翻译",
        "description": "Translate text between any languages",
        "trigger": ["translate", "翻译", "translation"],
        "cli": None,  # Conversational
        "params": ["text", "target_language"],
        "type": "transform",
    },
    "mac-control": {
        "name": "Mac 自动化",
        "description": "Automate Mac UI (click, screenshot, keyboard)",
        "trigger": ["click", "screenshot", "键盘", "自动化"],
        "cli": "{skill_dir}/scripts/click-at-display.sh",
        "params": ["x", "y"],
        "type": "action",
    },
    "macos-calendar": {
        "name": "日历管理",
        "description": "Create/list macOS Calendar events",
        "trigger": ["calendar", "日历", "事件"],
        "cli": '"{skill_dir}/scripts/calendar.sh"',
        "params": ["action", "summary", "date"],
        "type": "action",
    },
    "deep-research-pro": {
        "name": "深度研究",
        "description": "Multi-source research synthesis (no paid APIs)",
        "trigger": ["research", "研究", "调查"],
        "cli": None,
        "params": ["topic", "depth"],
        "type": "query",
    },
    "desearch-web-search": {
        "name": "网页搜索",
        "description": "Real-time web search with SERP-style results",
        "trigger": ["search", "搜索", "web"],
        "cli": 'python "{skill_dir}/scripts/desearch.py" web',
        "params": ["query", "start"],
        "type": "query",
    },
    "url-to-lark-doc": {
        "name": "URL 转飞书文档",
        "description": "Fetch URLs, analyze content, create Feishu docs",
        "trigger": ["url", "链接", "网址", "整理url"],
        "cli": None,
        "params": ["urls", "title"],
        "type": "action",
    },
    "lark-im": {
        "name": "飞书消息",
        "description": "Send Feishu instant messages to users or groups",
        "trigger": ["飞书消息", "lark消息", "发飞书", "飞书通知"],
        "cli": "lark-cli im",
        "params": ["user_id", "content", "chat_id"],
        "type": "action",
    },
    "lark-doc": {
        "name": "飞书文档",
        "description": "Create and manage Feishu cloud documents",
        "trigger": ["飞书文档", "创建文档", "lark文档", "飞书记录"],
        "cli": "lark-cli docs",
        "params": ["title", "content", "folder_token"],
        "type": "action",
    },
    "lark-calendar": {
        "name": "飞书日历",
        "description": "Create and manage Feishu calendar events",
        "trigger": ["飞书日历", "日历事件", "日程"],
        "cli": "lark-cli calendar",
        "params": ["summary", "start_time", "end_time"],
        "type": "action",
    },
}


class SkillRegistry:
    """Manages skill discovery and invocation."""

    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self.skills = self._load_skills()

    def _load_skills(self) -> dict[str, dict]:
        """Load skill metadata from SKILLS dict.

        Note: Some skills (like lark-cli) don't have a local directory,
        but are still available via CLI command.
        """
        loaded = {}
        for skill_id, meta in SKILLS.items():
            skill_path = self.skills_dir / skill_id
            has_local_dir = skill_path.exists()

            # Skills with local directories get logged as verified
            if has_local_dir:
                logger.debug(f"✓ Skill loaded (with local dir): {skill_id}")
            else:
                # Skills without local dir (e.g., lark-cli) are still valid if they have a CLI
                if meta.get("cli"):
                    logger.debug(f"✓ Skill loaded (CLI-based): {skill_id}")
                else:
                    logger.warning(f"⚠ Skill {skill_id} has no local dir and no CLI command")

            loaded[skill_id] = meta

        return loaded

    def get_all(self) -> dict[str, dict]:
        """Return all loaded skills."""
        return self.skills

    def get(self, skill_id: str) -> dict | None:
        """Get skill metadata by ID."""
        return self.skills.get(skill_id)

    def find_by_trigger(self, text: str) -> list[tuple[str, dict]]:
        """Find skills whose trigger keywords appear in text."""
        matches = []
        text_lower = text.lower()
        for skill_id, meta in self.skills.items():
            for trigger in meta.get("trigger", []):
                if trigger.lower() in text_lower:
                    matches.append((skill_id, meta))
                    break
        return matches

    def list_for_prompt(self) -> str:
        """Format skill list for inclusion in LLM prompts."""
        lines = ["## 可用的 Skills\n"]
        for skill_id, meta in self.skills.items():
            lines.append(f"- **{meta['name']}** (`{skill_id}`)")
            lines.append(f"  触发词: {', '.join(meta.get('trigger', []))}")
            lines.append(f"  {meta.get('description', '')}\n")
        return "\n".join(lines)

    def call(
        self,
        skill_id: str,
        params: dict[str, Any] | None = None,
        **kwargs,
    ) -> str:
        """Invoke a skill by ID with parameters.

        Returns: skill output as string
        """
        skill = self.get(skill_id)
        if not skill:
            raise ValueError(f"Unknown skill: {skill_id}")

        params = params or {}
        skill_path = self.skills_dir / skill_id

        # For now, just return a placeholder
        # In real use, this would execute the skill's CLI or script
        logger.info(f"[SKILL] Calling {skill_id} with params: {params}")

        cli_template = skill.get("cli")
        if not cli_template:
            logger.warning(f"Skill {skill_id} has no CLI, skipping invocation")
            return f"[{skill['name']} would be called here with {params}]"

        # Expand template variables
        cli = cli_template.replace("{skill_dir}", str(skill_path))

        try:
            # Simple execution (for CLI-based skills)
            # In production, handle stdin/env based on skill type
            result = subprocess.run(
                cli,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(skill_path),
            )
            if result.returncode == 0:
                logger.info(f"✓ Skill {skill_id} succeeded")
                return result.stdout.strip()
            else:
                logger.error(f"✗ Skill {skill_id} failed: {result.stderr[:200]}")
                return f"Error: {result.stderr[:200]}"
        except subprocess.TimeoutExpired:
            logger.error(f"✗ Skill {skill_id} timed out")
            return "Skill execution timed out"
        except Exception as e:
            logger.error(f"✗ Skill {skill_id} exception: {e}")
            return f"Skill error: {e}"


# Global registry instance
_registry: SkillRegistry | None = None


def get_registry(skills_dir: str = "skills") -> SkillRegistry:
    """Get or create the global skill registry."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry(skills_dir)
    return _registry
