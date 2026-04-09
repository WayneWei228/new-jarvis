#!/usr/bin/env bash
# ──────────────────────────────────────────────
#  Jarvis + Web 一键启动脚本
#
#  用法:
#    ./start.sh                 # 默认：Jarvis 无摄像头，Web UI 独占
#    ./start.sh [其他参数]      # 传递参数给 main.py
# ──────────────────────────────────────────────
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
WEB="$DIR/test_mcp"

# ── 颜色 ──
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── 清理函数：Ctrl+C 时杀掉所有子进程 ──
cleanup() {
  echo ""
  echo -e "${YELLOW}[start.sh] Shutting down...${NC}"
  # kill 后端和前端
  kill $JARVIS_PID $VITE_PID 2>/dev/null || true
  wait $JARVIS_PID $VITE_PID 2>/dev/null || true
  echo -e "${GREEN}[start.sh] All stopped.${NC}"
  exit 0
}
trap cleanup SIGINT SIGTERM

# ── 1. 检查 venv ──
if [ ! -f "$VENV/bin/python3" ]; then
  echo -e "${CYAN}[start.sh] Creating venv...${NC}"
  python3 -m venv "$VENV"
fi

# 检查依赖
if ! "$VENV/bin/python3" -c "import anthropic" 2>/dev/null; then
  echo -e "${CYAN}[start.sh] Installing Python dependencies...${NC}"
  "$VENV/bin/pip" install -r "$DIR/requirements.txt" -q
fi

# ── 2. 检查 node_modules ──
if [ ! -d "$WEB/node_modules" ]; then
  echo -e "${CYAN}[start.sh] Installing web dependencies...${NC}"
  (cd "$WEB" && npm install)
fi

echo -e "${CYAN}[start.sh] Starting system...${NC}"

# ── 3. 启动 Jarvis 后端 ──
echo -e "${GREEN}[start.sh] Starting Jarvis backend...${NC}"
"$VENV/bin/python3" "$DIR/main.py" "$@" &
JARVIS_PID=$!

# 等 WebSocket 桥启动（端口 8765）
echo -e "${CYAN}[start.sh] Waiting for WebSocket bridge (port 8765)...${NC}"
for i in $(seq 1 15); do
  if lsof -i :8765 >/dev/null 2>&1; then
    echo -e "${GREEN}[start.sh] WebSocket bridge ready!${NC}"
    break
  fi
  sleep 1
done

# ── 4. 启动 Web 前端 ──
echo -e "${GREEN}[start.sh] Starting Web frontend...${NC}"
(cd "$WEB" && npx vite --host) &
VITE_PID=$!

# 等 Vite 启动
sleep 2

echo ""
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  🎥 Jarvis + Web 已启动${NC}"
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Web UI: http://localhost:5173${NC}"
echo -e "${GREEN}  AI Thinking: ws://localhost:8765/ws${NC}"
echo ""
echo -e "${CYAN}📹 摄像头配置：${NC}"
echo -e "${CYAN}  • Jarvis AI 分析: 本地电脑摄像头 (索引 0)${NC}"
echo -e "${CYAN}  • Web UI 显示:    Insta360 摄像头 (索引 1)${NC}"
echo ""
echo -e "${CYAN}✅ Web 左下角摄像头框会自动显示 Insta360 实时视频${NC}"
echo ""
echo -e "${GREEN}  按 Ctrl+C 停止所有服务${NC}"
echo -e "${GREEN}══════════════════════════════════════════════${NC}"
echo ""

# ── 等待子进程 ──
wait
