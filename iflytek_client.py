"""
讯飞实时语音转写大模型 WebSocket 客户端。

基于星火大模型的实时语音转写，支持中英 + 202 种方言免切识别，无时长限制。
API 文档: https://www.xfyun.cn/doc/asr/rtasr_llm/API.html

需要的环境变量:
    IFLYTEK_APP_ID        — 开放平台应用 ID
    IFLYTEK_API_KEY       — accessKeyId
    IFLYTEK_API_SECRET    — accessKeySecret (签名密钥)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import queue
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Callable
from urllib.parse import quote, urlencode

import numpy as np
import websocket

logger = logging.getLogger(__name__)

RTASR_LLM_URL = "wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1"


class IflytekStreamingASR:
    """讯飞实时语音转写大模型客户端。

    持续从音频队列读取数据，通过 WebSocket 发送给讯飞大模型转写服务，
    回调返回识别文字。无单次会话时长限制。
    """

    def __init__(self, app_id: str, api_key: str, api_secret: str):
        self.app_id = app_id
        self.api_key = api_key       # accessKeyId
        self.api_secret = api_secret  # accessKeySecret (HMAC 签名密钥)
        self._on_result: Callable[[str, bool], None] | None = None

    def on_result(self, callback: Callable[[str, bool], None]):
        """
        注册结果回调。
        callback(text, is_final):
            text     — 当前段的识别文字
            is_final — type="0" 表示该段最终确定结果
        """
        self._on_result = callback

    # ------------------------------------------------------------------
    # Public: run loop (blocking, call from a background thread)
    # ------------------------------------------------------------------

    def run(self, audio_queue: queue.Queue[np.ndarray]):
        """持续运行：音频 → 讯飞大模型转写 → 回调。连接断开自动重连。"""
        while True:
            try:
                self._run_one_session(audio_queue)
            except Exception as e:
                logger.error("讯飞转写会话异常: %s — 1 秒后重连", e)
                time.sleep(1)

    # ------------------------------------------------------------------
    # Internal: one WebSocket session
    # ------------------------------------------------------------------

    def _run_one_session(self, audio_queue: queue.Queue[np.ndarray]):
        url = self._build_auth_url()
        logger.debug("连接: %s", url[:120] + "...")

        ws = websocket.WebSocketApp(
            url,
            on_open=lambda w: self._on_open(w, audio_queue),
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        ws.run_forever()

    # ------------------------------------------------------------------
    # WebSocket callbacks
    # ------------------------------------------------------------------

    def _on_open(self, ws: websocket.WebSocketApp, audio_queue: queue.Queue):
        logger.info("讯飞转写大模型 WebSocket 已连接")
        threading.Thread(
            target=self._send_loop, args=(ws, audio_queue), daemon=True
        ).start()

    def _on_message(self, ws: websocket.WebSocketApp, message: str):
        try:
            resp = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("无法解析消息: %s", message[:200])
            return

        # 握手阶段: {"action": "started", "code": "0", ...}
        action = resp.get("action")
        if action == "started":
            logger.info("转写会话已启动 (sid=%s)", resp.get("sid"))
            return
        if action == "error":
            logger.error("转写错误 %s: %s", resp.get("code"), resp.get("desc"))
            ws.close()
            return

        # 转写结果: {"msg_type": "result", "res_type": "asr", "data": {...}}
        msg_type = resp.get("msg_type")
        res_type = resp.get("res_type")

        if msg_type == "result" and res_type == "asr":
            self._handle_asr_result(resp.get("data", {}))
        elif msg_type == "result" and res_type == "frc":
            # 功能异常通知
            data = resp.get("data", {})
            if not data.get("normal", True):
                logger.warning("转写功能异常: %s", data.get("desc"))

    def _handle_asr_result(self, data: dict):
        """解析 ASR 结果并触发回调。"""
        # data 可能是 dict 或 JSON string
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return

        st = data.get("cn", {}).get("st", {})
        result_type = str(st.get("type", "1"))  # "0"=确定, "1"=中间
        text = self._extract_text(st)
        is_final = result_type == "0"

        if text and self._on_result:
            self._on_result(text, is_final)

    def _on_error(self, _ws: websocket.WebSocketApp, error: Exception):
        logger.error("WebSocket 错误: %s", error)

    def _on_close(self, _ws: websocket.WebSocketApp, code: Any, _msg: Any):
        logger.info("WebSocket 已断开 (code=%s)", code)

    # ------------------------------------------------------------------
    # Audio sender thread
    # ------------------------------------------------------------------

    def _send_loop(self, ws: websocket.WebSocketApp, audio_queue: queue.Queue):
        """持续从队列读取音频块，转为 PCM int16 后以二进制发送。

        RTASR 大模型直接接收二进制 PCM 数据。
        queue.get() 以录音实时速率自然阻塞，无需额外 sleep。
        当队列为空时发送静音帧保持连接。
        """
        # 640 samples * 2 bytes = 1280 bytes silence frame
        silence_pcm = b"\x00" * 1280

        while ws.sock and ws.sock.connected:
            try:
                chunk: np.ndarray = audio_queue.get(timeout=1.0)
            except queue.Empty:
                # Send silence to keep WebSocket alive
                try:
                    ws.send(silence_pcm, opcode=websocket.ABNF.OPCODE_BINARY)
                except Exception:
                    return
                continue

            pcm = (
                (chunk.flatten() * 32768)
                .clip(-32768, 32767)
                .astype(np.int16)
                .tobytes()
            )

            try:
                ws.send(pcm, opcode=websocket.ABNF.OPCODE_BINARY)
            except Exception:
                return

    # ------------------------------------------------------------------
    # Auth URL — 签名机制
    # ------------------------------------------------------------------

    def _build_auth_url(self) -> str:
        """生成带鉴权参数的 WebSocket URL。

        签名流程:
        1. 收集所有参数 (不含 signature)，按 key 升序排列
        2. URL-encode 每个 key/value，拼接为 key=value&key=value
        3. HmacSHA1(baseString, accessKeySecret) → base64
        """
        # UTC 时间格式: 2025-09-04T15:38:07+0800
        tz_cn = timezone(timedelta(hours=8))
        utc_str = datetime.now(tz_cn).strftime("%Y-%m-%dT%H:%M:%S%z")

        params = {
            "appId": self.app_id,
            "accessKeyId": self.api_key,
            "uuid": uuid.uuid4().hex,
            "utc": utc_str,
            "lang": "autodialect",
            "audio_encode": "pcm_s16le",
            "samplerate": "16000",
        }

        # 按 key 升序排序，URL-encode key 和 value，拼接
        sorted_keys = sorted(params.keys())
        base_string = "&".join(
            f"{quote(k, safe='')}={quote(params[k], safe='')}"
            for k in sorted_keys
        )

        # HmacSHA1(baseString, accessKeySecret) → base64
        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                base_string.encode(),
                hashlib.sha1,
            ).digest()
        ).decode()

        params["signature"] = signature
        query = urlencode(params)
        return f"{RTASR_LLM_URL}?{query}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(st: dict) -> str:
        """从转写结果 st 结构中提取纯文字。

        结构: st.rt[].ws[].cw[].w
        """
        parts: list[str] = []
        for rt in st.get("rt", []):
            for ws_item in rt.get("ws", []):
                for cw in ws_item.get("cw", []):
                    parts.append(cw.get("w", ""))
        return "".join(parts)
