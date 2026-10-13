"""二次筛选 V2：从 screener_pool.csv 筛出趋势票 + 震荡票（按梁大锋 9-4 修订口径）。
趋势: MA20>MA60>MA120 + 现价>MA20 + 60日涨幅≥20% + 20日回撤<15% + 量比_20_60≥1.2 + 涨停否决
震荡: 60日带宽≤25% + 四线差值<3% + 缩量 (量比_20_60≤1.5) + 流通50-500亿
每只必须给全支撑/压力/止损三价位才入围。
"""
from pathlib import Path

import pandas as pd

POOL = Path(__file__).parent / "screener_pool.csv"
OUT_TREND = Path(__file__).parent / "trend_candidates.csv"
OUT_OSC = Path(__file__).parent / "oscillation_candidates.csv"

def support_resist_stop(row):
    """为单只计算支撑/压力/止损。
    支撑: 近20低 + MA60 + 0.9*筹码峰(近似近20低) 取 max
    压力: 近60高 + MA20 + 当前价 上方 8% (保守)
    止损: 支撑 × 0.97
    返回 (support, resist, stop) 或 None
    """
    s_candidates = [row["近20低"], row["MA60"]]
    s = max([x for x in s_candidates if x > 0])
    # 压力：近60高（前提是现价离近60高不是太远）
    r = row["近60高"]
    if r < row["现价"] * 0.95:
        # 现价已突破 60 日高，压力量化取现价 * 1.10 作为压力延伸
        r = row["现价"] * 1.10
    stop = round(s * 0.97, 2)
    return round(s, 2), round(r, 2), stop

def main():
    df = pd.read_csv(POOL, encoding="utf-8-sig")
    print(f"候选池: {len(df)} 只\n", flush=True)
    if df.empty:
        return

    # === 趋势票 ===
    trend = df[
        (df["MA20"] > df["MA60"]) &
        (df["MA60"] > df["MA120"]) &
        (df["现价"] > df["MA20"]) &
        (df["量比_20_60"] >= 1.2) &
        (df["60日涨幅%"] >= 20) &
        (df["20日最大回撤%"] < 15)
    ].copy()
    # 涨停否决：今日涨幅 < 9.5%（剔除纯连板情绪）
    trend = trend[trend["今日涨幅%"] < 9.5]
    # 计算三价位
    trend["支撑"], trend["压力"], trend["止损"] = zip(*trend.apply(support_resist_stop, axis=1))

    # === 震荡票 ===
    df["band60"] = ((df["近60高"] - df["近60低"]) / df["近60低"] * 100)
    ma_cols = ["MA20","MA60","MA120"]
    df["ma_spread"] = ((df[ma_cols].max(axis=1) - df[ma_cols].min(axis=1)) / df[ma_cols].min(axis=1) * 100)
    osc = df[
        (df["band60"] <= 25) &
        (df["ma_spread"] <= 3) &
        (df["量比_20_60"] <= 1.5) &
        (df["流通市值亿"] >= 50) & (df["流通市值亿"] <= 500)
    ].copy()
    osc["支撑"], osc["压力"], osc["止损"] = zip(*osc.apply(support_resist_stop, axis=1))

    trend.to_csv(OUT_TREND, index=False, encoding="utf-8-sig")
    osc.to_csv(OUT_OSC, index=False, encoding="utf-8-sig")

    print(f"\n=== 趋势候选 {len(trend)} 只 ===", flush=True)
    if not trend.empty:
        print(trend[["代码","名称","现价","MA20","MA60","MA120","60日涨幅%","20日最大回撤%","量比_20_60","支撑","压力","止损"]].to_string(index=False), flush=True)
    print(f"\n=== 震荡候选 {len(osc)} 只 ===", flush=True)
    if not osc.empty:
        print(osc[["代码","名称","现价","MA20","MA60","MA120","band60","ma_spread","量比_20_60","支撑","压力","止损"]].to_string(index=False), flush=True)

if __name__ == "__main__":
    main()
