#!/usr/bin/env bash
# Phase 2 Test Launcher
# Starts the test controller (which manages WS + alignment + quality servers)
# and the frontend HTTP server.
#
# Usage: ./start-test.sh
# Stop:  ./start-test.sh stop

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/tts-venv/bin/python3"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

cleanup() {
  echo -e "\n${YELLOW}Shutting down...${NC}"
  [ -n "$CTRL_PID" ] && kill "$CTRL_PID" 2>/dev/null && echo "  Stopped controller (PID $CTRL_PID)"
  [ -n "$HTTP_PID" ] && kill "$HTTP_PID" 2>/dev/null && echo "  Stopped HTTP server (PID $HTTP_PID)"
  echo -e "${GREEN}Done.${NC}"
}

if [ "$1" = "stop" ]; then
  echo "Stopping test servers..."
  pkill -f "test-controller.py" 2>/dev/null || true
  pkill -f "web-vox-server" 2>/dev/null || true
  pkill -f "alignment_server.py" 2>/dev/null || true
  pkill -f "quality_server.py" 2>/dev/null || true
  pkill -f "chatterbox_server.py" 2>/dev/null || true
  pkill -f "kokoro_server.py" 2>/dev/null || true
  pkill -f "coqui_server.py" 2>/dev/null || true
  pkill -f "coqui_xtts_server.py" 2>/dev/null || true
  pkill -f "qwen_tts_server.py" 2>/dev/null || true
  pkill -f "qwen_tts_clone_server.py" 2>/dev/null || true
  lsof -ti :8098 :8099 :21740 :21741 :21742 :21743 :21744 :21745 :21746 :21747 :21748 2>/dev/null | xargs kill 2>/dev/null || true
  echo "Stopped."
  exit 0
fi

trap cleanup EXIT INT TERM

echo -e "${GREEN}=== Phase 2 Quality Analysis Test Suite ===${NC}"
echo ""

# 1) Start controller (manages WS + alignment + quality servers)
echo -e "${YELLOW}[1/2] Starting test controller (port 8098)...${NC}"
"$VENV" "$SCRIPT_DIR/test-controller.py" &
CTRL_PID=$!
sleep 1
if kill -0 "$CTRL_PID" 2>/dev/null; then
  echo -e "${GREEN}  Controller running (PID $CTRL_PID)${NC}"
else
  echo -e "${RED}  Controller failed to start${NC}"
  exit 1
fi

# 2) Start frontend HTTP server
echo -e "${YELLOW}[2/2] Starting test frontend (port 8099)...${NC}"
"$VENV" -m http.server 8099 --directory "$SCRIPT_DIR" &>/dev/null &
HTTP_PID=$!
sleep 1

echo ""
echo -e "${GREEN}=== Ready ===${NC}"
echo ""
echo -e "  ${CYAN}Test frontend:${NC}  ${GREEN}http://localhost:8099${NC}"
echo -e "  ${CYAN}Controller API:${NC} http://localhost:8098"
echo ""
echo -e "  Use the ${GREEN}Server Control${NC} panel in the frontend to start/stop"
echo -e "  the WebSocket server, alignment server, and quality server."
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop everything.${NC}"
echo ""

# Open browser
if command -v open &>/dev/null; then
  open "http://localhost:8099"
elif command -v xdg-open &>/dev/null; then
  xdg-open "http://localhost:8099"
fi

wait
