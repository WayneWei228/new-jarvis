# Executor 飞书 Skills 安装与使用

为 Executor 添加了三个飞书（Feishu/Lark）skills，用于直接操作飞书：
- `lark-im` — 发送飞书消息
- `lark-doc` — 创建/编辑飞书文档
- `lark-calendar` — 创建日历事件

## 前置要求

### 1. 安装 lark-cli

```bash
# 全局安装 lark-cli
npm install -g @larksuite/cli

# 验证安装
lark-cli --version
```

### 2. 初始化和认证

```bash
# 初始化配置（创建新应用）
lark-cli config init --new

# 或者使用已有应用
lark-cli config init
```

该命令会：
- 提示你输入 Feishu/Lark 组织的 Domain
- 打开浏览器进行 OAuth 认证
- 保存 token 到本地配置

**配置文件位置：**
```
~/.lark/config.json
```

### 3. 验证配置

```bash
# 测试连接
lark-cli im ls-chats

# 应该能看到你的飞书群列表
```

## Executor 中的飞书 Skills

### lark-im — 发送飞书消息

**用途：** 发送消息到飞书用户或群组

**Brain 决策示例：**
```json
{
  "action": "发送飞书消息给团队说已完成该任务",
  "reason": "用户完成了重要任务，需要通知团队",
  "plan": "1. 构造消息内容 2. 发送到项目群",
  "params": {
    "skill": "lark-im",
    "chat_id": "oc_abc123def456",  // 群组 ID 或 user_id
    "content": "✅ 任务已完成"
  },
  "priority": "medium",
  "confidence": 0.9
}
```

**关键参数：**
- `chat_id` (必需) — 飞书群组 ID 或用户 ID
  - 可以通过 `lark-cli im ls-chats` 查询
  - 格式：`oc_xxx` (群组) 或 `ou_xxx` (用户)
- `user_id` (可选) — 如果发给指定用户
- `content` (必需) — 消息内容（支持 Markdown）

**Executor 调用：**
```python
result = skill_registry.call("lark-im", params={
    "chat_id": "oc_abc123def456",
    "content": "✅ 任务已完成"
})
```

**CLI 命令：**
```bash
lark-cli im send-message --chat-id oc_xxx --content "消息内容"
```

---

### lark-doc — 创建和编辑飞书文档

**用途：** 创建新的飞书云文档或追加内容

**Brain 决策示例：**
```json
{
  "action": "创建飞书文档记录今天的会议内容",
  "reason": "用户刚结束会议，需要记录相关内容",
  "plan": "1. 整理会议内容 2. 在飞书文档中创建记录",
  "params": {
    "skill": "lark-doc",
    "title": "2026-04-09 会议纪要",
    "content": "## 与会人员\n- 张三\n- 李四\n\n## 讨论内容\n...",
    "folder_token": "fldcnXXXX"  // 可选，指定保存位置
  },
  "priority": "high",
  "confidence": 0.85
}
```

**关键参数：**
- `title` (必需) — 文档标题
- `content` (必需) — 文档内容（支持 Lark Markdown）
- `folder_token` (可选) — 保存到指定文件夹
  - 不指定则保存到"我的空间"
  - 通过 `lark-cli docs ls-folders` 查询

**Executor 调用：**
```python
result = skill_registry.call("lark-doc", params={
    "title": "2026-04-09 会议纪要",
    "content": "## 标题\n\n内容..."
})
```

**CLI 命令：**
```bash
# 创建文档
lark-cli docs +create --as user --title "文档标题" --markdown "@content.md"

# 查询文件夹
lark-cli docs ls-folders
```

---

### lark-calendar — 创建日历事件

**用途：** 在飞书日历中创建事件

**Brain 决策示例：**
```json
{
  "action": "创建日历事件提醒用户明天下午2点有重要会议",
  "reason": "用户说了明天有会议，应该自动加日历",
  "plan": "1. 计算明天下午2点的时间 2. 创建日历事件",
  "params": {
    "skill": "lark-calendar",
    "summary": "重要会议",
    "start_time": "2026-04-10T14:00:00+08:00",
    "end_time": "2026-04-10T15:00:00+08:00",
    "description": "与团队讨论项目进展"
  },
  "priority": "high",
  "confidence": 0.9
}
```

**关键参数：**
- `summary` (必需) — 事件标题
- `start_time` (必需) — 开始时间（ISO 8601 格式）
  - 示例：`2026-04-10T14:00:00+08:00`
- `end_time` (必需) — 结束时间
- `description` (可选) — 事件描述
- `attendees` (可选) — 参会人员列表

**Executor 调用：**
```python
result = skill_registry.call("lark-calendar", params={
    "summary": "重要会议",
    "start_time": "2026-04-10T14:00:00+08:00",
    "end_time": "2026-04-10T15:00:00+08:00"
})
```

**CLI 命令：**
```bash
lark-cli calendar +create --as user --summary "事件标题" --start-time "2026-04-10T14:00:00" --end-time "2026-04-10T15:00:00"
```

---

## 实际使用流程

### 场景 1: 用户完成任务，自动通知团队

1. **用户状态输入：**
   ```
   用户刚刚说"好的，我已经完成了代码审查任务"
   ```

2. **Brain 生成决策：**
   ```json
   {
     "action": "发送飞书消息给团队通知任务完成",
     "params": {
       "skill": "lark-im",
       "chat_id": "oc_project_team",
       "content": "✅ @所有人 Wayne 已完成代码审查任务"
     },
     "confidence": 0.9
   }
   ```

3. **Executor 执行：**
   - 检查 `params.skill` → "lark-im" ✓
   - 调用 `skill_registry.call("lark-im", params)`
   - lark-cli 发送消息
   - 返回执行结果

4. **用户看到：**
   - 飞书群组中出现消息通知

---

### 场景 2: 会议后自动记录

1. **用户状态输入：**
   ```
   用户刚结束了一个 30 分钟的会议，桌面上有会议记录
   ```

2. **Brain 生成决策：**
   ```json
   {
     "action": "创建飞书文档记录会议内容",
     "params": {
       "skill": "lark-doc",
       "title": "2026-04-09 产品讨论会议纪要",
       "content": "## 参会人员\n- PM: 张三\n- 工程: 李四\n...",
       "folder_token": "fldcnMeeting2026"
     },
     "confidence": 0.85
   }
   ```

3. **Executor 执行：**
   - 调用 lark-cli 创建文档
   - 返回文档 URL

4. **用户看到：**
   - 飞书文档已创建，包含会议内容
   - 链接显示在 Executor 结果卡中

---

### 场景 3: 自动加日程

1. **用户状态输入：**
   ```
   用户语音："明天下午3点跟客户开会"
   ```

2. **Brain 生成决策：**
   ```json
   {
     "action": "在日历中创建会议事件",
     "params": {
       "skill": "lark-calendar",
       "summary": "与客户开会",
       "start_time": "2026-04-10T15:00:00+08:00",
       "end_time": "2026-04-10T16:00:00+08:00",
       "description": "讨论项目需求"
     },
     "confidence": 0.95
   }
   ```

3. **Executor 执行：**
   - 调用 lark-cli 创建日历事件
   - 返回成功确认

4. **用户看到：**
   - 飞书日历中已添加事件
   - 明天下午 3 点的日程已锁定

---

## 常见问题

### Q: 如何查询群组 ID？

```bash
# 列出所有群组
lark-cli im ls-chats

# 输出类似：
# oc_6abc123def456 | 产品团队
# oc_7ghi789jkl012 | 工程技术
# ...
```

### Q: 如何找到文件夹 token？

```bash
# 列出云空间中的文件夹
lark-cli docs ls-folders

# 输出类似：
# fldcnXXXX | 项目文档
# fldcnYYYY | 会议纪要
# ...
```

### Q: 飞书文档支持什么格式？

支持 **Lark Markdown**，包括：
```markdown
# 标题 1
## 标题 2

**加粗**、*斜体*、~~删除线~~

- 列表项 1
- 列表项 2

> 引用

```代码块```

[链接](https://example.com)

| 表头1 | 表头2 |
|------|------|
| 单元格 | 单元格 |
```

### Q: 日历事件时间格式是什么？

使用 **ISO 8601 格式**（带时区）：
```
2026-04-10T14:00:00+08:00  // 北京时间 下午 2 点

可用格式：
- 2026-04-10T14:00:00Z     // UTC 时间
- 2026-04-10T14:00:00+08:00 // UTC+8 (推荐)
- 2026-04-10T14:00:00      // 本地时间（不推荐）
```

### Q: Executor 调用飞书 skill 失败怎么办？

检查以下几点：

1. **lark-cli 是否安装且在 PATH 中：**
   ```bash
   which lark-cli
   lark-cli --version
   ```

2. **认证是否正确：**
   ```bash
   # 检查配置文件
   cat ~/.lark/config.json
   
   # 重新认证
   lark-cli config init
   ```

3. **权限是否足够：**
   - lark-cli 应用需要以下权限：
     - `im:message:create` — 发送消息
     - `docx:document:create` — 创建文档
     - `calendar:event:create` — 创建日历事件

4. **查看 Executor 日志：**
   ```bash
   # 日志会显示 skill 执行失败的具体原因
   tail -f logs/executor.log
   ```

---

## Brain 中使用飞书 Skills 的最佳实践

### 1. 显式指定 skill（推荐）
```json
{
  "action": "发送飞书消息...",
  "params": {
    "skill": "lark-im",
    "chat_id": "...",
    "content": "..."
  }
}
```

### 2. 利用 trigger 自动检测
```json
{
  "action": "发飞书消息给团队说已完成",  // 包含 "飞书消息"
  "params": {}  // Executor 会自动识别 lark-im
}
```

### 3. 为不同场景选择合适的 skill

| 场景 | 使用 Skill | 原因 |
|------|-----------|------|
| 快速通知 | `lark-im` | 实时、简洁 |
| 详细记录 | `lark-doc` | 支持格式、可搜索 |
| 日程管理 | `lark-calendar` | 便于日程规划 |

---

## 集成到现有系统

### 已集成到：
- ✅ Executor Skill Registry (`executor/skill_registry.py`)
- ✅ Brain System Prompt（列在可用 skills 中）
- ✅ Demo 脚本（`demo_brain_executor_skills.py`）

### 下一步：
1. 运行 `lark-cli config init --new` 完成认证
2. 验证 `lark-cli im ls-chats` 能正常运行
3. 测试 `demo_brain_executor_skills.py` 的飞书 skill 自动检测
4. Brain 在生成决策时可以自然地使用飞书 skill

---

## 快速参考

### 配置检查清单

```bash
# ✅ 安装 lark-cli
npm install -g @larksuite/cli
lark-cli --version

# ✅ 初始化和认证
lark-cli config init --new

# ✅ 测试连接
lark-cli im ls-chats        # 列出群组
lark-cli docs ls-folders    # 列出文件夹
lark-cli calendar ls        # 列出日历

# ✅ 查看配置
cat ~/.lark/config.json
```

### Brain 决策模板

**发送消息：**
```json
{
  "action": "发送飞书消息...",
  "params": {
    "skill": "lark-im",
    "chat_id": "oc_xxx",
    "content": "..."
  }
}
```

**创建文档：**
```json
{
  "action": "创建飞书文档...",
  "params": {
    "skill": "lark-doc",
    "title": "...",
    "content": "..."
  }
}
```

**创建事件：**
```json
{
  "action": "创建日历事件...",
  "params": {
    "skill": "lark-calendar",
    "summary": "...",
    "start_time": "2026-04-10T14:00:00+08:00",
    "end_time": "2026-04-10T15:00:00+08:00"
  }
}
```
