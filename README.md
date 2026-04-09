<div align="center">

# Jarvis

**一个主动感知、主动帮助的 AI 助手 — 不用你开口。**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![LLM](https://img.shields.io/badge/LLM-Claude%20(Bedrock)-blueviolet.svg)](https://aws.amazon.com/bedrock/)

[English](README.md) | **中文**

</div>

---

Jarvis 是一个常驻运行的 AI 伙伴，通过**摄像头**、**桌面截屏**、**麦克风**和**浏览器活动**持续感知你的环境，然后通过 macOS 原生浮动面板主动提供上下文相关的帮助。

与传统等待指令的聊天式助手不同，Jarvis 自主完成**观察 → 推理 → 行动**的闭环，并通过内置的反馈系统持续学习你的偏好。

## 核心特性

- **多模态感知** — 融合摄像头 (OpenCV)、桌面截屏、实时语音识别（讯飞 ASR）和浏览器历史，构建统一的上下文流。
- **主动智能** — 双触发模式：**语音触发**（检测到你说完话后 3–5 秒内反应）和**周期触发**（每 10–15 秒后台观察一轮）。
- **单次调用 Reactor** — 一次 LLM 调用（通过 AWS Bedrock 调用 Claude）同时完成感知、推理和行动决策，保持低延迟和简洁架构。
- **原生 macOS 浮动面板** — 基于 `NSPanel` + `WKWebView` 的浮动面板，展示 AI 洞察而不抢占焦点。
- **偏好学习** — 反馈闭环（点赞 / 关闭 / 语音评价 / 超时信号）持续优化 `preferences.json`，让 Jarvis 越用越懂你。
- **模块化输入** — 每个传感器（摄像头、桌面、音频、浏览器）都可以在启动时独立开关。

## 架构

```
INPUT（摄像头 + 桌面截屏 + 音频 + 浏览器）
  → Reactor（单次 LLM 调用：感知 + 推理 + 行动）
    → 原生浮动面板（macOS Overlay）
      → 反馈闭环（用户信号 → 偏好学习）
```

**Reactor** 是核心引擎。每个周期接收最新的多模态快照，调用一次 LLM，决定是否（以及如何）向你展示建议。用户反馈——无论是显式的还是隐式的——都会回流到持久化的记忆存储中，供 Reactor 在后续周期参考。

> 完整的系统设计——包括 Brain、Executor、Memory Store 和多轮反馈场景——请参阅 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 快速开始

### 前置要求

| 要求 | 说明 |
|---|---|
| **macOS** | 使用了 `NSPanel`、`screencapture`、AppleScript |
| **Python 3.11+** | 已在 3.11 和 3.12 上测试 |
| **摄像头和麦克风权限** | 系统设置 → 隐私与安全性 |
| **Chrome** | 仅在启用浏览器监控时需要 |

### 安装

```bash
git clone https://github.com/<your-org>/jarvis.git
cd jarvis

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### 配置

在项目根目录创建 `.env` 文件：

```bash
# AWS Bedrock — Claude 多模态推理（视觉 + 文字）
AWS_BEARER_TOKEN_BEDROCK=your_token_here
AWS_DEFAULT_REGION=ap-northeast-1

# 讯飞 iFlytek — 实时中文语音识别（WebSocket 流式 ASR）
IFLYTEK_APP_ID=your_app_id
IFLYTEK_API_KEY=your_api_key
IFLYTEK_API_SECRET=your_api_secret
```

### 启动

```bash
source .venv/bin/activate
python main.py
```

启动后会在屏幕右侧弹出浮动面板，显示 Jarvis 的观察和建议。

按 `Ctrl+C` 退出。

## 使用方法

### 命令行参数

```bash
# 完整模式（默认开启所有传感器）
python main.py

# 关闭单个传感器
python main.py --no-camera       # 不使用摄像头
python main.py --no-desktop      # 不截取桌面
python main.py --no-audio        # 不录音 / 不做语音识别
python main.py --no-browser      # 不监控 Chrome 浏览记录

# 调整观察频率
python main.py --periodic 15             # 后台观察周期（默认 10 秒）
python main.py --camera-interval 5       # 摄像头捕获间隔（默认 3 秒）
python main.py --desktop-interval 10     # 桌面截屏间隔（默认 5 秒）

# 自由组合
python main.py --no-camera --periodic 20
```

### 反馈系统

Jarvis 从每一次交互中学习——无需手写规则：

| 信号 | 来源 | 效果 |
|---|---|---|
| **"有用" 按钮** | 浮动面板 | 强化类似建议 |
| **关闭 / 忽略** | 浮动面板 | 降低此类建议的置信度 |
| **语音表扬**（"不错"、"谢谢"） | 麦克风 | 正向强化 |
| **语音否定**（"别烦我"、"不需要"） | 麦克风 | 负向强化 |
| **卡片被忽略**（超时自动消失） | 系统 | 轻微负向信号 |

累积的反馈会由 LLM 定期提炼为偏好规则，持久化到 `memory/preferences.json`。

## 项目结构

```
jarvis/
├── main.py                    # 入口 & 命令行参数解析
├── reactor.py                 # 核心引擎 — 单次 LLM 调用完成感知 + 推理 + 行动
│
├── input/                     # 传感器层
│   ├── __init__.py            #   InputCollector：统一传感器调度
│   ├── screen_capture.py      #   摄像头（OpenCV）
│   ├── desktop_capture.py     #   桌面截屏（screencapture CLI）
│   ├── sensor_adapter.py      #   麦克风 → 讯飞流式 ASR
│   ├── browser_monitor.py     #   Chrome 浏览历史（SQLite）
│   ├── feedback_receiver.py   #   收集用户显式反馈
│   └── models.py              #   共享数据模型
│
├── executor/                  # 输出层
│   ├── executor.py            #   动作执行器 & 任务分解
│   ├── overlay.py             #   NativeOverlay 控制器（子进程 IPC）
│   └── overlay_window.py      #   独立 AppKit 进程（NSPanel + WKWebView）
│
├── brain/                     # 记忆与推理
│   ├── brain.py               #   Brain 推理模块
│   └── memory.py              #   MemoryStore（JSONL + preferences.json）
│
├── iflytek_client.py          # 讯飞 WebSocket ASR 客户端
├── recorder.py                # 音频录制（sounddevice）
│
├── memory/                    # 持久化数据（自动生成，已 gitignore）
│   ├── preferences.json       #   学习到的用户偏好
│   ├── decisions.jsonl        #   历史决策记录
│   └── feedback.jsonl         #   用户反馈日志
│
├── requirements.txt
├── ARCHITECTURE.md            # 详细系统设计文档
└── .env                       # API 密钥（不提交）
```

## macOS 权限

首次启动时 macOS 会弹窗请求以下权限——请全部允许以获得完整功能：

| 权限 | 用途 |
|---|---|
| **摄像头** | 观察用户状态和表情 |
| **麦克风** | 实时语音识别 |
| **屏幕录制** | 桌面截屏以获取上下文 |
| **辅助功能** | 检测活动窗口位置（AppleScript） |

可在 **系统设置 → 隐私与安全性** 中管理。

## 技术栈

| 组件 | 技术 |
|---|---|
| LLM 推理 | Claude Sonnet（通过 AWS Bedrock） |
| 语音识别 | 讯飞 WebSocket 流式 ASR |
| 摄像头捕获 | OpenCV |
| 音频录制 | sounddevice + NumPy |
| 原生浮动面板 | PyObjC（AppKit `NSPanel` + `WKWebView`） |
| 异步运行时 | asyncio + aiohttp |

## 参与贡献

欢迎贡献代码！参与方式：

1. **Fork** 本仓库
2. **创建**功能分支：`git checkout -b feat/my-feature`
3. **提交**更改：`git commit -m "feat: add my feature"`
4. **推送**到你的分支：`git push origin feat/my-feature`
5. **发起** Pull Request

请保持 PR 聚焦，并附上清晰的变更说明。

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。

---

<div align="center">
  <sub>Built with curiosity and Claude.</sub>
</div>
