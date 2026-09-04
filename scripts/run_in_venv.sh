#!/usr/bin/env bash
# 在 skill 自带 venv 中运行 Python 代码的小工具
# 用法: ./run_in_venv.sh -c "import mootdx; print(mootdx.__version__)"
#      ./run_in_venv.sh my_script.py
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# venv 位于仓库根目录（不在 scripts/ 下），所以向上跳一级
PY="$SCRIPT_DIR/../venv/bin/python"
# 抑制 Python 3.12 的弃用警告 stderr，避免某些终端适配器阻塞读 stderr 卡死
PY_FLAGS="-W ignore"

# 自动加载 .env (如果存在)
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$SCRIPT_DIR/.env"
  set +a
fi

if [ "$1" = "-c" ]; then
  shift
  exec "$PY" $PY_FLAGS -c "$*"
else
  exec "$PY" $PY_FLAGS "$@"
fi
