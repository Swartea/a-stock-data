"""任务 4 验证 v2.1：直接 import analyze_single(output_md=False)，不写文件。
从 64 只震荡候选中挑 12 只代表性 v2 逐只验证。

债 4 修法 ② 接入（梁大锋 17:20 拍板）：
- 启动时检查 screener_pool.csv + pool_meta.json
- 旧池（DEPRECATED）→ 仅 WARN（任务 4 闭环，海选池保留作历史归档，不阻断点票流程）
- 若未来用于三价位计算 → 必须先重跑 v4 生成新池
"""
import importlib.util
import json
import sys
from pathlib import Path

WORKSPACE = Path("/Users/swarteachou/Desktop/大A数据")
ANALYSIS = WORKSPACE / "analysis"
SCRIPTS = WORKSPACE / "scripts"
OUT_JSON = SCRIPTS / "v2_verify_results.json"

sys.path.insert(0, str(ANALYSIS))
sys.path.insert(0, str(SCRIPTS))

# 债 4 修法 ②：启动时跑 snapshot_guard（不强阻断，WARN 即可）
from snapshot_guard import check_csv_snapshot, check_meta_snapshot, emit

print("[债 4 接入] v2_verify_batch.py 启动 snapshot_guard 检查...")
csv_check = check_csv_snapshot(SCRIPTS / "screener_pool.csv")
emit(csv_check)
meta_check = check_meta_snapshot(SCRIPTS / "pool_meta.json")
emit(meta_check)
if csv_check.get("block"):
    # 旧池（任务 4 海选池）保留归档不阻断，但记录 BLOCK 状态
    print("[债 4 接入] 注意：screener_pool.csv 缺 price_snapshot_time 列，"
          "但本脚本走 v2 analyze_single 实时拉价，不依赖 CSV 现价。BLOCK 仅作记录。", flush=True)

# 加载 quant_analyzer_v2
spec = importlib.util.spec_from_file_location("qav2", ANALYSIS / "quant_analyzer_v2.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PICKS = [
    ("002014", "永新股份"),
    ("002120", "韵达股份"),
    ("002191", "劲嘉股份"),
    ("002216", "三全食品"),
    ("002332", "仙琚制药"),
    ("002603", "以岭药业"),
    ("002606", "大连电瓷"),
    ("002737", "葵花药业"),
    ("002901", "大博医疗"),
    ("600109", "国金证券"),
    ("600483", "福能股份"),
    ("603128", "华贸物流"),
]

def main():
    results = {}
    for i, (code, name) in enumerate(PICKS, 1):
        print(f"[{i}/{len(PICKS)}] {code} {name} ...", flush=True)
        try:
            r = mod.analyze_single(code, name, output_md=False)
            score = r.get("score", {})
            results[code] = {
                "name": name,
                "ok": True,
                "total": score.get("total"),
                "trend": score.get("trend"),
                "valuation": score.get("valuation"),
                "valuation_pctile": score.get("valuation_pctile"),
                "risk": score.get("risk"),
                "chip": score.get("chip"),
                "advice": r.get("advice"),
                "emoji": r.get("emoji"),
                "price": r.get("quote", {}).get("price"),
                "pe_ttm": r.get("quote", {}).get("pe_ttm"),
                "float_mcap_yi": r.get("quote", {}).get("mcap_yi"),
            }
            print(f"    ✓ total={score.get('total')} advice={r.get('advice')}", flush=True)
        except Exception as e:
            results[code] = {"name": name, "ok": False, "error": str(e)[:200]}
            print(f"    ✗ {type(e).__name__}: {str(e)[:80]}", flush=True)
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写 {OUT_JSON}", flush=True)

if __name__ == "__main__":
    main()
