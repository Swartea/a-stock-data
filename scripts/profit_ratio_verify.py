"""A 路补：12 只 9-4 获利比例复核（用 §4.6 chip_distribution）。

数据拼接：
- 历史 OHLC + turn：§6.5 baostock（窗口 = 2024-01-01 ~ 2026-09-03，T+1 滞后到 9-3）
- 9-4 当日 OHLC + turn：§1.2 腾讯实时行情（9-4 收盘后快照）
- 前复权：用腾讯 K 线接口拿的复权后价做拼接（v2_recalc 已落地）

输出：12 只 profit_ratio（百分数）+ 30-70% 门槛裁决。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据")
SCRIPTS = Path("/Users/swarteachou/Desktop/大A数据/scripts")

# 债 4 接入：本脚本用 baostock 历史 + 腾讯实时 9-4 当日，腾讯接口拉到的 last_date 必须是当日
# 否则本脚本的 profit_ratio 数据窗口不可信 → 由 snapshot_guard 在 run() 里每只单独阻断
from snapshot_guard import check_csv_snapshot, check_last_bar_today, check_meta_snapshot, emit

print("[债 4 接入] profit_ratio_verify.py 启动 snapshot_guard...")
csv_check = check_csv_snapshot(SCRIPTS / "screener_pool.csv")
emit(csv_check)
meta_check = check_meta_snapshot(SCRIPTS / "pool_meta.json")
emit(meta_check)


def baostock_full_history(code: str, end_date: str = "2026-09-03"):
    """§6.5 baostock 拉 OHLC + turn（截止 9-3，T+1 滞后）"""
    import baostock as bs
    bs_code = code[:2] in ("60", "68", "90") and f"sh.{code}" or f"sz.{code}"
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login fail: {lg.error_msg}")
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,turn,tradestatus",
            start_date="2024-01-01", end_date=end_date,
            frequency="d", adjustflag="2",     # 2=前复权，与 v2_recalc 的腾讯 qfq 对齐
        )
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        fields = rs.fields
    finally:
        bs.logout()
    df = pd.DataFrame(rows, columns=fields)
    for c in ("open", "high", "low", "close", "volume", "turn"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df


def tencent_realtime_ohlc(code: str):
    """§1.2 腾讯实时行情 → 当日 OHLC + turn"""
    import requests
    market = "sh" if code.startswith(("6", "9", "5")) else "sz"
    url = f"https://qt.gtimg.cn/q={market}{code}"
    r = requests.get(url, timeout=10)
    line = r.content.decode("gbk").strip()
    if "=" not in line or '"' not in line:
        return None
    vals = line.split('"')[1].split("~")
    if len(vals) < 53:
        return None
    return {
        "date": pd.Timestamp("2026-09-04"),
        "open": float(vals[5]),
        "high": float(vals[33]),
        "low": float(vals[34]),
        "close": float(vals[3]),
        "volume": 0,                    # 实时接口无 volume
        "turn": float(vals[38]) if vals[38] else 0,
        "tradestatus": "1",
    }


def chip_distribution(df: pd.DataFrame, grid_size: int = 300, decay: float = 1.0) -> dict:
    """§4.6 chip_distribution（从 SKILL.md 抄的，确保口径一致）"""
    df = df.sort_values("date").reset_index(drop=True)
    df = df[df["tradestatus"] == "1"].copy()  # 过滤停牌
    need = {"date", "high", "low", "close", "turn"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"chip_distribution 缺列: {sorted(missing)}")
    df = df.dropna(subset=["high", "low", "close", "turn"]).reset_index(drop=True)
    if df.empty:
        raise ValueError("chip_distribution: 有效行数为 0")

    grid_min = float(df["low"].min())
    grid_max = float(df["high"].max())
    if grid_max <= grid_min:
        raise ValueError(f"chip_distribution: 价格区间无效 grid_min={grid_min} grid_max={grid_max}")
    grid = np.linspace(grid_min, grid_max, grid_size)

    def daily_weight(row, grid):
        """当日筹码在价格网格上的三角分布权重（峰值在均价）"""
        lo, hi, cl, vo = row["low"], row["high"], row["close"], row["turn"]
        if hi <= lo or pd.isna(vo) or vo <= 0:
            return None
        peak = (lo + hi + cl) / 3.0 if cl else (lo + hi) / 2.0
        # 三角形：peak 处权重最大
        w = np.zeros_like(grid)
        left = (grid >= lo) & (grid <= peak)
        right = (grid > peak) & (grid <= hi)
        if peak > lo:
            w[left] = (grid[left] - lo) / (peak - lo)
        if hi > peak:
            w[right] = (hi - grid[right]) / (hi - peak)
        area = w.sum()
        if area > 0:
            w = w / area
        return w

    chips = None
    for _, row in df.iterrows():
        w = daily_weight(row, grid)
        if w is None:
            continue
        t = min(max(row["turn"] / 100.0, 0.0), 1.0)
        if chips is None:
            chips = w.copy()
        else:
            chips = chips * (1.0 - t) + w * t

    if chips is None:
        raise RuntimeError("chip_distribution: 无法构建分布")
    total = chips.sum()
    if total <= 0:
        raise RuntimeError("chip_distribution: 筹码总量为 0")
    chips = chips / total

    price = float(df["close"].iloc[-1])
    cum = np.cumsum(chips)

    def price_at(q):
        return float(np.interp(q, cum, grid))

    p05, p15, p85, p95 = (price_at(q) for q in (0.05, 0.15, 0.85, 0.95))
    peak_i = int(np.argmax(chips))
    return {
        "profit_ratio": float(chips[grid <= price].sum()),
        "avg_cost": float((grid * chips).sum()),
        "cost_90": (p05, p95),
        "cost_70": (p15, p85),
        "concentration_70": float((p85 - p15) / (p85 + p15)) if p85 + p15 else None,
        "peak_price": float(grid[peak_i]),
        "window_rows": int(len(df)),
        "last_date": str(df["date"].iloc[-1].date()),
        "last_price": price,
    }


CODES = [
    ("002014", "永新股份"), ("002120", "韵达股份"), ("002191", "劲嘉股份"),
    ("002216", "三全食品"), ("002332", "仙琚制药"), ("002603", "以岭药业"),
    ("002606", "大连电瓷"), ("002737", "葵花药业"), ("002901", "大博医疗"),
    ("600109", "国金证券"), ("600483", "福能股份"), ("603128", "华贸物流"),
]


def run():
    results = []
    for code, name in CODES:
        try:
            df_bs = baostock_full_history(code, end_date="2026-09-03")
            rt = tencent_realtime_ohlc(code)
            if rt is None:
                raise RuntimeError("腾讯实时拉取失败")
            # 拼接：baostock 历史（已含 9-3）+ 腾讯 9-4 当日
            row_94 = pd.DataFrame([rt])
            df = pd.concat([df_bs, row_94], ignore_index=True)
            chip = chip_distribution(df)
            in_range = 30 <= chip["profit_ratio"] * 100 <= 70

            # 债 4 修法 ③：last_date 强校验（block 即视为该只 profit_ratio 不可用）
            lb_check = check_last_bar_today(str(chip["last_date"]))
            emit(lb_check)
            block_reason = None
            if lb_check.get("block"):
                block_reason = lb_check.get("message")

            results.append({
                "code": code, "name": name,
                "profit_ratio_pct": round(chip["profit_ratio"] * 100, 2),
                "avg_cost": round(chip["avg_cost"], 2),
                "cost_70": [round(x, 2) for x in chip["cost_70"]],
                "peak_price": round(chip["peak_price"], 2),
                "in_30_70": in_range and not block_reason,
                "verdict": "存活" if (in_range and not block_reason) else ("BLOCK" if block_reason else "淘汰"),
                "block_reason": block_reason,
                "window_rows": chip["window_rows"],
                "last_date": chip["last_date"],
                "last_price": round(chip["last_price"], 2),
            })
            print(f"  ✅ {code} {name}: profit={chip['profit_ratio']*100:.2f}% "
                  f"peak={chip['peak_price']:.2f} avg_cost={chip['avg_cost']:.2f} "
                  f"→ {'存活' if in_range else '淘汰'}")
        except Exception as e:
            print(f"  ❌ {code} {name}: {e}")
            results.append({"code": code, "name": name, "error": str(e)})
    return results


if __name__ == "__main__":
    print("=== 12 只 9-4 获利比例复核（§6.5 + §1.2 + §4.6）===")
    results = run()
    out_path = SCRIPTS / "profit_ratio_verify.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n➡ 已落盘: {out_path}")
    survived = [r for r in results if r.get("verdict") == "存活"]
    eliminated = [r for r in results if r.get("verdict") == "淘汰"]
    print(f"统计：存活 {len(survived)} 只, 淘汰 {len(eliminated)} 只")
