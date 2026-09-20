#!/usr/bin/env bash
# V3 专用稳定入口：避免系统/Anaconda Python 抢占项目虚拟环境。
# 用法:
#   bash scripts/run_v3.sh --check
#   bash scripts/run_v3.sh 600693 东百集团
# 可选:
#   DA_PYTHON=/path/to/python bash scripts/run_v3.sh 600693 东百集团
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

choose_python() {
  if [ -n "${DA_PYTHON:-}" ]; then
    if [ ! -x "$DA_PYTHON" ]; then
      echo "[runtime] DA_PYTHON 不可执行: $DA_PYTHON" >&2
      return 2
    fi
    printf '%s\n' "$DA_PYTHON"
    return 0
  fi

  local candidate
  for candidate in "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/venv/bin/python"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi

  echo "[runtime] 未找到 Python。请先创建 .venv/venv，或设置 DA_PYTHON。" >&2
  return 2
}

PY="$(choose_python)"

if ! "$PY" -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec("baostock") else 1)'; then
  echo "[runtime] 当前解释器缺少 baostock: $PY" >&2
  echo "[runtime] 请使用项目虚拟环境执行 pip install -e ." >&2
  exit 3
fi

PY_REAL="$("$PY" -c 'import sys; print(sys.executable)')"
echo "[runtime] python=$PY_REAL" >&2

if [ "${1:-}" = "--check" ]; then
  exit 0
fi

if [ "$#" -lt 1 ]; then
  echo "用法: bash scripts/run_v3.sh <code> [name]" >&2
  echo "检查: bash scripts/run_v3.sh --check" >&2
  exit 2
fi

cd "$ROOT_DIR"
exec "$PY" -W ignore -m analysis.quant_analyzer_v3 "$@"
