"""二次筛选 V3：修正版。
修复:
1) 剔除 MA 异常行（MA20 偏离现价 0.5-2 倍之外）
2) 震荡票四线缠绕改成三线（MA20/60/120，MA5 用 V2 逐只验证阶段补）
3) 获利比例在 V3 用 现价/MA60 近似（精度粗略，v2 阶段重算）
4) 涨停否决用"今日涨幅<9.5%"近似（近5日次数在 v2 阶段补）
"""
from pathlib import Path

import pandas as pd

POOL = Path(__file__).parent / "screener_pool.csv"
OUT_TREND = Path(__file__).parent / "trend_candidates_v3.csv"
OUT_OSC = Path(__file__).parent / "oscillation_candidates_v3.csv"

def support_resist_stop(row):
    """支撑/压力/止损。
    支撑: MA20 与 近20低 取较大（MA20 是动态支撑）
    压力: 近60高（已突破取 现价*1.10）
    止损: 支撑 * 0.97
    """
    s_candidates = [row["MA20"], row["近20低"]]
    s = max([x for x in s_candidates if x > 0])
    r = row["近60高"]
    if r < row["现价"] * 0.95:
        r = row["现价"] * 1.10
    stop = round(s * 0.97, 2)
    return round(s, 2), round(r, 2), stop

def main():
    df = pd.read_csv(POOL, encoding="utf-8-sig")
    print(f"原始候选池: {len(df)} 只", flush=True)

    # === 1) 剔除 MA 异常行（MA20 与现价比值应在 0.5-2 之间）===
    df["ma_ratio"] = df["MA20"] / df["现价"]
    df_clean = df[(df["ma_ratio"] >= 0.5) & (df["ma_ratio"] <= 2)].copy()
    print(f"剔除 MA 异常后: {len(df_clean)} 只（剔除 {len(df) - len(df_clean)} 行）", flush=True)

    # === 2) 趋势票 ===
    trend = df_clean[
        (df_clean["MA20"] > df_clean["MA60"]) &
        (df_clean["MA60"] > df_clean["MA120"]) &
        (df_clean["现价"] > df_clean["MA20"]) &
        (df_clean["量比_20_60"] >= 1.2) &
        (df_clean["60日涨幅%"] >= 20) &
        (df_clean["20日最大回撤%"] < 15)
    ].copy()
    # 涨停否决：今日涨幅 < 9.5%（纯连板情绪）
    trend = trend[trend["今日涨幅%"] < 9.5]

    # 三价位
    if not trend.empty:
        trend["支撑"], trend["压力"], trend["止损"] = zip(*trend.apply(support_resist_stop, axis=1))

    # === 3) 震荡票 ===
    df_clean["band60"] = (df_clean["近60高"] - df_clean["近60低"]) / df_clean["近60低"] * 100
    ma_cols = ["MA20", "MA60", "MA120"]
    df_clean["ma_spread"] = (df_clean[ma_cols].max(axis=1) - df_clean[ma_cols].min(axis=1)) / df_clean[ma_cols].min(axis=1) * 100
    # 获利比例近似：现价与 MA60 距离 50% 视为 100% 获利
    df_clean["profit_ratio"] = ((df_clean["现价"] - df_clean["MA60"]) / df_clean["MA60"] * 100 + 50).clip(0, 100)

    osc = df_clean[
        (df_clean["band60"] <= 25) &
        (df_clean["ma_spread"] <= 3) &
        (df_clean["量比_20_60"] <= 1.5) &
        (df_clean["profit_ratio"] >= 30) & (df_clean["profit_ratio"] <= 70) &
        (df_clean["流通市值亿"] >= 50) & (df_clean["流通市值亿"] <= 500)
    ].copy()

    if not osc.empty:
        osc["支撑"], osc["压力"], osc["止损"] = zip(*osc.apply(support_resist_stop, axis=1))

    # 输出
    trend.to_csv(OUT_TREND, index=False, encoding="utf-8-sig")
    osc.to_csv(OUT_OSC, index=False, encoding="utf-8-sig")

    print(f"\n=== 趋势候选 {len(trend)} 只 ===", flush=True)
    cols_t = ["代码", "名称", "现价", "MA20", "MA60", "MA120", "60日涨幅%", "20日最大回撤%", "量比_20_60", "今日涨幅%", "支撑", "压力", "止损"]
    if not trend.empty:
        print(trend[cols_t].to_string(index=False), flush=True)
    print(f"\n=== 震荡候选 {len(osc)} 只 ===", flush=True)
    cols_o = ["代码", "名称", "现价", "MA20", "MA60", "MA120", "band60", "ma_spread", "量比_20_60", "profit_ratio", "流通市值亿", "支撑", "压力", "止损"]
    if not osc.empty:
        print(osc[cols_o].to_string(index=False), flush=True)

if __name__ == "__main__":
    main()
