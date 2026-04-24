#!/bin/bash
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID="$PROJECT_ROOT/backend.pid"
FRONTEND_PID="$PROJECT_ROOT/frontend.pid"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# 停止后端
if [ -f "$BACKEND_PID" ]; then
    PID=$(cat "$BACKEND_PID")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo -e "${GREEN}后端进程 $PID 已停止${NC}"
    else
        echo -e "${RED}后端进程 $PID 不存在${NC}"
    fi
    rm -f "$BACKEND_PID"
else
    echo -e "${RED}后端 PID 文件不存在，可能未运行${NC}"
fi

# 停止前端
if [ -f "$FRONTEND_PID" ]; then
    PID=$(cat "$FRONTEND_PID")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo -e "${GREEN}前端进程 $PID 已停止${NC}"
    else
        echo -e "${RED}前端进程 $PID 不存在${NC}"
    fi
    rm -f "$FRONTEND_PID"
else
    echo -e "${RED}前端 PID 文件不存在，可能未运行${NC}"
fi

echo "服务已停止"
