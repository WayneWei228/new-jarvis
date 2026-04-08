# Brainiest Mind - Architecture v2

## System Overview

A real-time multimodal monitoring and intelligent decision system. It continuously collects user physiological and behavioral data, uses LLM to generate user state snapshots, and a Brain module reasons about how to help — then an Executor carries out the action and feeds results back for continuous learning.

## Core Data Flow

```
┌──────────────────────────────────────────────────┐
│  INPUT MODULE                                    │
│                                                  │
│  A. Physiological Data (心率, 视频, 音频, 图片)   │
│  B. Behavioral Data (浏览器, 收藏, 点击, 应用)    │
│  C. Execution Feedback (上一轮的执行结果回流)      │
│                                                  │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────┐
│  LLM ANALYSIS                                    │
│                                                  │
│  Input:  最新多模态原始数据                       │
│  Output: user_status_{timestamp}.md              │
│                                                  │
│  职责:                                           │
│  • 融合多数据源 (生理 + 行为 + 反馈)              │****
│  • 标注事件类型 (continuous / discrete / feedback) │
│  • 生成结构化的用户状态描述                       │
│                                                  │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
              ┌──────────────┐
              │ input/ folder │
              │ (State Store) │
              └──────┬───────┘
                     │
                     ▼
┌──────────────────────────────────────────────────┐
│  BRAIN MODULE                                    │
│                                                  │
│  Inputs:                                         │
│  • user_status_*.md (最新N个状态快照)             │
│  • Memory Store (决策历史 + 执行结果 + 用户反馈)  │
│                                                  │
│  Process:                                        │
│  1. 读取最新状态 + 历史记忆                       │
│  2. 分析用户当前需求和趋势                        │
│  3. 推理: 我能做什么来帮助用户？                  │
│  4. 生成决策 (action + reason + params)           │
│                                                  │
│  Output: decision_{timestamp}.json               │
│  {                                               │
│    "action": "organize_docs",                    │
│    "reason": "用户收藏了8篇文章，整理会有帮助",    │
│    "params": {...},                              │
│    "priority": "normal",                         │
│    "confidence": 0.85                            │
│  }                                               │
│                                                  │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────┐
│  EXECUTOR MODULE                                 │
│                                                  │
│  1. Task Decomposition (复杂任务 → 子任务列表)    │
│     "organize_docs" →                            │
│       sub1: fetch_urls(8)                        │
│       sub2: extract_content()                    │
│       sub3: categorize()                         │
│       sub4: generate_docs()                      │
│                                                  │
│  2. Execute (调用 tools/skills 执行每个子任务)    │
│                                                  │
│  3. Notify User (弹窗/消息/UI交互)               │
│     "已为您整理好8篇收藏的文档"                   │
│                                                  │
│  4. Write Back (结果回流)                         │
│     → Memory Store: 存储决策+结果                 │
│     → INPUT(C): 执行结果作为下一轮的输入          │
│                                                  │
│  Output: execution_result_{timestamp}.json       │
│  {                                               │
│    "decision_id": "dec_001",                     │
│    "status": "success",                          │
│    "result": {...},                              │
│    "user_feedback": null                         │
│  }                                               │
│                                                  │
└──────────┬──────────────────┬────────────────────┘
           │                  │
           ▼                  ▼
┌─────────────────┐  ┌────────────────────────┐
│  MEMORY STORE   │  │  INPUT MODULE (回流)    │
│                 │  │  C. Execution Feedback  │
│  • 决策历史     │  └────────────────────────┘
│  • 执行结果     │           │
│  • 用户反馈     │           └──→ 触发下一轮
│  • 学习到的偏好 │               LLM Analysis
└─────────────────┘               → Brain
                                  → Executor
                                  → ...循环
```

## The Feedback Loop

This is the most critical architectural addition. Without it, the system can only make one-shot decisions.

```
Round 1:
  INPUT(浏览器收藏) → Analysis → Brain(决定整理文档) → Executor(整理+通知)
       ↑                                                       │
       │                                                       │
       └────────── execution result + user reaction ───────────┘

Round 2:
  INPUT(用户看文档的反应) → Analysis → Brain(决定做产品) → Executor(做产品+通知)
       ↑                                                       │
       │                                                       │
       └────────── execution result + user reaction ───────────┘
Round N: ...
```

Each round makes the system smarter because:
1. **Brain reads Memory** — knows what it did before and what worked
2. **INPUT receives feedback** — execution results become new data
3. **Decisions compound** — Round 2 builds on Round 1's output

---

## Module Details

### A. INPUT MODULE

Three categories of input data:

| Category | Examples | Nature | Frequency |
|----------|----------|--------|-----------|
| **Physiological** | 心率, 面部表情, 语音语调, 体温 | Continuous stream | ~1/sec |
| **Behavioral** | 浏览器URL, 收藏, 点击, 应用切换, 文件操作 | Discrete events | On action |
| **Execution Feedback** | 上一轮Executor的结果, 用户对结果的反应 | Event-driven | After execution |

Key design decisions:
- Physiological data = continuous polling (每秒采样)
- Behavioral data = event-driven (发生时才采集)
- Execution feedback = push from Executor (执行完就推送)

All three merge into `user_status_*.md` via LLM Analysis.

---

### B. LLM ANALYSIS

Transforms raw multimodal data into structured user state descriptions.

**Input**: Raw data from all three INPUT categories

**Output**: Markdown file in `input/` folder

```markdown
# User Status - 2026-04-08T10:30:00Z

## Meta
- event_type: discrete
- trigger: browser_favorites_batch
- session_id: sess_20260408_001

---

## Browsing Activity

### Pages Visited (20)
| # | URL | Title | Duration | Scroll Depth | Action |
|---|-----|-------|----------|-------------|--------|
| 1 | https://example.com/ai-home-design | AI-Powered Smart Home Design | 4min 12s | 92% | favorited |
| 2 | https://example.com/iot-trends-2026 | IoT Trends 2026 | 1min 03s | 35% | skimmed |
| 3 | https://medium.com/ai-assistant-ux | Building AI Assistants with Great UX | 6min 45s | 100% | favorited |
| 4 | https://news.ycombinator.com/item?id=xxx | Show HN: Open Source Home AI | 0min 30s | 15% | bounced |
| ... | ... | ... | ... | ... | ... |
| 20 | https://arxiv.org/abs/xxxx | Multimodal LLM for Product Design | 3min 20s | 78% | favorited |

### Favorited Pages (8)
| # | URL | Title | Topic Tags | Read Duration | Engagement |
|---|-----|-------|-----------|---------------|------------|
| 1 | https://example.com/ai-home-design | AI-Powered Smart Home Design | [smart-home, AI, IoT] | 4min 12s | high |
| 2 | https://medium.com/ai-assistant-ux | Building AI Assistants with Great UX | [AI-assistant, UX, product] | 6min 45s | very-high |
| 3 | https://blog.company.com/prototype-fast | How to Prototype in 24 Hours | [prototyping, rapid-dev] | 3min 50s | high |
| 4 | https://example.com/voice-ui-patterns | Voice UI Design Patterns | [voice-UI, smart-home] | 2min 15s | medium |
| 5 | https://arxiv.org/abs/xxxx | Multimodal LLM for Product Design | [LLM, product-design] | 3min 20s | high |
| 6 | https://dev.to/smart-home-api | Smart Home API Integration Guide | [smart-home, API, dev] | 5min 10s | high |
| 7 | https://example.com/ai-product-market | AI Product Market Fit 2026 | [AI, market, startup] | 2min 40s | medium |
| 8 | https://github.com/xxx/home-ai | Open Source Home AI Framework | [smart-home, open-source] | 4min 00s | high |

### Topic Analysis
- Primary cluster: **Smart Home + AI** (5/8 favorites)
- Secondary cluster: **AI Product Design** (3/8 favorites)
- Cross-topic interest: applying AI/LLM to physical product design

### Browsing Pattern
- Total session: 30 minutes
- Avg time per favorited page: 4min 01s
- Avg time per non-favorited page: 0min 55s
- Scroll depth (favorited): 85% avg → deep reading
- Scroll depth (non-favorited): 30% avg → quick scan and skip

---

## Physiological State
- Heart rate: 72 bpm (normal, focused)
- Facial expression: neutral-to-positive, occasional eyebrow raise (curiosity)
- Posture: leaning forward (engaged)
- Eye tracking: sustained focus on text, minimal distraction

---

## Key Signals
- HIGH: 8 favorites in 30 min (unusual volume, normal is 1-2)
- HIGH: 5/8 favorites share "smart-home" tag → strong topic focus
- MEDIUM: deep reading pattern on favorited pages (4min avg)
- LOW: no signs of frustration, fatigue, or distraction

---

## System Context
- Previous system action: none (first round)
- User feedback on previous action: N/A
- Memory reference: N/A
```

---

### C. BRAIN MODULE

The reasoning engine. Reads state + memory, outputs decisions.

**Two inputs**:
1. `user_status_*.md` — what's happening NOW
2. `Memory Store` — what happened BEFORE

**Decision process**:
```
1. Read latest user status
2. Read relevant memory (past decisions, results, feedback)
3. Reason: What does the user need? What can I do?
4. Evaluate confidence: Am I sure enough to act?
5. Output decision JSON
```

**Brain does NOT**:
- Execute any action
- Interact with the user
- Modify any system state (except writing decisions)

---

### D. EXECUTOR MODULE

Carries out Brain's decisions. Four responsibilities:

#### D1. Task Decomposition
Complex tasks are broken into ordered sub-tasks:

```json
{
  "task": "organize_docs",
  "subtasks": [
    {"id": 1, "action": "fetch_urls", "params": {"urls": [...]}, "depends_on": []},
    {"id": 2, "action": "extract_content", "depends_on": [1]},
    {"id": 3, "action": "categorize", "depends_on": [2]},
    {"id": 4, "action": "generate_summary_docs", "depends_on": [3]}
  ]
}
```

#### D2. Execute
Run each sub-task using available tools/skills. Handle errors and retries.

#### D3. Notify User
Send results to the user through the notification layer:

| Method | When to use |
|--------|------------|
| **Toast/Popup** | Task completed, needs attention |
| **Silent log** | Background task, low priority |
| **Interactive dialog** | Needs user confirmation before proceeding |

#### D4. Write Back (Feedback Loop)
After execution:
1. Write `execution_result_*.json` to Memory Store
2. Push summary back to INPUT(C) as execution feedback
3. This triggers the next round of Analysis → Brain → Executor

---

### E. MEMORY STORE

Persistent storage that gives Brain context across rounds.

**Contents**:

| Data | Purpose | Example |
|------|---------|---------|
| **Decision History** | What Brain decided | "organized 8 docs at T3" |
| **Execution Results** | What actually happened | "8 docs generated successfully" |
| **User Feedback** | How user reacted | "user spent 5min on doc_3, smiled" |
| **Learned Preferences** | Patterns over time | "user prefers detailed summaries" |

**Retention policy**:
- Hot (last 1 hour): full detail, in memory
- Warm (last 24 hours): summarized, on disk
- Cold (older): key learnings only, compressed

---

## Scenario Walkthrough

### The Complete Flow: Browse → Organize → Build Product

#### Round 1: User favorites → AI organizes docs

```
T0  INPUT(B-behavioral)
    Event: user favorited 8 URLs in 30 minutes
    ↓
T1  LLM ANALYSIS
    Output: "用户在AI产品设计领域密集研究，收藏8篇"
    ↓
T2  BRAIN
    Reads: user_status (8 favorites, focused state)
    Reads: Memory (empty — first round)
    Reasons: "大量收藏说明在做调研，整理文档会帮助用户"
    Decision: { action: "organize_docs", confidence: 0.85 }
    ↓
T3  EXECUTOR
    Decompose: fetch(8 URLs) → extract → categorize → generate
    Execute: produces 8 structured documents
    Notify: popup "已为您整理好8篇收藏的文档"
    Write back:
      → Memory: { did: organize_docs, produced: 8 docs, status: success }
      → INPUT(C): { event: execution_complete, action: organize_docs }
```

#### Round 2: User reads docs → AI detects satisfaction

```
T4  INPUT(A-physiological + B-behavioral)
    Behavioral: user opened doc_3, read 5 min; opened doc_5, read 8 min
    Physiological: smiling while reading doc_3, nodding at doc_5
    ↓
T5  LLM ANALYSIS
    Output: "用户对doc_3(智能家居)和doc_5(AI助手)高度感兴趣，情绪积极"
    ↓
T6  BRAIN
    Reads: user_status (happy with doc_3 and doc_5)
    Reads: Memory (last round organized docs, user liked 2 of them)
    Reasons: "用户对这两个概念很兴奋，做成产品原型会更有帮助"
    Decision: { action: "build_prototype", based_on: [doc_3, doc_5], confidence: 0.78 }
    ↓
T7  EXECUTOR
    Decompose: analyze_concepts → design_spec → write_code → deploy
    Execute: builds a working prototype
    Notify: popup "基于您感兴趣的概念，已为您制作了产品原型"
    Write back:
      → Memory: { did: build_prototype, based_on: [doc_3, doc_5], status: success }
      → INPUT(C): { event: execution_complete, action: build_prototype }
```

#### Round 3+: Continuous improvement...

Brain now knows:
- User researches AI products
- User responds well to organized docs
- User gets excited about smart home + AI assistant concepts
- Building prototypes was well-received

Future decisions become increasingly targeted and valuable.

---

## User Response Handling

After Executor notifies the user, there are three possible outcomes. The system must handle all three.

```
Executor notifies user: "已为您整理好8篇文档"
     │
     ├─── A. Explicit Feedback (显式反馈)
     │    User replies, clicks, reacts directly
     │    → Clear signal, write to Memory immediately
     │
     ├─── B. Implicit Signal (隐式信号)
     │    User doesn't reply, but INPUT(A+B) detects related behavior
     │    → Infer intent via LLM Analysis
     │
     └─── C. Timeout / No Signal (超时无信号)
          User doesn't reply, no detectable behavior change
          → Apply timeout strategy
```

### A. Explicit Feedback

User directly responds to the notification.

| User Action | Signal | Brain Learns |
|-------------|--------|-------------|
| "谢谢，很有用" | Positive | Increase confidence for similar actions |
| "不需要" | Negative | Decrease confidence, avoid similar actions |
| Clicks "查看" | Interested | User engaged, monitor next behavior |
| Dismisses popup | Mild negative | Lower priority, don't repeat soon |

Processing: `Executor → Memory Store → Brain reads on next round`

### B. Implicit Signal (No Reply, But Behavior Detected)

User doesn't reply to the notification, but INPUT(A+B) continues collecting data.
The system should NOT wait for a reply — it already has signal.

| Detected Behavior | Inferred Intent | Confidence |
|-------------------|----------------|------------|
| User opens the organized docs | Saw notification, interested | High |
| User opens docs + smiles + reads 5min | Very satisfied | Very high |
| User opens docs + closes after 10sec | Not what they wanted | Medium |
| User switches to unrelated app | Busy or not interested | Low |
| User's heart rate stays calm, no context switch | Didn't notice or doesn't care | Low |

Processing: `INPUT(A+B) → LLM Analysis → user_status_*.md includes inferred reaction → Brain uses it`

This is the key insight: **silence is not absence of data**. The physiological and behavioral sensors are always running. Brain should use these implicit signals rather than blocking on an explicit reply.

### C. Timeout Strategy (No Reply + No Detectable Signal)

When there is genuinely no signal — user is away, device is idle, or sensors can't detect anything useful.

```
T+0     Notification sent
        → System continues normal monitoring, does NOT block

T+5min  No signal detected
        → Status: "pending_response"
        → Brain: continue other work, don't send more notifications

T+30min Still no signal
        → Status: "likely_unseen"
        → Memory: mark action as "unacknowledged"
        → Brain: may retry notification once (different channel or time)

T+2hr   Still no signal
        → Status: "no_response"
        → Memory: mark as "user_did_not_engage"
        → Brain: lower confidence for this action type by 10%
        → Do NOT retry again
```

**Key rules**:
1. **Never block** — the system continues monitoring and reasoning regardless of reply status
2. **Never spam** — max 1 retry notification, then stop
3. **Degrade gracefully** — no response slowly reduces confidence, doesn't trigger panic
4. **Reset on engagement** — if user later opens the docs (even hours later), override timeout status with implicit signal

### How This Feeds Back Into the Loop

```
Round 1: Brain decides → Executor acts → Notifies user
                                              │
              ┌───────────────────────────────┤
              │               │               │
         A. Explicit     B. Implicit     C. Timeout
         "谢谢"         opens docs      no signal
              │               │               │
              ▼               ▼               ▼
         Memory:          INPUT(A+B):     Memory:
         feedback=        behavior →      status=
         positive         LLM infers      no_response
              │           satisfaction        │
              │               │               │
              └───────┬───────┘               │
                      ▼                       ▼
              Brain Round 2:          Brain Round 2:
              high confidence         lower confidence
              "做产品原型"              "等待，不主动行动"
```

---

## Known Limitations & Mitigations

| Issue | Status | Mitigation |
|-------|--------|------------|
| File I/O bottleneck (86k files/day) | Known | Use event-driven + batch writes, implement TTL cleanup |
| Concurrent read/write conflicts | Known | Atomic writes (tmp → rename), or migrate to message queue |
| LLM context window limits | Known | Memory summarization, sliding window of recent N snapshots |
| Privacy / sensitive data | Known | Local LLM preferred, data encryption, minimal collection |
| Over-automation risk | Known | Confidence threshold — low confidence → ask user first |
| Complex task failure | Known | Sub-task retry + rollback, partial completion reporting |

---

## File Structure

```
brainiest-mind/
├── scenarios/designer/
│   ├── main.py                    # Main loop: INPUT → Analysis → Brain → Executor → loop
│   │
│   ├── input/                     # INPUT MODULE
│   │   ├── __init__.py
│   │   ├── browser_monitor.py     # Behavioral: browser events, favorites
│   │   ├── screen_capture.py      # Physiological: video/screen
│   │   ├── sensor_adapter.py      # Physiological: heart rate, etc.
│   │   ├── feedback_receiver.py   # Execution feedback from Executor
│   │   └── user_status/           # Generated status markdown files
│   │       ├── status_001.md
│   │       └── ...
│   │
│   ├── brain/                     # BRAIN MODULE
│   │   ├── __init__.py
│   │   ├── brain.py               # Core reasoning loop
│   │   ├── memory.py              # Memory read/write interface
│   │   └── decisions/             # Generated decision files
│   │       ├── decision_001.json
│   │       └── ...
│   │
│   ├── executor/                  # EXECUTOR MODULE
│   │   ├── __init__.py
│   │   ├── executor.py            # Core execution loop
│   │   ├── task_decomposer.py     # Break complex tasks into subtasks
│   │   ├── notifier.py            # User notification (popup/message/dialog)
│   │   ├── tools/                 # Available tools/skills
│   │   │   ├── doc_organizer.py
│   │   │   ├── prototype_builder.py
│   │   │   └── ...
│   │   └── results/               # Execution result logs
│   │       ├── result_001.json
│   │       └── ...
│   │
│   └── memory/                    # MEMORY STORE
│       ├── decisions.jsonl        # Decision history
│       ├── results.jsonl          # Execution results
│       ├── feedback.jsonl         # User feedback
│       └── preferences.json       # Learned user preferences
│
├── ARCHITECTURE.md                # This file
└── requirements.txt
```
