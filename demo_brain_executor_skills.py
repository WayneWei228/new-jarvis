#!/usr/bin/env python3
"""
Demo: Brain → Executor → Skills 完整流程

演示：
1. Brain 生成一个决策，指定使用 skill
2. Executor 读取决策，识别 skill，调用 skill registry
3. Skill registry 查找并执行对应的 skill

在真实场景中：
- Brain 监听 input/user_status/ 目录
- Executor 监听 brain/decisions/ 目录
- Skill 被实际执行（而不是仅返回占位符）
"""

import json
import logging
from pathlib import Path
from executor.skill_registry import get_registry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def demo_skill_registry():
    """演示 Skill Registry 的功能."""
    logger.info("=" * 60)
    logger.info("Demo 1: Skill Registry")
    logger.info("=" * 60)

    registry = get_registry()

    # 1. 列出所有 skills
    print("\n✅ 已注册的 skills:")
    for skill_id, meta in registry.get_all().items():
        print(f"  - {meta['name']} ({skill_id})")
        print(f"    触发词: {', '.join(meta['trigger'])}")

    # 2. 从 action 文本自动检测 skill
    print("\n✅ 自动检测 skill 的例子:")
    test_actions = [
        "发送邮件给 user@example.com",
        "总结一下这篇文章",
        "翻译成英文",
        "帮我搜索 Python 最佳实践",
    ]
    for action_text in test_actions:
        matches = registry.find_by_trigger(action_text)
        if matches:
            skill_id, meta = matches[0]
            print(f"  '{action_text}'")
            print(f"    ✓ 匹配到: {meta['name']} ({skill_id})")
        else:
            print(f"  '{action_text}'")
            print(f"    ✗ 未匹配")


def demo_brain_decision_with_skill():
    """演示 Brain 生成的带 skill 指定的决策."""
    logger.info("\n" + "=" * 60)
    logger.info("Demo 2: Brain Decision with Skill")
    logger.info("=" * 60)

    # 模拟 Brain 生成的决策（带 skill 指定）
    decision = {
        "action": "发送邮件给用户确认会议时间",
        "reason": "用户刚刚预约了一个会议，应该发邮件确认",
        "plan": "1. 构造邮件内容 2. 调用发邮件 skill 3. 保存结果",
        "params": {
            "skill": "send-email",
            "recipient": "user@example.com",
            "subject": "会议预约确认",
            "body": "您的会议已预约在明天下午3点。",
        },
        "priority": "high",
        "confidence": 0.9,
    }

    print("\n📋 Brain 生成的决策：")
    print(json.dumps(decision, ensure_ascii=False, indent=2))

    # Executor 处理这个决策
    registry = get_registry()
    skill_id = decision.get("params", {}).get("skill")

    if skill_id:
        print(f"\n✅ Executor 识别到 skill: {skill_id}")
        print(f"   来自 params.skill 字段")

        skill = registry.get(skill_id)
        if skill:
            print(f"   描述: {skill['description']}")
            print(f"   参数: {', '.join(skill['params'])}")
            print(f"\n   [实际执行中...（当前为演示模式）]")
        else:
            print(f"   ✗ Skill 不存在")


def demo_auto_detect_skill():
    """演示 Executor 从 action 文本自动检测 skill."""
    logger.info("\n" + "=" * 60)
    logger.info("Demo 3: Auto-detect Skill from Action")
    logger.info("=" * 60)

    # 模拟 Brain 生成的决策（不明确指定 skill，但 Executor 可以自动检测）
    decision = {
        "action": "我看用户最近很忙，应该提醒他查看今天的热点新闻放松一下",
        "reason": "用户已经工作 6 小时连续编码，需要放松一下",
        "plan": "1. 获取今天的热点新闻 2. 整理成清单 3. 推荐给用户",
        "params": {},  # 没有明确指定 skill
        "priority": "low",
        "confidence": 0.6,
    }

    print("\n📋 Brain 生成的决策（无 skill 明确指定）：")
    print(f"  action: {decision['action'][:60]}...")

    # Executor 自动检测
    registry = get_registry()
    matches = registry.find_by_trigger(decision["action"])

    if matches:
        skill_id, skill_meta = matches[0]
        print(f"\n✅ Executor 自动检测到 skill: {skill_id}")
        print(f"   名称: {skill_meta['name']}")
        print(f"   描述: {skill_meta['description']}")
    else:
        print(f"\n❌ 无法自动检测 skill，将使用 LLM 执行")


def demo_skills_in_brain_prompt():
    """演示 Brain 系统 prompt 中包含的 skills 列表."""
    logger.info("\n" + "=" * 60)
    logger.info("Demo 4: Skills in Brain System Prompt")
    logger.info("=" * 60)

    from brain.brain import BRAIN_SYSTEM_PROMPT

    print("\n📋 Brain 系统 prompt 的 Skills 部分：")
    if "可用的 Executor Skills" in BRAIN_SYSTEM_PROMPT:
        start = BRAIN_SYSTEM_PROMPT.find("## 可用的 Executor Skills")
        end = BRAIN_SYSTEM_PROMPT.find("## 如果你的决策", start)
        if start >= 0:
            section = BRAIN_SYSTEM_PROMPT[start:end if end >= 0 else len(BRAIN_SYSTEM_PROMPT)]
            lines = section.split("\n")[:15]  # 前 15 行
            for line in lines:
                print(f"  {line}")
            print("  ...")


def main():
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " Brain → Executor → Skills 完整联动演示".center(58) + "║")
    print("╚" + "=" * 58 + "╝")

    demo_skill_registry()
    demo_brain_decision_with_skill()
    demo_auto_detect_skill()
    demo_skills_in_brain_prompt()

    print("\n" + "=" * 60)
    print("Demo 完成！")
    print("=" * 60)
    print("\n📝 关键改变：")
    print("  1. Brain 系统 prompt 现在包含所有可用的 skills")
    print("  2. Executor 支持两种方式调用 skill:")
    print("     - 显式: params.skill 字段指定")
    print("     - 隐式: 从 action 文本自动检测")
    print("  3. Skill Registry 提供统一的 skill 查询和调用接口")
    print("\n🎯 执行流程：")
    print("  1. Brain 观察用户状态 → 生成决策 JSON（可包含 skill 指定）")
    print("  2. Executor 读取决策 → 检查是否有 skill")
    print("  3. 若有 skill → Skill Registry 直接调用")
    print("  4. 若无 skill → LLM 生成内容（原有逻辑）")
    print()


if __name__ == "__main__":
    main()
