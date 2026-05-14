#!/bin/bash
# 产品图批量背景替换 - 启动脚本
# 使用方法: ./start.sh

cd "$(dirname "$0")"

# 检查虚拟环境
if [ -d ".venv" ]; then
    PYTHON=".venv/bin/python3"
else
    PYTHON="python3"
fi

# 检查 Flask 是否安装
if ! $PYTHON -c "import flask" 2>/dev/null; then
    echo "❌ Flask 未安装，正在安装依赖..."
    $PYTHON -m pip install -r requirements.txt
fi

echo "🚀 启动服务器..."
echo "   Python: $($PYTHON --version 2>&1)"
echo "   地址: http://127.0.0.1:5010"
echo ""

$PYTHON server.py
