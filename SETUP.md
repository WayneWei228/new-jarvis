# Jarvis 启动指南

## 架构概览

```
Jarvis Backend (Python)              Web UI (React + Vite)
┌─────────────────────┐              ┌──────────────────┐
│  main.py            │              │  test_mcp/       │
│  ├── InputCollector  │   WebSocket  │  └── src/App.tsx │
│  │   (camera/mic/   │◄────────────►│     (光斑动画     │
│  │    desktop/browser)│  ws://8765  │      摄像头/屏幕  │
│  ├── Reactor         │              │      音频可视化)  │
│  │   (LLM 推理)      │              └──────────────────┘
│  └── NativeOverlay   │              ┌──────────────────┐
│      (macOS NSPanel) │              │  pywebview 窗口   │
└─────────────────────┘              │  (无边框 app 模式) │
                                     └──────────────────┘
```

**两套 UI 可以同时运行：**
- **NativeOverlay** — macOS 原生浮动面板（Action Cards + Thinking Panel），由 main.py 自动启动
- **Web UI** — React 全屏动效界面（光斑、摄像头 dithering、音频波形），需要手动启动

## 前置要求

- macOS（使用了 NSPanel、screencapture、AppleScript）
- Python 3.11+
- Node.js 18+（用于 Web UI）
- 摄像头 + 麦克风权限（系统设置 > 隐私与安全性）

## 第一步：安装依赖

```bash
cd new-jarvis

# Python 依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pywebview   # Web UI 窗口

# Web UI 依赖
cd test_mcp
npm install
cd ..
```

## 第二步：配置环境变量

创建 `.env` 文件（项目根目录）：

```bash
# AWS Bedrock (Claude API)
AWS_BEARER_TOKEN_BEDROCK=your_token
AWS_DEFAULT_REGION=ap-northeast-1

# Google Gemini (Tick 模式用)
GOOGLE_API_KEY=your_key

# 讯飞 ASR
IFLYTEK_APP_ID=your_app_id
IFLYTEK_API_KEY=your_api_key
IFLYTEK_API_SECRET=your_secret

# OpenAI (Streaming 模式用)
OPENAI_API_KEY=your_key
```

## 第三步：启动

需要打开 **两个终端窗口**。

### 终端 1 — 启动 Web UI

```bash
cd new-jarvis/test_mcp
npm run dev
```

看到 `Local: http://localhost:5173/` 说明成功。

### 终端 2 — 启动 Jarvis 后端

```bash
cd new-jarvis
source .venv/bin/activate

# Tick 模式（默认，Gemini Flash 周期观察）
python main.py

# 或 Streaming 模式（OpenAI Realtime，持续感知）
python main.py --streaming
```

### 打开 Web UI 窗口

新开一个终端，或者在 Jarvis 启动后执行：

```bash
cd new-jarvis/test_mcp
python app_window.py
```

这会打开一个无边框原生窗口，显示 Web UI。

## 常用启动参数

```bash
# 关闭摄像头（不需要摄像头时）
python main.py --no-camera

# 关闭桌面截屏
python main.py --no-desktop

# 调整 tick 间隔（秒）
python main.py --periodic 5

# Streaming 模式 + 自定义视觉间隔
python main.py --streaming --vision-interval 10
```

## 数据流

```
1. InputCollector 采集传感器数据（摄像头/麦克风/桌面截屏/浏览器）
2. Reactor (Tick 或 Streaming) 调用 LLM 分析，决定是否行动
3. 行动结果通过 NativeOverlay 显示为 macOS 浮动卡片
4. Web UI 通过 WebSocket 接收 AI 状态，驱动光斑动画和文字流
```

## 停止

- `Ctrl+C` 停止 Jarvis 后端
- `Ctrl+C` 停止 Vite dev server
- 关闭 pywebview 窗口即退出 UI

## 故障排除

| 问题 | 原因 | 解决 |
|------|------|------|
| Web UI 显示 "Loading camera..." | 浏览器未授权摄像头 | 点击允许，或忽略（会自动显示错误提示） |
| Web UI 控制台 WebSocket 报错 | Jarvis 后端未启动 | 先启动 `python main.py`，UI 会自动重连 |
| 光斑动画卡顿 | 粒子数太多 | 用 pywebview 打开而不是浏览器 |
| pywebview 窗口太大/小 | 屏幕分辨率不匹配 | 修改 `app_window.py` 中的 width/height |
| 麦克风无声音 | 系统权限未授予 | 系统设置 > 隐私与安全性 > 麦克风 |
