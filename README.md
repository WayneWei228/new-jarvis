# Jarvis — Proactive AI Assistant

一个坐在你旁边的 AI 朋友。通过摄像头、屏幕截图、麦克风和浏览器，持续感知你在做什么，在合适的时候主动帮你。

## 架构

```
INPUT (camera + desktop + audio + browser)
  → Reactor (单次 LLM 调用: 感知 + 推理 + 行动)
    → Native Overlay (macOS 浮动面板)
      → Feedback Loop (用户反馈 → 偏好学习)
```

**Reactor** 是核心引擎，两种触发模式：
- **语音触发** — 检测到你说完一句话（2s 静默）后立即反应
- **周期触发** — 每 10-15s 背景观察一轮

**反馈系统** — 不靠硬编码规则，通过你的反馈持续学习偏好：
- 浮动面板上的「有用」/「关闭」按钮
- 语音中对 AI 行为的评价（"别烦我" / "这个不错"）
- 卡片是否被忽略（超时自动消失）
- 累计反馈后 LLM 自动提炼偏好规则，写入 `memory/preferences.json`

## 前置要求

- macOS（使用了 NSPanel、screencapture、AppleScript）
- Python 3.11+
- 摄像头 + 麦克风权限（系统设置 → 隐私与安全性）
- Chrome（如果需要浏览器监控）

## 安装

```bash
cd new-jarvis

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

## 配置

创建 `.env` 文件：

```bash
# AWS Bedrock (Claude API)
AWS_BEARER_TOKEN_BEDROCK=your_token_here
AWS_DEFAULT_REGION=ap-northeast-1

# 讯飞实时语音转写
IFLYTEK_APP_ID=your_app_id
IFLYTEK_API_KEY=your_api_key
IFLYTEK_API_SECRET=your_api_secret
```

**AWS Bedrock** — 用于 Claude Sonnet 多模态推理（视觉 + 文字）。
**讯飞 iFlytek** — 用于实时中文语音识别（WebSocket 流式 ASR）。

## 运行

```bash
source .venv/bin/activate
python main.py
```

启动后会在屏幕右侧弹出浮动面板，显示 AI 的观察和建议。

### 命令行参数

```bash
# 完整运行（默认）
python main.py

# 关闭摄像头（隐私 / 没有摄像头）
python main.py --no-camera

# 关闭某些输入
python main.py --no-desktop    # 不截屏
python main.py --no-audio      # 不录音
python main.py --no-browser    # 不监控浏览器

# 调整频率
python main.py --periodic 15           # 周期观察间隔（秒，默认 10）
python main.py --camera-interval 5     # 摄像头捕获间隔（秒，默认 3）
python main.py --desktop-interval 10   # 桌面截屏间隔（秒，默认 5）

# 组合使用
python main.py --no-camera --periodic 20
```

### 停止

`Ctrl+C` 退出。

## 目录结构

```
new-jarvis/
├── main.py                  # 入口
├── reactor.py               # 核心引擎（感知 + 推理 + 行动 + 偏好学习）
├── input/                   # 输入层
│   ├── __init__.py          #   InputCollector 统一调度
│   ├── screen_capture.py    #   摄像头 (OpenCV)
│   ├── desktop_capture.py   #   桌面截屏 (screencapture CLI)
│   ├── sensor_adapter.py    #   麦克风 → 讯飞 ASR
│   └── browser_monitor.py   #   Chrome History SQLite
├── executor/                # 输出层
│   ├── overlay.py           #   NativeOverlay 控制器（subprocess IPC）
│   └── overlay_window.py    #   独立 AppKit 进程（NSPanel + WKWebView）
├── brain/                   # 记忆
│   └── memory.py            #   MemoryStore (JSONL + preferences.json)
├── iflytek_client.py        # 讯飞 WebSocket ASR 客户端
├── recorder.py              # 音频录制 (sounddevice)
└── memory/                  # 持久化数据（自动生成）
    ├── preferences.json     #   学习到的用户偏好（永久）
    ├── decisions.jsonl       #   历史决策
    └── feedback.jsonl        #   用户反馈记录
```

## macOS 权限

首次运行时系统会弹窗请求权限，全部允许：

- **摄像头** — 观察用户状态
- **麦克风** — 语音识别
- **辅助功能** — 检测活动窗口位置（AppleScript）
- **屏幕录制** — 桌面截屏
