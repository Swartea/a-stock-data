#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Task 5.3 — 北向资金接口实际返回结构验证脚本

目的: 在写 _classify_north_scope() 之前, 跑一次 V3 全链路,
      打印 macro 字典的实际 keys + hsgt/north 子结构, 用于校准 helper 函数字段名。

用法: venv/bin/python -W ignore scripts/verify_north_scope.py [code] [name]
默认: 600693 东百集团
输出: /tmp/north_scope.json (含 macro 完整 dump + keys 列表)
"""
import sys
import json
import os

# 绝对 import: ROOT 加入 sys.path (与 plan 一致, 不用 `sys.path.insert(0, "analysis/")` 旧风格)
_ROOT = "/Users/swarteachou/Desktop/大A数据"
sys.path.insert(0, _ROOT)

from analysis.quant_analyzer_v3 import analyze_single_v3  # noqa: E402


def run_v3(code: str, name: str) -> dict:  # 兼容 plan 习惯
    return analyze_single_v3(code, name)

# 兼容 plan 原脚本中的 "north" / "north_hsgt" 两个 key 探测
def main():
    code = sys.argv[1] if len(sys.argv) >= 2 else "600693"
    name = sys.argv[2] if len(sys.argv) >= 3 else "东百集团"
    print(f"[verify_north_scope] 跑 {code} {name} → 等 V3 全链路跑完 (约 60-90s)...", flush=True)
    res = run_v3(code, name)
    macro = res.get("macro", {}) if isinstance(res, dict) else {}
    hsgt = macro.get("hsgt", {}) if isinstance(macro, dict) else {}

    out = {
        "code": code, "name": name,
        "macro_keys_top": list(macro.keys()) if isinstance(macro, dict) else None,
        "macro.hsgt": hsgt,
        "macro.north (备选 key)": macro.get("north"),
        "macro.north_hsgt (备选 key)": macro.get("north_hsgt"),
        "macro.is_dict": isinstance(macro, dict),
        "macro.hsgt.is_dict": isinstance(hsgt, dict),
        "hsgt_keys": list(hsgt.keys()) if isinstance(hsgt, dict) else None,
        "hsgt_data_points": hsgt.get("data_points") if isinstance(hsgt, dict) else None,
    }

    print("=" * 72)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("=" * 72)

    # 落盘: 后续 helper 函数设计依据
    out_path = "/tmp/north_scope.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[verify_north_scope] 落盘 {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
