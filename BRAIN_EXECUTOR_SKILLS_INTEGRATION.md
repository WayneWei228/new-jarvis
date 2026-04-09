# Brain → Executor → Skills 完整联动

## 问题
原来的架构中，Brain 生成决策，Executor 读取决策后直接调用 LLM 生成内容。但有 9 个专业 skill（邮件、翻译、搜索、日历等）存在于 `skills/` 目录中，却完全脱节于这个管线。

## 解决方案
实现了一个完整的 Brain → Executor → Skills 联动机制：

```
User Status (多模态输入)
    ↓
Brain (观察 + 决策)
    ├─ 系统 prompt 现在包含所有可用 skills
    └─ 可在决策中指定 skill 或通过描述隐含使用
    ↓ [decision JSON]
Executor (执行)
    ├─ 检查 params.skill（显式指定）
    ├─ 或 auto-detect 从 action 文本
    └─ 调用 Skill Registry
    ↓
Skill Registry (分发)
    ├─ 若有 skill match → 直接执行 skill
    └─ 若无 skill → fallback 到 LLM（原有逻辑）
    ↓ [result]
Overlay (显示结果)
```

## 核心改动

### 1. Skill Registry (`executor/skill_registry.py`)
提供统一的 skill 管理和调用接口。

**已注册的 9 个 skills：**
- `send-email` — 发送邮件（SMTP，带附件）
- `daily-news` — 获取热点新闻（Baidu + Google Trends）
- `summarize-pro` — 多格式内容总结（TL;DR、bullets 等）
- `universal-translate` — 任意语言翻译
- `mac-control` — Mac 自动化（AppleScript、cliclick）
- `macos-calendar` — 日历事件管理
- `deep-research-pro` — 深度多源研究
- `desearch-web-search` — 实时网页搜索
- `url-to-lark-doc` — URL 转飞书文档

**主要方法：**
```python
registry = get_registry()

# 列出所有 skills
registry.get_all()

# 获取单个 skill
registry.get("send-email")

# 从 action 文本自动检测 skill
matches = registry.find_by_trigger("发送邮件给 xxx")  # → [(skill_id, meta), ...]

# 调用 skill
result = registry.call("send-email", params={"recipient": "...", ...})
```

**自动检测机制：**
每个 skill 有 `trigger` 关键词列表，Executor 会自动检测：
```python
"send-email": {
    "trigger": ["email", "邮件", "发送邮件"],
    ...
}
```

### 2. Brain 系统 Prompt 更新 (`brain/brain.py`)
新增 **"可用的 Executor Skills"** 部分，列出所有可用 skills：

```
## 可用的 Executor Skills

执行层有以下专业工具可以直接调用（在 params 中用 "skill" 字段指定）：
- **send-email** — 发送邮件（带附件）
- **daily-news** — 获取热点新闻
...

如果你的决策需要用到这些工具之一，可以在 params 中加 "skill" 字段：
  "params": { "skill": "send-email", "recipient": "...", ... }

或者放在 action 描述里自然地指出（比如"发送邮件到..."），Executor 会自动识别。
```

**额外指导：**
> 如果决策涉及发邮件/搜索/翻译等，优先在 skill 中声明，让执行层直接调用工具，而不是让 LLM 再生成内容

### 3. Executor 分发逻辑 (`executor/executor.py`)
修改 `_execute()` 方法，新增两层 skill 匹配：

**第一层 — 显式指定（推荐）：**
```python
# Brain 在决策中明确指定
decision = {
    "action": "发送邮件给用户确认...",
    "params": {
        "skill": "send-email",
        "recipient": "user@example.com",
        "subject": "...",
        "body": "..."
    },
    ...
}
```

**第二层 — 隐式自动检测（备选）：**
```python
# 如果 Brain 没有明确指定 skill，Executor 尝试从 action 文本检测
matches = skill_registry.find_by_trigger(decision["action"])
if matches:
    skill_id, _ = matches[0]
    # 调用 skill
```

**执行优先级：**
1. 检查 `params.skill`（显式）
2. 若无，自动检测（隐式）
3. 若仍无，fallback 到 LLM

```python
async def _execute(self, decision, filename):
    # ... skip checks ...
    
    # Step 1: Try explicit skill
    skill_id = params.get("skill")
    
    # Step 2: Try auto-detect
    if not skill_id:
        matches = skill_registry.find_by_trigger(action)
        if matches:
            skill_id, _ = matches[0]
    
    # Step 3: Call skill or fall back to LLM
    if skill_id:
        result = skill_registry.call(skill_id, params)
    else:
        result = self._call_llm(decision)
    
    # Show result...
```

## 使用示例

### 例子 1: Brain 显式指定 skill（推荐）

**Brain 决策：**
```json
{
  "action": "发送邮件给用户确认会议时间",
  "reason": "用户刚刚预约了会议",
  "plan": "构造邮件内容并发送",
  "params": {
    "skill": "send-email",
    "recipient": "user@example.com",
    "subject": "会议预约确认",
    "body": "您的会议已预约在明天下午3点"
  },
  "priority": "high",
  "confidence": 0.9
}
```

**Executor 执行流程：**
1. 读取决策
2. 检查 `params.skill` → "send-email" ✓
3. 查询 registry → 找到 send-email skill
4. 直接调用 `skill_registry.call("send-email", params)`
5. 返回执行结果（而不是让 LLM 再生成一遍邮件内容）

### 例子 2: Brain 隐含使用（自动检测）

**Brain 决策：**
```json
{
  "action": "帮用户总结一下最新的行业新闻趋势",
  "reason": "用户忙于编码，需要了解行业动态",
  "plan": "1. 获取热点新闻 2. 整理成清单 3. 推荐",
  "params": {},  // 没有明确指定 skill
  "priority": "low",
  "confidence": 0.6
}
```

**Executor 执行流程：**
1. 读取决策
2. 检查 `params.skill` → 无 ✗
3. 自动检测：`find_by_trigger("行业新闻趋势")` → "daily-news" ✓
4. 调用 skill: `skill_registry.call("daily-news", {})`
5. 返回最新新闻列表

### 例子 3: 非 skill 决策（fallback 到 LLM）

**Brain 决策：**
```json
{
  "action": "提醒用户休息一会儿，给出 3 个放松建议",
  "reason": "用户已经工作 6 小时",
  "plan": "生成个性化的放松建议",
  "params": {},
  "priority": "low",
  "confidence": 0.8
}
```

**Executor 执行流程：**
1. 读取决策
2. 检查 skill → 无匹配
3. 自动检测 → 无匹配
4. **Fallback 到 LLM**：调用 Claude 生成放松建议
5. 返回 LLM 生成的内容

## 演示脚本

运行 `demo_brain_executor_skills.py` 查看完整演示：

```bash
python3 demo_brain_executor_skills.py
```

**输出包括：**
- 所有已注册 skills 的列表
- 自动检测示例（4 个不同的 action 文本）
- Brain 带 skill 的决策示例
- Brain 无 skill 但自动检测的决策示例
- Brain 系统 prompt 中的 skills 列表部分

## 架构优势

| 方面 | 原来 | 现在 |
|------|------|------|
| **Skills 利用** | 脱节，无法使用 | 完全集成，可自动选择 |
| **Brain 感知** | 不知道有 skills | 系统 prompt 列出所有 skills |
| **Executor 逻辑** | 无脑调 LLM | 智能分发（skill 优先，LLM 备选） |
| **性能** | 所有内容都让 LLM 生成 | skill 直接执行，更快 |
| **成本** | 高（LLM tokens） | 低（skill 执行快，LLM 只处理复杂逻辑） |
| **可靠性** | 依赖 LLM 行为 | skill 有明确输出格式，更可靠 |

## 未来扩展

1. **Skill 参数验证** — 在调用前验证 params 是否合法
2. **Skill 超时控制** — 给每个 skill 设置 timeout
3. **Skill 缓存** — 缓存频繁使用的 skill 结果
4. **自定义 Skill** — 用户可以在 `skills/` 中添加新 skill，自动被 registry 识别
5. **Skill 评分** — 追踪 skill 执行成功率，优化选择策略
6. **多 skill 组合** — 允许单个决策调用多个 skills（如先搜索再总结）

## 文件位置

- **Skill Registry**: `executor/skill_registry.py` (新增)
- **Brain 更新**: `brain/brain.py` (修改)
- **Executor 更新**: `executor/executor.py` (修改)
- **演示脚本**: `demo_brain_executor_skills.py` (新增)
- **本文档**: `BRAIN_EXECUTOR_SKILLS_INTEGRATION.md`

## 快速参考

### Brain 写决策时

如果决策涉及以下任何操作，**优先在 `params` 中加 `"skill": "..."` 字段**：

```json
{
  "action": "...",
  "params": {
    "skill": "send-email",  // 或 daily-news, translate 等
    // ... 其他参数 ...
  }
}
```

或者自然地在 action 描述中提及（Executor 会自动检测）：
```json
{
  "action": "发送邮件给...",  // Executor 自动识别 send-email
  "params": {}
}
```

### Executor 调试时

检查日志中的这些关键行：
```
INFO:executor.executor:[SKILL] Calling send-email with params: {...}
INFO:executor.executor:✓ Skill send-email succeeded
INFO:executor.executor:Skill send-email returned: 123 chars
```

若看到这样的日志说明 fallback 到 LLM 了：
```
INFO:executor.executor:Executing via LLM: ...
```

### 添加新 Skill

1. 在 `skills/` 目录下创建 skill 目录
2. 实现 skill 脚本
3. 在 `executor/skill_registry.py` 的 `SKILLS` dict 中加入元数据
4. 运行 `demo_brain_executor_skills.py` 验证

```python
# In executor/skill_registry.py
SKILLS = {
    "my-new-skill": {
        "name": "新 Skill 的名字",
        "description": "描述",
        "trigger": ["keyword1", "keyword2"],
        "cli": "python script.py",
        "params": ["param1", "param2"],
        "type": "action",  # 或 query, transform
    },
    ...
}
```
