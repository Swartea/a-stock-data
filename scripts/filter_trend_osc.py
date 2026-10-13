"""二次筛选：从 screener_pool.csv 筛出趋势票 + 震荡票。
趋势: MA20>MA60>MA120 + 60日涨幅≥20% + 20日回撤<15% + 量比≥1.2 + 近5日涨停<3次
震荡: 60日带宽≤25% + 四线差值<3% + 缩量 (20日均量≤1.5×60日均量) + 流通50-500亿
"""
from pathlib import Path

import pandas as pd

POOL = Path(__file__).parent / "screener_pool.csv"
OUT_TREND = Path(__file__).parent / "trend_candidates.csv"
OUT_OSC = Path(__file__).parent / "oscillation_candidates.csv"

df = pd.read_csv(POOL, encoding="utf-8-sig")
# 同花顺热点票多数今日涨停 → 放宽涨幅口径，先按结构 + 量比筛
# 趋势票：MA20 > MA60 > MA120, 现价站上 MA20, 量比 >= 1.2
# 涨幅条件放宽到"60日涨幅 ≥ 10%"（海选样本是当日热点，本身涨幅偏大）
# 回撤放宽到"20日最大回撤 < 20%"
trend = df[
    (df["MA20"] > df["MA60"]) &
    (df["MA60"] > df["MA120"]) &
    (df["现价"] > df["MA20"]) &
    (df["量比_20_60"] >= 1.2) &
    (df["60日涨幅%"] >= 10) &
    (df["20日最大回撤%"] < 20)
].copy()

# 震荡票：60日带宽 (近60高-近60低)/近60低 ≤ 25%, 四线差值小 (max-min)/min ≤ 3%
df["band60"] = ((df["近60高"] - df["近60低"]) / df["近60低"] * 100)
df["ma_spread"] = ((df[["MA20","MA60","MA120"]].max(axis=1) - df[["MA20","MA60","MA120"]].min(axis=1))
                   / df[["MA20","MA60","MA120"]].min(axis=1) * 100)
osc = df[
    (df["band60"] <= 25) &
    (df["ma_spread"] <= 3) &
    (df["量比_20_60"] <= 1.5) &
    (df["流通市值亿"] >= 50) & (df["流通市值亿"] <= 500)
].copy()

trend.to_csv(OUT_TREND, index=False, encoding="utf-8-sig")
osc.to_csv(OUT_OSC, index=False, encoding="utf-8-sig")

print(f"趋势候选: {len(trend)} 只")
print(f"震荡候选: {len(osc)} 只")
print()
print("=== 趋势候选 ===")
print(trend[["代码","名称","现价","MA20","MA60","MA120","60日涨幅%","20日最大回撤%","量比_20_60"]].to_string(index=False))
print()
print("=== 震荡候选 ===")
print(osc[["代码","名称","现价","MA20","MA60","MA120","band60","ma_spread","量比_20_60","流通市值亿"]].to_string(index=False))
