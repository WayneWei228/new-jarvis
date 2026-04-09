"""
WebSocket Bridge — 将 AI Thinking 数据广播给前端。

使用 aiohttp 提供 WebSocket 端点 /ws，Reactor 调用 broadcast() 时
向所有连接的 web 客户端推送 JSON 数据。

Usage:
    bridge = ThinkingBridge(port=8765)
    await bridge.start()
    await bridge.broadcast([{"text": "...", "type": "reason"}])
"""

from __future__ import annotations

import json
import logging

from aiohttp import web

logger = logging.getLogger(__name__)


class ThinkingBridge:
    """WebSocket server that broadcasts AI thinking entries to web clients."""

    def __init__(self, port: int = 8765):
        self.port = port
        self._clients: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/ws", self._ws_handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()
        logger.info(f"ThinkingBridge started on ws://0.0.0.0:{self.port}/ws")

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        logger.info(f"Web client connected ({len(self._clients)} total)")
        try:
            async for _ in ws:
                pass  # We only send, ignore incoming
        finally:
            self._clients.discard(ws)
            logger.info(f"Web client disconnected ({len(self._clients)} total)")
        return ws

    async def broadcast(self, entries: list[dict]) -> None:
        if not self._clients or not entries:
            return
        msg = json.dumps({"type": "thinking", "entries": entries}, ensure_ascii=False)
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send_str(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def broadcast_camera(self, image_base64: str) -> None:
        """推送摄像头帧（base64 图片）给网页"""
        if not self._clients or not image_base64:
            return
        msg = json.dumps({"type": "camera", "data": image_base64}, ensure_ascii=False)
        dead = set()
        logger.debug(f"📹 Broadcasting camera frame to {len(self._clients)} clients ({len(msg)} bytes)")
        for ws in list(self._clients):
            try:
                await ws.send_str(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def broadcast_state(self, state: str) -> None:
        """推送 AI 状态给网页: 'observe' 或 'execute'"""
        if not self._clients or state not in ["observe", "execute"]:
            return
        msg = json.dumps({"type": "ai_state", "state": state}, ensure_ascii=False)
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send_str(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def stop(self) -> None:
        # Close all client connections
        for ws in list(self._clients):
            await ws.close()
        self._clients.clear()
        if self._runner:
            await self._runner.cleanup()
            logger.info("ThinkingBridge stopped")
