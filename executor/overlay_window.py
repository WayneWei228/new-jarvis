#!/usr/bin/env python3
"""
Overlay Window Process — 独立运行的 AppKit 进程。

从 stdin 读取 JSON 命令，显示/关闭浮动面板。
由 overlay.py (NativeOverlay) 通过 subprocess 启动。
"""

import json
import subprocess
import sys
import time
import threading

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


# ── Active Window Detection ──────────────────────────────

def get_active_window_info() -> dict:
    """Get frontmost window's position and size via AppleScript."""
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


# ── Panel Builder ─────────────────────────────────────────

def build_html(data: dict) -> str:
    card_type = data.get("type", "info")
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

    body_html = body.replace('\n', '<br>')

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
.typing::after {{
    content: '▌';
    animation: blink 1s step-end infinite;
    color: {accent};
}}
@keyframes blink {{ 50% {{ opacity: 0; }} }}
</style></head><body>
<div class="label">{label}</div>
<div class="title{' typing' if card_type == 'thinking' else ''}">{title}</div>
<div class="body">{body_html}</div>
<div class="actions">
    <div class="btn btn-accent">有用</div>
    <div class="btn">关闭</div>
</div>
</body></html>'''


def create_panel(data: dict) -> NSPanel:
    """Create a floating NSPanel with WKWebView content."""
    screen = NSScreen.mainScreen().frame()
    screen_w = screen.size.width
    screen_h = screen.size.height

    # Get active window position
    win_info = get_active_window_info()
    width = 380
    height = 320

    # Position to the right of active window
    win_x = win_info.get("x", 0)
    win_w = win_info.get("w", 800)
    x = min(win_x + win_w + 12, screen_w - width - 10)
    # macOS coordinates: y=0 is bottom, so convert
    win_y = win_info.get("y", 100)
    y = screen_h - win_y - height

    # Clamp
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

    # WebView
    config = WKWebViewConfiguration.alloc().init()
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
    """Read JSON commands from stdin in a background thread."""
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


# ── Main: AppKit Event Loop ──────────────────────────────

def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(0)  # Regular app so windows are visible

    panels = []  # (NSPanel, created_at, timeout)

    # ObjC timer callback class
    class Ticker(NSObject):
        def init(self):
            self = objc.super(Ticker, self).init()
            return self

        @objc.typedSelector(b"v@:@")
        def tick_(self, timer):
            nonlocal panels

            # Process commands
            with cmd_lock:
                cmds = list(cmd_buffer)
                cmd_buffer.clear()

            for cmd in cmds:
                action = cmd.get("action")

                if action == "show":
                    try:
                        p = create_panel(cmd)
                        timeout = cmd.get("timeout", 30)
                        panels.append((p, time.time(), timeout))
                    except Exception as e:
                        sys.stderr.write(f"Panel error: {e}\n")
                        sys.stderr.flush()

                elif action == "close_all":
                    for (p, _, _) in panels:
                        p.close()
                    panels.clear()

                elif action == "quit":
                    for (p, _, _) in panels:
                        p.close()
                    panels.clear()
                    NSApp.terminate_(None)
                    return

            # Auto-dismiss expired
            now = time.time()
            alive = []
            for (p, created, timeout) in panels:
                if now - created > timeout:
                    p.close()
                else:
                    alive.append((p, created, timeout))
            panels = alive

    ticker = Ticker.alloc().init()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.3, ticker, b"tick:", None, True
    )

    # Start stdin reader thread
    t = threading.Thread(target=stdin_reader, daemon=True)
    t.start()

    # Run AppKit loop
    app.run()


if __name__ == "__main__":
    main()
