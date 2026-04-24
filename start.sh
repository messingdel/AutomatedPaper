#!/bin/bash

# 一键启动前后端脚本（含 MySQL 服务）
# 使用方法: ./start.sh

set -e  # 遇到错误立即退出

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==========================================="
echo "  试卷图片分析与AI阅卷实验平台 启动脚本"
echo "==========================================="

# 0. 启动 MySQL 服务
echo "正在检查 MySQL 服务..."
if ! pgrep -x "mysqld" > /dev/null; then
    echo "MySQL 未运行，正在启动..."
    sudo service mysql start
    echo "MySQL 已启动。"
else
    echo "MySQL 服务已在运行。"
fi

# 1. 检查后端虚拟环境
if [ ! -d "backend/venv" ]; then
    echo "后端虚拟环境不存在，正在创建..."
    cd backend
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cd ..
    echo "后端环境创建完成。"
else
    echo "后端虚拟环境已存在。"
fi

# 2. 检查前端依赖
if [ ! -d "frontend/node_modules" ]; then
    echo "前端依赖未安装，正在安装..."
    cd frontend
    npm install
    cd ..
    echo "前端依赖安装完成。"
else
    echo "前端依赖已安装。"
fi

# 3. 启动后端服务
echo "正在启动后端服务 (FastAPI) ..."
cd backend
# 直接使用虚拟环境中的 uvicorn，避免激活子 shell 问题
nohup ./venv/bin/uvicorn app_main:app --host 0.0.0.0 --port 8001 > ../backend.log 2>&1 &
BACKEND_PID=$!
cd ..
echo "后端服务已启动，PID: $BACKEND_PID，日志: backend.log"

# 4. 启动前端服务
echo "正在启动前端服务 (Vue) ..."
cd frontend
nohup npm run dev > ../frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..
echo "前端服务已启动，PID: $FRONTEND_PID，日志: frontend.log"

echo ""
echo "==========================================="
echo "  服务启动完成！"
echo "  MySQL 已启动"
echo "  后端地址: http://localhost:8001"
echo "  前端地址: http://localhost:5173"
echo "  后端日志: tail -f backend.log"
echo "  前端日志: tail -f frontend.log"
echo "  停止服务: kill $BACKEND_PID $FRONTEND_PID; sudo service mysql stop"
echo "==========================================="
