# 飞书 Skills 快速开始

## 安装 (3 分钟)

```bash
# 方式 1: 使用自动安装脚本（推荐）
chmod +x setup_lark_cli.sh
./setup_lark_cli.sh

# 方式 2: 手动安装
npm install -g @larksuite/cli
lark-cli config init --new

# 验证
lark-cli im ls-chats
```

## Brain 中使用飞书 Skills

### 发送飞书消息

```json
{
  "action": "发送飞书消息给团队",
  "params": {
    "skill": "lark-im",
    "chat_id": "oc_abc123",  // 群组 ID
    "content": "✅ 任务已完成"
  }
}
```

自动检测（无需显式指定 skill）：
```json
{
  "action": "发飞书通知大家项目上线了",
  "params": {}  // Executor 自动识别 lark-im
}
```

### 创建飞书文档

```json
{
  "action": "创建飞书文档记录会议内容",
  "params": {
    "skill": "lark-doc",
    "title": "2026-04-09 会议纪要",
    "content": "## 内容\n..."
  }
}
```

### 创建日历事件

```json
{
  "action": "创建日历事件",
  "params": {
    "skill": "lark-calendar",
    "summary": "团队会议",
    "start_time": "2026-04-10T14:00:00+08:00",
    "end_time": "2026-04-10T15:00:00+08:00"
  }
}
```

## 常用命令

```bash
# 查询群组 ID
lark-cli im ls-chats

# 查询文件夹 ID
lark-cli docs ls-folders

# 发送消息
lark-cli im send-message --chat-id oc_xxx --content "消息"

# 创建文档
lark-cli docs +create --as user --title "标题" --markdown "@file.md"

# 创建日历事件
lark-cli calendar +create --as user --summary "事件" --start-time "2026-04-10T14:00:00"
```

## 自动检测触发词

| Skill | 触发词 |
|-------|--------|
| **lark-im** | 飞书消息, lark消息, 发飞书, 飞书通知 |
| **lark-doc** | 飞书文档, 创建文档, lark文档, 飞书记录 |
| **lark-calendar** | 飞书日历, 日历事件, 日程 |

## 演示

```bash
# 查看飞书 skills 自动检测效果
python3 -c "
from executor.skill_registry import get_registry
registry = get_registry()
print('飞书 Skills:')
for skill_id in ['lark-im', 'lark-doc', 'lark-calendar']:
    meta = registry.get(skill_id)
    print(f'  {skill_id}: {meta[\"name\"]}')
"

# 完整演示
python3 demo_brain_executor_skills.py
```

## 故障排除

### lark-cli 找不到

```bash
# 检查是否安装
which lark-cli
lark-cli --version

# 重新安装
npm install -g @larksuite/cli
```

### 认证失败

```bash
# 重新配置
lark-cli config init

# 查看配置
cat ~/.lark/config.json
```

### 无法连接飞书

```bash
# 测试连接
lark-cli im ls-chats

# 检查权限是否足够
# 应用需要这些权限：
# - im:message:create (发送消息)
# - docx:document:create (创建文档)
# - calendar:event:create (创建日历事件)
```

## 参考文档

- 📖 **详细文档**: `LARK_SKILLS_SETUP.md`
- 🔧 **Skill Registry**: `executor/skill_registry.py`
- 🧠 **Brain 系统 Prompt**: `brain/brain.py`
- ⚡ **Executor 逻辑**: `executor/executor.py`

## 集成到你的 Brain

当 Brain 生成需要与飞书交互的决策时，可以：

1. **显式指定 skill**（推荐）
   ```json
   { "params": { "skill": "lark-im", ... } }
   ```

2. **隐式自动检测**
   ```json
   { "action": "发飞书消息...", "params": {} }
   ```

两种方式都有效，Executor 会自动处理。

## 完整流程

```
用户操作
    ↓
Brain 观察 + 生成决策
    ├─ 决策中可指定 skill 或隐含描述
        ↓
Executor 读取决策
    ├─ 检查 params.skill
    ├─ 或自动检测
        ↓
Skill Registry
    ├─ lark-cli 执行
        ↓
飞书
    ├─ 消息发送 ✓
    ├─ 文档创建 ✓
    ├─ 日历更新 ✓
```
