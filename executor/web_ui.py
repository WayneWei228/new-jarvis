"""
Web UI — 实时浮动面板，展示 AI 的思考和执行过程。

Serves:
- GET /          → overlay HTML page
- GET /events    → SSE stream (real-time updates)

Auto-opens in browser on start.
"""

from __future__ import annotations

import asyncio
import json
import logging
import webbrowser

from aiohttp import web

from executor.notifier import Notifier

logger = logging.getLogger(__name__)

OVERLAY_HTML = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brainiest Mind</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', 'Helvetica Neue', sans-serif;
    background: #0a0a0f;
    color: #e0e0e0;
    min-height: 100vh;
    overflow-x: hidden;
  }

  .container {
    max-width: 520px;
    margin: 0 auto;
    padding: 16px;
  }

  /* Header */
  .header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 0;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 16px;
  }
  .pulse-dot {
    width: 10px; height: 10px;
    background: #00ff88;
    border-radius: 50%;
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(0,255,136,0.4); }
    50% { opacity: 0.7; box-shadow: 0 0 0 8px rgba(0,255,136,0); }
  }
  .header h1 {
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.5px;
  }
  .header .status {
    margin-left: auto;
    font-size: 11px;
    color: #666;
  }

  /* Current thinking card */
  .card {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
    animation: fadeIn 0.3s ease;
  }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .card-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #555;
    margin-bottom: 8px;
  }

  .thinking-card {
    border-color: rgba(0,255,136,0.15);
    background: rgba(0,255,136,0.03);
  }
  .thinking-card .card-label { color: #00ff88; }

  .executing-card {
    border-color: rgba(100,149,237,0.2);
    background: rgba(100,149,237,0.03);
  }
  .executing-card .card-label { color: #6495ed; }

  .result-card {
    border-color: rgba(255,215,0,0.15);
    background: rgba(255,215,0,0.03);
  }
  .result-card .card-label { color: #ffd700; }

  .card h3 {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 6px;
    line-height: 1.4;
  }

  .card p, .card .body {
    font-size: 13px;
    line-height: 1.6;
    color: #aaa;
  }

  .card .body {
    white-space: pre-wrap;
    word-break: break-word;
  }

  .card .meta {
    display: flex;
    gap: 12px;
    margin-top: 10px;
    font-size: 11px;
    color: #555;
  }
  .card .meta .tag {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 600;
  }
  .tag-high { background: rgba(255,80,80,0.15); color: #ff5050; }
  .tag-medium { background: rgba(255,180,50,0.15); color: #ffb432; }
  .tag-low { background: rgba(100,200,100,0.15); color: #64c864; }

  /* Timeline */
  .timeline {
    margin-top: 20px;
    border-top: 1px solid rgba(255,255,255,0.06);
    padding-top: 12px;
  }
  .timeline-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #444;
    margin-bottom: 10px;
  }
  .timeline-item {
    display: flex;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid rgba(255,255,255,0.03);
    font-size: 12px;
    animation: fadeIn 0.3s ease;
  }
  .timeline-item .time {
    color: #444;
    white-space: nowrap;
    min-width: 50px;
  }
  .timeline-item .action {
    color: #888;
    flex: 1;
  }
  .timeline-item .action strong {
    color: #ccc;
    font-weight: 500;
  }

  /* Typing animation */
  .typing::after {
    content: '|';
    animation: blink 1s step-end infinite;
  }
  @keyframes blink {
    50% { opacity: 0; }
  }

  /* Empty state */
  .empty {
    text-align: center;
    padding: 60px 20px;
    color: #333;
  }
  .empty .icon { font-size: 32px; margin-bottom: 12px; }
  .empty p { font-size: 13px; }

  /* Scrollable result body */
  .result-body {
    max-height: 300px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: #333 transparent;
  }
  .result-body::-webkit-scrollbar { width: 4px; }
  .result-body::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }

  /* Markdown-like formatting in results */
  .result-body h1, .result-body h2, .result-body h3 {
    color: #ddd;
    margin: 12px 0 6px 0;
  }
  .result-body h1 { font-size: 16px; }
  .result-body h2 { font-size: 14px; }
  .result-body h3 { font-size: 13px; }
  .result-body ul, .result-body ol {
    padding-left: 20px;
    margin: 6px 0;
  }
  .result-body li { margin: 3px 0; }
  .result-body code {
    background: rgba(255,255,255,0.08);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 12px;
  }
  .result-body pre {
    background: rgba(255,255,255,0.05);
    padding: 10px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 12px;
    margin: 8px 0;
  }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="pulse-dot" id="statusDot"></div>
    <h1>Brainiest Mind</h1>
    <span class="status" id="connStatus">connecting...</span>
  </div>

  <div id="currentSection">
    <div class="empty">
      <div class="icon">&#129504;</div>
      <p>AI is observing and thinking...</p>
    </div>
  </div>

  <div class="timeline" id="timelineSection" style="display:none">
    <div class="timeline-label">Timeline</div>
    <div id="timeline"></div>
  </div>
</div>

<script>
const currentSection = document.getElementById('currentSection');
const timelineSection = document.getElementById('timelineSection');
const timeline = document.getElementById('timeline');
const connStatus = document.getElementById('connStatus');
const statusDot = document.getElementById('statusDot');

let eventSource = null;
const timelineItems = [];

function connect() {
  eventSource = new EventSource('/events');

  eventSource.onopen = () => {
    connStatus.textContent = 'live';
    statusDot.style.background = '#00ff88';
  };

  eventSource.onerror = () => {
    connStatus.textContent = 'reconnecting...';
    statusDot.style.background = '#ff5050';
    setTimeout(() => {
      eventSource.close();
      connect();
    }, 3000);
  };

  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      handleEvent(data);
    } catch (err) {
      console.error('Parse error:', err);
    }
  };
}

function handleEvent(ev) {
  switch (ev.type) {
    case 'brain_thinking':
      showThinking(ev);
      addTimeline(ev.timestamp, 'thinking', ev.action || 'Thinking...');
      break;
    case 'brain_decision':
      showDecision(ev);
      addTimeline(ev.timestamp, 'decided', ev.action || '?');
      break;
    case 'executing':
      showExecuting(ev);
      addTimeline(ev.timestamp, 'executing', ev.action || '?');
      break;
    case 'execution_complete':
      showResult(ev);
      addTimeline(ev.timestamp, 'done', ev.action || '?');
      break;
    case 'execution_error':
      showError(ev);
      addTimeline(ev.timestamp, 'error', ev.message || '?');
      break;
    case 'status_update':
      showStatus(ev);
      addTimeline(ev.timestamp, 'status', ev.summary || '?');
      break;
  }
}

function showThinking(ev) {
  currentSection.innerHTML = `
    <div class="card thinking-card">
      <div class="card-label">AI is thinking</div>
      <h3 class="typing">${esc(ev.action || 'Analyzing your current state...')}</h3>
      <p>${esc(ev.reason || '')}</p>
    </div>
  `;
}

function showDecision(ev) {
  const priorityClass = 'tag-' + (ev.priority || 'medium');
  currentSection.innerHTML = `
    <div class="card thinking-card">
      <div class="card-label">AI decided</div>
      <h3>${esc(ev.action || '?')}</h3>
      <p>${esc(ev.reason || '')}</p>
      <div class="meta">
        <span class="tag ${priorityClass}">${esc(ev.priority || 'medium')}</span>
        <span>confidence: ${ev.confidence || '?'}</span>
      </div>
    </div>
  `;
}

function showExecuting(ev) {
  currentSection.innerHTML = `
    <div class="card executing-card">
      <div class="card-label">Executing</div>
      <h3 class="typing">${esc(ev.action || 'Working...')}</h3>
      <p>${esc(ev.plan || '')}</p>
    </div>
  `;
}

function showResult(ev) {
  const body = ev.result || '';
  const rendered = renderMarkdown(body);
  currentSection.innerHTML = `
    <div class="card result-card">
      <div class="card-label">Result</div>
      <h3>${esc(ev.action || 'Done')}</h3>
      <div class="result-body">${rendered}</div>
      <div class="meta">
        <span>${esc(ev.title || '')}</span>
      </div>
    </div>
  `;
}

function showError(ev) {
  currentSection.innerHTML = `
    <div class="card" style="border-color: rgba(255,50,50,0.2); background: rgba(255,50,50,0.03);">
      <div class="card-label" style="color: #ff5050;">Error</div>
      <p>${esc(ev.message || 'Unknown error')}</p>
    </div>
  `;
}

function showStatus(ev) {
  currentSection.innerHTML = `
    <div class="card">
      <div class="card-label">Status Update</div>
      <p>${esc(ev.summary || '')}</p>
    </div>
  `;
}

function addTimeline(ts, type, text) {
  timelineSection.style.display = '';
  const time = new Date(ts * 1000).toLocaleTimeString('zh', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
  const item = {time, type, text};
  timelineItems.unshift(item);
  if (timelineItems.length > 20) timelineItems.pop();
  renderTimeline();
}

function renderTimeline() {
  timeline.innerHTML = timelineItems.map(i =>
    `<div class="timeline-item">
      <span class="time">${esc(i.time)}</span>
      <span class="action"><strong>${esc(i.type)}</strong> ${esc(i.text.substring(0, 80))}</span>
    </div>`
  ).join('');
}

function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}

function renderMarkdown(text) {
  if (!text) return '';
  let html = esc(text);
  // Headers
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // Bold
  html = html.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Lists
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\\/li>)/gs, '<ul>$1</ul>');
  // Line breaks
  html = html.replace(/\\n/g, '<br>');
  return html;
}

connect();
</script>
</body>
</html>
"""


class WebUI:
    """Async web server for the real-time overlay panel."""

    def __init__(self, notifier: Notifier, host: str = "127.0.0.1", port: int = 7888):
        self.notifier = notifier
        self.host = host
        self.port = port
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/events", self._handle_sse)
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start the web server and open browser."""
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        url = f"http://{self.host}:{self.port}"
        logger.info(f"Web UI started at {url}")
        webbrowser.open(url)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=OVERLAY_HTML, content_type="text/html")

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """Server-Sent Events endpoint."""
        resp = web.StreamResponse()
        resp.content_type = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        await resp.prepare(request)

        q = self.notifier.add_sse_client()
        try:
            while True:
                event = await q.get()
                data = json.dumps(event, ensure_ascii=False)
                await resp.write(f"data: {data}\n\n".encode())
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self.notifier.remove_sse_client(q)
        return resp
