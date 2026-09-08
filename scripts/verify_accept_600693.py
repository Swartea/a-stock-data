#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""600693 东百集团首票验收辅助检查（纯 stdlib，不碰 venv）"""
import json, re, zipfile
from pathlib import Path

BASE = Path("/Users/swarteachou/Desktop/大A数据")
D = BASE / "reports" / "600693_东百集团" / "2026-09-07"

def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

r = load(D / "result_v3.json")
print("=== result_v3.json 顶层 keys ===")
print(list(r.keys()))
for k, v in r.items():
    if not isinstance(v, (dict, list)):
        print(f"  {k} = {str(v)[:120]}")

HITS = 0
def walk(o, path=""):
    global HITS
    if HITS > 200 or "close_series" in path or "kline" in path.lower():
        return
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, f"{path}[{i}]")
    else:
        s = str(o)
        lp = path.lower()
        if any(t in lp for t in ["score", "verdict", "signal", "recommend",
                                 "support", "pressure", "stop", "last_bar",
                                 "fund", "flow", "主力", "资金", "error",
                                 "bull", "bear", "price", "前收",
                                 "as_of", "data_date", "trade_date"]):
            print(f"{path} = {s[:150]}")
            HITS += 1

print("=== 关键字段扫描 ===")
walk(r)

def cnt(text, kws):
    for kw in kws:
        print(f"  '{kw}' 出现 {text.count(kw)} 次")

md = (D / "600693-东百集团-1139.md").read_text(encoding="utf-8")
print("\n=== MD 硬要求检查 ===")
cnt(md, ["多", "空", "评分", "支撑", "压力", "止损",
         "11.26", "12.77", "10.80", "52", "11.61",
         "减仓", "不进场", "风险警报", "操作检查清单",
         "2026-09-04", "2026-09-07"])
print("\n=== MD 口播数字复查（应为 0）===")
cnt(md, ["2876", "5666", "2.07", "5.50", "7.30", "5.10",
         "6.47", "30 分", "30分"])

html = (D / "600693-东百集团-v3-20260907-1139.html").read_text(encoding="utf-8")
print("\n=== HTML 检查 ===")
print(f"  <svg 数量: {len(re.findall(r'<svg', html))}")
cnt(html, ["K线", "筹码", "PE", "雷达", "支撑", "压力", "止损",
           "11.26", "12.77", "10.80", "52"])
print("  外部 CDN 引用:", re.findall(r'(https?://[^"\']*(?:cdn|jsdelivr|unpkg|googleapis)[^"\']*)', html)[:5] or "无")

z = zipfile.ZipFile(D / "600693-东百集团-1139.docx")
print("\n=== DOCX 检查 ===")
print(f"  内部条目数: {len(z.namelist())}")
xml = z.read("word/document.xml").decode("utf-8")
cnt(xml, ["支撑", "压力", "止损", "11.26", "12.77", "10.80",
          "52", "评分", "多", "空"])
print("  '**' 加粗标记残留:", xml.count("**"))
