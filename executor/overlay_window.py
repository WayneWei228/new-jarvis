#!/usr/bin/env python3
"""
Overlay Window Process — 独立运行的 AppKit 进程。

两种面板:
1. Action Cards — 临时弹窗，显示 AI 的行动结果（右侧）
2. Thinking Panel — 常驻面板，实时滚动显示 AI 思考过程（左侧）

从 stdin 读取 JSON 命令，用户点击按钮时通过 stdout 返回反馈。
由 overlay.py (NativeOverlay) 通过 subprocess 启动。
"""

import json
import os
import subprocess
import sys
import time
import threading
import signal

import objc
from Foundation import NSObject, NSTimer, NSData
from AppKit import (
    NSApplication,
    NSPanel,
    NSScreen,
    NSBackingStoreBuffered,
    NSColor,
    NSMakeRect,
    NSFloatingWindowLevel,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskUtilityWindow,
    NSApp,
)
from WebKit import WKWebView, WKWebViewConfiguration


# ── Global State ─────────────────────────────────────────

active_panels = {}  # card_id → (NSPanel, created_at, timeout)
thinking_ref = None  # (NSPanel, WKWebView) or None


def send_feedback(feedback_type: str, card_id: str):
    """Write feedback JSON to stdout for parent process."""
    try:
        line = json.dumps({"feedback": feedback_type, "card_id": card_id})
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:
        pass


# ── Feedback Handler (WKScriptMessageHandler) ───────────

class FeedbackHandler(NSObject):
    """Receives messages from WKWebView JavaScript button clicks."""

    @objc.typedSelector(b"v@:@@")
    def userContentController_didReceiveScriptMessage_(self, controller, message):
        body = message.body()
        try:
            feedback_type = body["type"]
            card_id = body.get("card_id", "")
        except (KeyError, TypeError):
            return

        # Handle URL open requests — open in default browser
        if feedback_type == "open_url":
            url = body.get("url", "")
            if url:
                from AppKit import NSWorkspace
                from Foundation import NSURL
                NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))
            return

        send_feedback(feedback_type, card_id)

        if feedback_type == "dismissed" and card_id in active_panels:
            active_panels[card_id][0].close()
            del active_panels[card_id]
        elif feedback_type == "helpful" and card_id in active_panels:
            active_panels[card_id][0].close()
            del active_panels[card_id]


_feedback_handler = None

def get_feedback_handler():
    global _feedback_handler
    if _feedback_handler is None:
        _feedback_handler = FeedbackHandler.alloc().init()
    return _feedback_handler


# ── Active Window Detection ──────────────────────────────

def get_active_window_info() -> dict:
    script = '''
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        try
            set frontWin to first window of frontApp
            set {x, y} to position of frontWin
            set {w, h} to size of frontWin
            return appName & "|" & x & "|" & y & "|" & w & "|" & h
        on error
            return appName & "|0|0|800|600"
        end try
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=3
        )
        parts = result.stdout.strip().split("|")
        if len(parts) >= 5:
            return {
                "app": parts[0],
                "x": int(parts[1]),
                "y": int(parts[2]),
                "w": int(parts[3]),
                "h": int(parts[4]),
            }
    except Exception:
        pass
    return {"app": "unknown", "x": 0, "y": 0, "w": 800, "h": 600}


def html_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def linkify(escaped_html: str) -> str:
    """Convert markdown-style [text](url) links in already-escaped HTML to clickable anchors."""
    import re
    # Match [text](url) in escaped HTML — brackets/parens are not escaped by html_escape
    # Use jarvis message handler to open URL in default browser
    return re.sub(
        r'\[([^\]]+)\]\((https?://[^)]+)\)',
        r'<a href="#" style="color:#6ea8fe;text-decoration:underline;cursor:pointer;" '
        r'onclick="openUrl(\'\2\');return false;">\1</a>',
        escaped_html,
    )


# ── Thinking Panel ───────────────────────────────────────

THINKING_HTML = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
    font-family: 'SF Mono', 'Menlo', 'Consolas', monospace;
    background: rgba(12, 12, 18, 0.98);
    color: #ccc;
    padding: 32px 14px 14px 14px;
    -webkit-user-select: text;
}
.header {
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #00ff88;
    margin-bottom: 10px;
    font-weight: 600;
}
#log {
    overflow-y: auto;
    max-height: calc(100vh - 56px);
    padding-bottom: 10px;
}
#log::-webkit-scrollbar { width: 3px; }
#log::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }
.e {
    font-size: 11px;
    line-height: 1.5;
    padding: 1px 0;
}
.t { color: #444; font-size: 10px; margin-right: 6px; }
.e-input { color: #777; }
.e-reason { color: #aaa; }
.e-decision { color: #ffd700; }
.e-action { color: #00ff88; font-weight: 600; }
.e-feedback { color: #6495ed; }
.e-error { color: #ff6b6b; }
.e-sep {
    color: #555;
    border-top: 1px solid #282828;
    margin-top: 8px;
    padding-top: 6px;
    font-size: 10px;
    font-family: -apple-system, sans-serif;
}
</style></head><body>
<div class="header">AI Thinking</div>
<div id="log"></div>
<script>
function addEntries(entries) {
    var log = document.getElementById('log');
    entries.forEach(function(e) {
        var div = document.createElement('div');
        var cls = 'e e-' + (e.type || 'input');
        div.className = cls;
        if (e.type === 'separator') {
            div.innerHTML = e.text;
        } else {
            var now = new Date();
            var h = String(now.getHours()).padStart(2,'0');
            var m = String(now.getMinutes()).padStart(2,'0');
            var s = String(now.getSeconds()).padStart(2,'0');
            div.innerHTML = '<span class="t">' + h + ':' + m + ':' + s + '</span>' + e.text;
        }
        log.appendChild(div);
    });
    while (log.children.length > 300) { log.removeChild(log.firstChild); }
    if (log.lastChild) { log.lastChild.scrollIntoView({behavior:'smooth'}); }
}
</script>
</body></html>'''


def create_thinking_panel() -> tuple:
    """Create the persistent thinking log panel (left side of screen)."""
    screen = NSScreen.mainScreen().frame()
    screen_h = screen.size.height

    width = 340
    height = 520
    x = 20
    y = screen_h - 80 - height  # 80px from top

    style = (
        NSWindowStyleMaskTitled
        | NSWindowStyleMaskClosable
        | NSWindowStyleMaskFullSizeContentView
        | NSWindowStyleMaskNonactivatingPanel
        | NSWindowStyleMaskUtilityWindow
    )

    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, width, height),
        style,
        NSBackingStoreBuffered,
        False,
    )

    panel.setLevel_(NSFloatingWindowLevel)
    panel.setTitle_("Jarvis Thinking")
    panel.setTitlebarAppearsTransparent_(True)
    panel.setMovableByWindowBackground_(True)
    panel.setHidesOnDeactivate_(False)
    panel.setBecomesKeyOnlyIfNeeded_(True)
    panel.setFloatingPanel_(True)
    panel.setAlphaValue_(0.92)
    panel.setBackgroundColor_(
        NSColor.colorWithRed_green_blue_alpha_(0.05, 0.05, 0.07, 0.98)
    )

    config = WKWebViewConfiguration.alloc().init()
    webview = WKWebView.alloc().initWithFrame_configuration_(
        NSMakeRect(0, 0, width, height), config
    )
    webview.setValue_forKey_(False, "drawsBackground")
    webview.loadHTMLString_baseURL_(THINKING_HTML, None)

    panel.setContentView_(webview)
    panel.orderFront_(None)

    return (panel, webview)


# ── Action Card Builder ──────────────────────────────────

def build_html(data: dict) -> str:
    card_type = data.get("type", "info")
    card_id = data.get("card_id", "unknown")
    title = html_escape(data.get("title", "Jarvis"))
    body = html_escape(data.get("body", ""))

    type_colors = {
        "thinking": "#00ff88",
        "result": "#ffd700",
        "suggestion": "#6495ed",
        "warning": "#ff6b6b",
        "info": "#888",
    }
    accent = type_colors.get(card_type, "#888")

    type_labels = {
        "thinking": "AI Thinking...",
        "result": "Result",
        "suggestion": "Suggestion",
        "warning": "Heads Up",
        "info": "Info",
    }
    label = type_labels.get(card_type, "Info")

    body_html = linkify(body).replace('\n', '<br>')

    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', 'Helvetica Neue', sans-serif;
    background: rgba(15, 15, 22, 0.98);
    color: #e0e0e0;
    padding: 32px 18px 14px 18px;
    -webkit-user-select: text;
}}
.label {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: {accent};
    margin-bottom: 8px;
    font-weight: 600;
}}
.title {{
    font-size: 15px;
    font-weight: 600;
    line-height: 1.4;
    margin-bottom: 10px;
    color: #fff;
}}
.body {{
    font-size: 13px;
    line-height: 1.7;
    color: #bbb;
    max-height: 200px;
    overflow-y: auto;
}}
.body::-webkit-scrollbar {{ width: 3px; }}
.body::-webkit-scrollbar-thumb {{ background: #333; border-radius: 2px; }}
.actions {{
    margin-top: 14px;
    display: flex;
    gap: 8px;
    border-top: 1px solid rgba(255,255,255,0.06);
    padding-top: 10px;
}}
.btn {{
    font-size: 11px;
    padding: 5px 14px;
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.1);
    background: rgba(255,255,255,0.05);
    color: #aaa;
    cursor: pointer;
}}
.btn:hover {{
    background: rgba(255,255,255,0.12);
    color: #fff;
}}
.btn-accent {{
    background: {accent}22;
    color: {accent};
    border-color: {accent}44;
}}
</style></head><body>
<div class="label">{label}</div>
<div class="title">{title}</div>
<div class="body">{body_html}</div>
<div class="actions">
    <div class="btn btn-accent" onclick="sendFeedback('helpful')">有用</div>
    <div class="btn" onclick="sendFeedback('dismissed')">关闭</div>
</div>
<script>
function sendFeedback(type) {{
    try {{
        window.webkit.messageHandlers.jarvis.postMessage({{
            type: type,
            card_id: "{card_id}"
        }});
    }} catch(e) {{}}
}}
function openUrl(url) {{
    try {{
        window.webkit.messageHandlers.jarvis.postMessage({{
            type: "open_url",
            url: url,
            card_id: "{card_id}"
        }});
    }} catch(e) {{
        window.location.href = url;
    }}
}}
</script>
</body></html>'''


def create_panel(data: dict) -> NSPanel:
    """Create a floating action card NSPanel (right side, near active window)."""
    screen = NSScreen.mainScreen().frame()
    screen_w = screen.size.width
    screen_h = screen.size.height

    win_info = get_active_window_info()
    width = 380
    height = 320

    win_x = win_info.get("x", 0)
    win_w = win_info.get("w", 800)
    x = min(win_x + win_w + 12, screen_w - width - 10)
    win_y = win_info.get("y", 100)
    y = screen_h - win_y - height

    x = max(10, min(x, screen_w - width - 10))
    y = max(50, min(y, screen_h - height - 50))

    style = (
        NSWindowStyleMaskTitled
        | NSWindowStyleMaskClosable
        | NSWindowStyleMaskFullSizeContentView
        | NSWindowStyleMaskNonactivatingPanel
        | NSWindowStyleMaskUtilityWindow
    )

    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, width, height),
        style,
        NSBackingStoreBuffered,
        False,
    )

    panel.setLevel_(NSFloatingWindowLevel)
    panel.setTitle_("Jarvis")
    panel.setTitlebarAppearsTransparent_(True)
    panel.setMovableByWindowBackground_(True)
    panel.setHidesOnDeactivate_(False)
    panel.setBecomesKeyOnlyIfNeeded_(True)
    panel.setFloatingPanel_(True)
    panel.setAlphaValue_(0.96)
    panel.setBackgroundColor_(
        NSColor.colorWithRed_green_blue_alpha_(0.06, 0.06, 0.09, 0.98)
    )

    config = WKWebViewConfiguration.alloc().init()
    handler = get_feedback_handler()
    config.userContentController().addScriptMessageHandler_name_(handler, "jarvis")

    webview = WKWebView.alloc().initWithFrame_configuration_(
        NSMakeRect(0, 0, width, height), config
    )
    webview.setValue_forKey_(False, "drawsBackground")
    webview.loadHTMLString_baseURL_(build_html(data), None)

    panel.setContentView_(webview)
    panel.orderFront_(None)

    return panel


# ── Stdin Reader Thread ───────────────────────────────────

cmd_buffer = []
cmd_lock = threading.Lock()

def stdin_reader():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
            with cmd_lock:
                cmd_buffer.append(cmd)
        except json.JSONDecodeError:
            pass
    # stdin closed → parent died, schedule quit
    with cmd_lock:
        cmd_buffer.append({"action": "quit"})


# ── Main: AppKit Event Loop ──────────────────────────────

def main():
    global thinking_ref

    _parent_pid = os.getppid()

    # Handle SIGINT/SIGTERM gracefully
    def _signal_quit(signum, frame):
        with cmd_lock:
            cmd_buffer.append({"action": "quit"})
    signal.signal(signal.SIGINT, _signal_quit)
    signal.signal(signal.SIGTERM, _signal_quit)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(0)

    class Ticker(NSObject):
        def init(self):
            self = objc.super(Ticker, self).init()
            return self

        @objc.typedSelector(b"v@:@")
        def tick_(self, timer):
            global thinking_ref

            # If parent process died, quit immediately
            if os.getppid() != _parent_pid:
                with cmd_lock:
                    cmd_buffer.append({"action": "quit"})

            with cmd_lock:
                cmds = list(cmd_buffer)
                cmd_buffer.clear()

            for cmd in cmds:
                action = cmd.get("action")

                if action == "show":
                    try:
                        card_id = cmd.get("card_id", f"card_{int(time.time())}")
                        cmd["card_id"] = card_id
                        p = create_panel(cmd)
                        timeout = cmd.get("timeout", 30)
                        active_panels[card_id] = (p, time.time(), timeout)
                    except Exception as e:
                        sys.stderr.write(f"Panel error: {e}\n")
                        sys.stderr.flush()

                elif action == "thinking":
                    try:
                        # Create thinking panel on first use
                        if thinking_ref is None:
                            thinking_ref = create_thinking_panel()

                        entries = cmd.get("entries", [])
                        if entries:
                            _, webview = thinking_ref
                            entries_json = json.dumps(entries, ensure_ascii=False)
                            js = f"addEntries({entries_json});"
                            webview.evaluateJavaScript_completionHandler_(js, None)
                    except Exception as e:
                        sys.stderr.write(f"Thinking panel error: {e}\n")
                        sys.stderr.flush()

                elif action == "close_all":
                    for card_id, (p, _, _) in active_panels.items():
                        p.close()
                        send_feedback("closed_by_system", card_id)
                    active_panels.clear()

                elif action == "quit":
                    for card_id, (p, _, _) in active_panels.items():
                        p.close()
                    active_panels.clear()
                    if thinking_ref:
                        thinking_ref[0].close()
                        thinking_ref = None
                    NSApp.terminate_(None)
                    return

            # Auto-dismiss expired action cards
            now = time.time()
            expired_ids = []
            for card_id, (p, created, timeout) in active_panels.items():
                if now - created > timeout:
                    p.close()
                    send_feedback("expired", card_id)
                    expired_ids.append(card_id)
            for card_id in expired_ids:
                del active_panels[card_id]

    ticker = Ticker.alloc().init()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.3, ticker, b"tick:", None, True
    )

    t = threading.Thread(target=stdin_reader, daemon=True)
    t.start()

    app.run()


if __name__ == "__main__":
    main()
