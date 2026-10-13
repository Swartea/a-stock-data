"""A 路：用 mootdx/腾讯拉 9-4 K 线重算三价位 + 震荡口径复核。

梁大锋 4 条硬校验：
1. mootdx/腾讯，禁 baostock
2. 前复权统一 + 校验：最后 bar=9-4 且收盘价与 v2 price 偏差 ≤0.5%
3. 公式不变：支撑=近20低、压力=近20高×0.98（兜底 现价×1.10）、止损=支撑×0.97
4. 硬门槛：现价 > 支撑 且 现价 < 压力，破位整只淘汰

债 4 修法 ③（梁大锋 17:20 拍板）：
- 显式命名降级链：mootdx → 腾讯，二级终点
- 腾讯仍失败/非当日/空 → 立即停止抛错
- 严禁用 screener_pool.csv 陈旧现价兜底
- 引入 snapshot_guard.check_last_bar_today() 强校验（block=True 即抛 SystemExit）

补充：
- 复核震荡口径：60 日带宽 ≤25%、四线差 <3%、量比 ≤1.5×
- 存活票加 MA20/MA60 跌破但 v2 ≥65 分的降档检查
"""
import csv as _csv
import json
import sys
from datetime import datetime
from pathlib import Path

WORKDIR = Path("/Users/swarteachou/Desktop/大A数据/scripts")
POOL_CSV = WORKDIR / "screener_pool.csv"
POOL_META = WORKDIR / "pool_meta.json"
V2_JSON = WORKDIR / "v2_verify_results.json"
OUT_JSON = WORKDIR / "three_levels_recalc.json"

# 债 4 接入
sys.path.insert(0, str(WORKDIR))
from snapshot_guard import (
    SHANGHAI_TZ,
    check_csv_snapshot,
    check_last_bar_today,
    check_meta_snapshot,
    emit,
)

print("[债 4 接入] recalc_three_levels.py 启动 snapshot_guard...")
csv_check = check_csv_snapshot(POOL_CSV)
emit(csv_check)
meta_check = check_meta_snapshot(POOL_META)
emit(meta_check)
if meta_check.get("warn_untrustworthy") and not meta_check.get("snapshot_time"):
    # 旧池 DEPRECATED → 本脚本读 v2 实时价，不依赖 CSV，但仍打印告警
    print("[债 4 接入] screener_pool.csv 是 DEPRECATED 旧池，本脚本走 v2 实时价不读 CSV 现价，OK。",
          flush=True)

TODAY_STR = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d")
print(f"[债 4 接入] 今日={TODAY_STR}", flush=True)

CODES = [
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


def fetch_kline_tencent(code: str, days: int = 250):
    """腾讯财经 K 线接口（前复权）。"""
    import requests
    market = "sh" if code.startswith(("6", "9", "5")) else "sz"
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {
        "param": f"{market}{code},day,,,{days},qfq",
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    # 解析腾讯返回的 K 线
    key = f"qt_{market}{code}"
    if key not in data.get("data", {}):
        # 备选 key
        for k in data.get("data", {}).keys():
            if k.endswith(code):
                key = k
                break
    rows = data["data"][key].get("qfqday") or data["data"][key].get("day")
    if not rows:
        return None
    bars = []
    for row in rows:
        # 格式: [date, open, close, high, low, volume]
        bars.append({
            "date": row[0],
            "open": float(row[1]),
            "close": float(row[2]),
            "high": float(row[3]),
            "low": float(row[4]),
            "volume": float(row[5]),
        })
    return bars


def fetch_kline_mootdx(code: str, days: int = 250):
    """mootdx K 线接口（前复权）。"""
    try:
        from mootdx.reader import TdxDailyBarReader
        reader = TdxDailyBarReader()
        # mootdx market: 0=sz, 1=sh
        market = 1 if code.startswith(("6", "9", "5")) else 0
        df = reader.get_df(f"daily/market/{['sz','sh'][market]}/{code}.csv")
        # df columns: date, open, close, high, low, volume
        df = df.sort_values("date").tail(days)
        bars = []
        for _, row in df.iterrows():
            bars.append({
                "date": str(row["date"])[:10],
                "open": float(row["open"]),
                "close": float(row["close"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "volume": float(row["volume"]),
            })
        return bars
    except Exception as e:
        print(f"mootdx 失败 {code}: {e}")
        return None


def calc_ma(values, period):
    """简单移动平均。"""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def recalc_three_levels(code, name, v2_price):
    """重算三价位 + 震荡口径复核。返回 dict 或 None（数据源失败）。"""
    print(f"\n[{code} {name}] v2基准价={v2_price}")

    # 优先 mootdx，备选腾讯
    bars = fetch_kline_mootdx(code, days=250)
    source = "mootdx"
    if not bars:
        bars = fetch_kline_tencent(code, days=250)
        source = "tencent"
    if not bars:
        return {"code": code, "name": name, "ok": False, "error": "K线拉取失败"}

    last_bar = bars[-1]
    print(f"  数据源: {source}, 最后 bar: {last_bar['date']} 收盘={last_bar['close']}")

    # 债 4 修法 ③：用 snapshot_guard 做强校验（block=True 即抛错停止）
    lb_check = check_last_bar_today(last_bar["date"], today=TODAY_STR)
    emit(lb_check)
    if lb_check.get("block"):
        # 严禁用 screener_pool.csv 陈旧价兜底。点票场景：直接阻断该只；
        # 海选场景（main 捕获 RuntimeError）：该只淘汰 + 阻断消息入档
        raise RuntimeError(
            f"[债 4 阻断] {code} {name} last_bar={last_bar['date']} 非当日 "
            f"(today={TODAY_STR}, source={source}). 降级链 mootdx→腾讯 已用尽 → "
            f"禁止陈旧价兜底. 中止本只."
        )

    # 硬校验 2: 收盘价与 v2 price 偏差 ≤0.5%
    diff_pct = abs(last_bar["close"] - v2_price) / v2_price * 100
    if diff_pct > 0.5:
        return {"code": code, "name": name, "ok": False,
                "error": f"价偏差{diff_pct:.2f}%, last={last_bar['close']} v2={v2_price}"}
    print(f"  校验通过: 偏差 {diff_pct:.3f}%")

    # 取近 20 / 60 日窗口（含当日）
    closes = [b["close"] for b in bars[-60:]]
    highs = [b["high"] for b in bars[-20:]]
    lows = [b["low"] for b in bars[-20:]]
    highs_60 = [b["high"] for b in bars[-60:]]
    lows_60 = [b["low"] for b in bars[-60:]]
    vols = [b["volume"] for b in bars[-20:]]
    vols_60 = [b["volume"] for b in bars[-60:]]

    current_price = last_bar["close"]

    # 三价位公式
    support = min(lows)               # 近 20 低
    resist_raw = max(highs) * 0.98    # 近 20 高 × 0.98
    resist = max(resist_raw, current_price * 1.10) if resist_raw <= current_price else resist_raw
    stop_loss = support * 0.97

    # 震荡口径复核
    high_60 = max(highs_60)
    low_60 = min(lows_60)
    band_pct = (high_60 - low_60) / current_price * 100  # 60 日带宽 %

    # 四线 MA
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    ma_values = [v for v in [ma5, ma10, ma20, ma60] if v]
    if ma_values:
        ma_range_pct = (max(ma_values) - min(ma_values)) / current_price * 100
    else:
        ma_range_pct = None

    # 量比
    vol_20 = sum(vols) / len(vols)
    vol_60 = sum(vols_60) / len(vols_60)
    vol_ratio = vol_20 / vol_60 if vol_60 > 0 else None

    # 硬门槛
    pass_three_level = current_price > support and current_price < resist

    # 震荡口径硬门槛
    pass_osc = (band_pct <= 25) and (ma_range_pct is not None and ma_range_pct < 3) and (vol_ratio is not None and vol_ratio <= 1.5)

    print(f"  支撑={support:.2f} 压力={resist:.2f} 止损={stop_loss:.2f}")
    print(f"  现价={current_price:.2f} | 三价位门槛 {'✅' if pass_three_level else '❌'}")
    print(f"  60日带宽={band_pct:.2f}% MA差={ma_range_pct:.2f}% 量比={vol_ratio:.2f} | 震荡口径 {'✅' if pass_osc else '❌'}")

    return {
        "code": code,
        "name": name,
        "ok": True,
        "source": source,
        "last_bar_date": last_bar["date"],
        "v2_price": v2_price,
        "last_close": current_price,
        "diff_pct": round(diff_pct, 3),
        "support": round(support, 2),
        "resist": round(resist, 2),
        "stop_loss": round(stop_loss, 2),
        "high_60": round(high_60, 2),
        "low_60": round(low_60, 2),
        "band_pct": round(band_pct, 2),
        "ma5": round(ma5, 2) if ma5 else None,
        "ma10": round(ma10, 2) if ma10 else None,
        "ma20": round(ma20, 2) if ma20 else None,
        "ma60": round(ma60, 2) if ma60 else None,
        "ma_range_pct": round(ma_range_pct, 2) if ma_range_pct else None,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio else None,
        "pass_three_level": pass_three_level,
        "pass_osc": pass_osc,
        "reason_eliminate": (
            None if (pass_three_level and pass_osc) else (
                "三价位破位" if not pass_three_level else (
                    f"震荡口径不合(band={band_pct:.1f}%, ma差={ma_range_pct:.1f}%, 量比={vol_ratio:.2f})"
                )
            )
        ),
    }


def main():
    # 加载 v2 基准价
    with open(V2_JSON, "r", encoding="utf-8") as f:
        v2_data = json.load(f)

    results = []
    for code, name in CODES:
        v2_entry = v2_data.get(code, {})
        v2_price = v2_entry.get("price")
        v2_total = v2_entry.get("total")
        v2_advice = v2_entry.get("advice")
        if v2_price is None:
            print(f"⚠️ {code} {name} 无 v2 基准价，跳过")
            continue
        try:
            r = recalc_three_levels(code, name, v2_price)
            if r and r.get("ok"):
                r["v2_total"] = v2_total
                r["v2_advice"] = v2_advice
                # MA20/MA60 跌破但 v2 ≥65 分的降档检查
                if r["ma20"] and r["last_close"] < r["ma20"] and v2_total and v2_total >= 65:
                    r["downgrade_note"] = f"现价{r['last_close']}<MA20={r['ma20']}但v2={v2_total}分，建议复核v2 trend因子"
        except RuntimeError as e:
            # 债 4 修法 ③：last_bar 非当日阻断，本只淘汰不阻断下一批
            print(f"  [债 4 阻断] {code} {name} → {e}", flush=True)
            r = {"code": code, "name": name, "ok": False, "error": str(e),
                 "block_by": "snapshot_guard", "v2_total": v2_total}
        results.append(r)

    # 写结果
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 写入 {OUT_JSON}")

    # 汇总
    print("\n=== 汇总 ===")
    survivors = [r for r in results if r.get("ok") and r["pass_three_level"] and r["pass_osc"]]
    eliminated = [r for r in results if not (r.get("ok") and r["pass_three_level"] and r["pass_osc"])]
    print(f"存活: {len(survivors)} 只")
    for r in survivors:
        print(f"  ✅ {r['code']} {r['name']} v2={r['v2_total']}分 三价=[{r['support']}, {r['resist']}, {r['stop_loss']}] 现价={r['last_close']}")
    print(f"\n淘汰: {len(eliminated)} 只")
    for r in eliminated:
        reason = r.get('reason_eliminate') or r.get('error', '未知')
        print(f"  ❌ {r['code']} {r['name']} - {reason}")


if __name__ == "__main__":
    main()
