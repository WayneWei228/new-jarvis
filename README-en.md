<div align="center">

# Jarvis

**A proactive AI assistant that sees, hears, and helps — before you ask.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![LLM](https://img.shields.io/badge/LLM-Claude%20(Bedrock)-blueviolet.svg)](https://aws.amazon.com/bedrock/)

**English** | [中文](README.zh-CN.md)

</div>

---

Jarvis is an always-on AI companion that continuously perceives your environment through **camera**, **screen capture**, **microphone**, and **browser activity** — then proactively offers contextual assistance through a native macOS floating overlay.

Unlike chatbot-style assistants that wait for commands, Jarvis **observes → reasons → acts** on its own, learning your preferences over time through an integrated feedback loop.

## Highlights

- **Multimodal Perception** — Fuses camera (OpenCV), desktop screenshots, real-time speech recognition (iFlytek ASR), and browser history into a unified context stream.
- **Proactive Intelligence** — Two trigger modes: **voice-triggered** (reacts within 3–5 s after you finish speaking) and **periodic** (background observation every 10–15 s).
- **Single-Call Reactor** — One LLM call (Claude via AWS Bedrock) handles perception, reasoning, and action selection — keeping latency low and architecture simple.
- **Native macOS Overlay** — A floating `NSPanel` + `WKWebView` panel that displays AI insights without stealing focus.
- **Preference Learning** — A feedback loop (thumbs-up / dismiss / voice cues / timeout signals) continuously refines a `preferences.json` so Jarvis adapts to you over time.
- **Modular Inputs** — Every sensor (camera, desktop, audio, browser) can be independently enabled or disabled at launch.

## Architecture

```
INPUT (camera + desktop + audio + browser)
  → Reactor (single LLM call: perceive + reason + act)
    → Native Overlay (macOS floating panel)
      → Feedback Loop (user signals → preference learning)
```

The **Reactor** is the core engine. On each cycle it receives the latest multimodal snapshot, queries the LLM once, and decides whether (and how) to surface a suggestion. User feedback — explicit or implicit — flows back into a persistent memory store that the Reactor consults on subsequent cycles.

> For the full system design — including the Brain, Executor, Memory Store, and multi-round feedback scenarios — see [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Getting Started

| Requirement | Notes |
| --- | --- |
| **macOS** | Uses `NSPanel`, `screencapture`, AppleScript |
| **Python 3.11+** | Tested on 3.11 and 3.12 |
| **Camera & Microphone permissions** | System Settings → Privacy & Security |
| **Chrome** | Required only if browser monitoring is enabled |

### Installation

```bash
git clone https://github.com/<your-org>/jarvis.git
cd jarvis

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root:

```bash
# AWS Bedrock — Claude multimodal reasoning (vision + text)
AWS_BEARER_TOKEN_BEDROCK=your_token_here
AWS_DEFAULT_REGION=ap-northeast-1

# iFlytek — real-time Chinese speech recognition (WebSocket streaming ASR)
IFLYTEK_APP_ID=your_app_id
IFLYTEK_API_KEY=your_api_key
IFLYTEK_API_SECRET=your_api_secret
```

### Run

```bash
source .venv/bin/activate
python main.py
```

A floating panel will appear on the right side of your screen, showing Jarvis's observations and suggestions.

Press `Ctrl+C` to stop.

## Usage

### Command-Line Options

```bash
# Full mode (all sensors enabled, default)
python main.py

# Disable individual sensors
python main.py --no-camera       # Skip webcam capture
python main.py --no-desktop      # Skip desktop screenshots
python main.py --no-audio        # Skip microphone / ASR
python main.py --no-browser      # Skip Chrome history monitoring

# Tune observation frequency
python main.py --periodic 15             # Background cycle interval (default: 10 s)
python main.py --camera-interval 5       # Webcam capture interval  (default: 3 s)
python main.py --desktop-interval 10     # Screenshot interval      (default: 5 s)

# Combine freely
python main.py --no-camera --periodic 20
```

### Feedback System

Jarvis learns from every interaction — no hand-written rules required:

| Signal | Source | Effect |
| --- | --- | --- |
| **"Useful" button** | Overlay panel | Reinforces similar suggestions |
| **Dismiss / close** | Overlay panel | Reduces confidence for this type |
| **Voice praise** ("nice", "thanks") | Microphone | Positive reinforcement |
| **Voice rejection** ("stop", "not now") | Microphone | Negative reinforcement |
| **Card ignored** (auto-dismiss timeout) | System | Mild negative signal |

Accumulated feedback is periodically distilled by the LLM into preference rules and persisted to `memory/preferences.json`.

## Project Structure

```
jarvis/
├── main.py                    # Entry point & CLI arg parsing
├── reactor.py                 # Core engine — perceive + reason + act in one LLM call
│
├── input/                     # Sensor layer
│   ├── __init__.py            #   InputCollector: unified sensor scheduler
│   ├── screen_capture.py      #   Webcam via OpenCV
│   ├── desktop_capture.py     #   Desktop screenshots via screencapture CLI
│   ├── sensor_adapter.py      #   Microphone → iFlytek streaming ASR
│   ├── browser_monitor.py     #   Chrome History (SQLite)
│   ├── feedback_receiver.py   #   Collects explicit user feedback
│   └── models.py              #   Shared data models
│
├── executor/                  # Output layer
│   ├── executor.py            #   Action executor & task decomposition
│   ├── overlay.py             #   NativeOverlay controller (subprocess IPC)
│   └── overlay_window.py      #   Standalone AppKit process (NSPanel + WKWebView)
│
├── brain/                     # Memory & reasoning
│   ├── brain.py               #   Brain reasoning module
│   └── memory.py              #   MemoryStore (JSONL + preferences.json)
│
├── iflytek_client.py          # iFlytek WebSocket ASR client
├── recorder.py                # Audio recording via sounddevice
│
├── memory/                    # Persistent data (auto-generated, gitignored)
│   ├── preferences.json       #   Learned user preferences
│   ├── decisions.jsonl        #   Historical decisions
│   └── feedback.jsonl         #   User feedback log
│
├── requirements.txt
├── ARCHITECTURE.md            # Detailed system design document
└── .env                       # API keys (not committed)
```

## macOS Permissions

On first launch, macOS will prompt for the following permissions — grant all for full functionality:

| Permission | Purpose |
| --- | --- |
| **Camera** | Observe user presence and expressions |
| **Microphone** | Real-time speech recognition |
| **Screen Recording** | Desktop screenshots for context |
| **Accessibility** | Detect active window position (AppleScript) |

These can be managed in **System Settings → Privacy & Security**.

## Tech Stack

| Component | Technology |
| --- | --- |
| LLM Reasoning | Claude Sonnet via AWS Bedrock |
| Speech Recognition | iFlytek WebSocket streaming ASR |
| Camera Capture | OpenCV |
| Audio Recording | sounddevice + NumPy |
| Native Overlay | PyObjC (AppKit `NSPanel` + `WKWebView`) |
| Async Runtime | asyncio + aiohttp |

## Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feat/my-feature`
3. **Commit** your changes: `git commit -m "feat: add my feature"`
4. **Push** to your branch: `git push origin feat/my-feature`
5. **Open** a Pull Request

## License

This project is licensed under the [MIT License](LICENSE).
