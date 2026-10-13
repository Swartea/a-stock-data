"""股票池过滤 V4：申万全 A 5918 只 + 腾讯流通市值 + baostock K 线 + 上市日。
最终筛选: 60/00/30 + 非 ST + 上市>14月 + 流通50-500亿 + 成交活跃。
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import baostock as bs
import pandas as pd
import requests

OUT = Path(__file__).parent / "screener_pool.csv"
META = Path(__file__).parent / "pool_meta.json"  # 债 4 修法 ①：价格快照时点落档
SW_FILE = Path("/tmp/sw.xls")  # 申万全 A 清单（curl 预下载，避开 SSL）

# 债 4 修法：行情源统一锚定 Asia/Shanghai
SHANGHAI_TZ = timezone(timedelta(hours=8))
TODAY = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d")
NOW_ISO = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")

def load_sw_codes() -> list[str]:
    if not SW_FILE.exists():
        # 下载
        subprocess.run(['curl','-SLo',str(SW_FILE),
            '-H','Referer: https://www.swsresearch.com/swindex/',
            '-H','User-Agent: Mozilla/5.0',
            'https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls'],
            check=True)
    df = pd.read_excel(SW_FILE)
    codes = df["股票代码"].astype(str).str.zfill(6).unique().tolist()
    return codes

def tencent_quote(codes: list[str]) -> dict[str, dict]:
    SH_INDEX = {"000300","000905","000016","000688","000852","000010"}
    prefixed, key_of = [], {}
    for c in codes:
        if c.startswith("92"):
            p = f"bj{c}"
        elif c in SH_INDEX or c.startswith(("5","6","9")):
            p = f"sh{c}"
        elif c.startswith(("4","8")):
            p = f"bj{c}"
        else:
            p = f"sz{c}"
        prefixed.append(p); key_of[p] = c
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=20)
    data = req.content.decode("gbk", errors="ignore")
    result = {}
    for line in data.strip().split(";"):
        if '"' not in line or "=" not in line: continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53: continue
        code = key_of.get(key, key[2:])
        try:
            result[code] = {
                "name": vals[1],
                "price": float(vals[3]) if vals[3] else 0,
                "change_pct": float(vals[32]) if vals[32] else 0,
                "amount_wan": float(vals[37]) if vals[37] else 0,
                "pe_ttm": float(vals[39]) if vals[39] else 0,
                "float_mcap_yi": float(vals[44]) if vals[44] else 0,
                "pb": float(vals[46]) if vals[46] else 0,
                "vol_ratio": float(vals[49]) if vals[49] else 0,
            }
        except (ValueError, IndexError): continue
    return result

def bs_code_of(code: str) -> str:
    if code.startswith(("4","8","92","920")):
        raise ValueError(f"bs 不支持 {code}")
    if code.startswith(("5","6","9")) or code.startswith("000"):
        return f"sh.{code}"
    return f"sz.{code}"

def bs_ipo_date(code: str) -> str:
    bs_code = bs_code_of(code)
    rs = bs.query_stock_basic(code=bs_code)
    if rs.error_code != "0": return ""
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows: return ""
    df = pd.DataFrame(rows, columns=rs.fields)
    return str(df.iloc[0].get("ipoDate", "") or "")

def bs_history(code: str) -> pd.DataFrame:
    bs_code = bs_code_of(code)
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,close,turn,tradestatus,isST",
        start_date="2025-08-01", end_date="2026-09-04",
        frequency="d", adjustflag="3",
    )
    if rs.error_code != "0":
        raise RuntimeError(f"bs err: {rs.error_msg}")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    if df.empty: return df
    for c in ("close","turn"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["tradestatus"] == "1"].copy().reset_index(drop=True)
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["ma120"] = df["close"].rolling(120).mean()
    return df

def main():
    print("[1/4] 申万全 A 清单 ...", flush=True)
    codes = load_sw_codes()
    print(f"  -> {len(codes)} 只原始", flush=True)
    codes = [c for c in codes if c.startswith(("60","00","30"))]
    print(f"  -> 前缀过滤(60/00/30): {len(codes)} 只", flush=True)

    print("[2/4] 腾讯批量行情 ...", flush=True)
    quotes = {}
    for i in range(0, len(codes), 80):
        batch = codes[i:i+80]
        quotes.update(tencent_quote(batch))
        if (i // 80) % 5 == 0:
            print(f"  ... {min(i+80,len(codes))}/{len(codes)}", flush=True)
        time.sleep(0.25)
    print(f"  -> {len(quotes)} 只报价", flush=True)
    # 过滤：流通 50-500 + 非 ST + 现价>0 + 成交活跃
    valid = []
    for c, q in quotes.items():
        if not (50 <= q.get("float_mcap_yi",0) <= 500): continue
        n = str(q.get("name",""))
        if "ST" in n.upper() or "退" in n: continue
        if q.get("price",0) <= 0 or q.get("amount_wan",0) < 1000: continue
        valid.append(c)
    print(f"  -> 流通+活跃过滤: {len(valid)} 只", flush=True)

    print(f"[3/4] baostock 上市日 + 250 日 K 线 ({len(valid)} 只) ...", flush=True)
    bs.login()
    try:
        rows = []
        fail = 0
        for i, c in enumerate(valid):
            try:
                ipo = bs_ipo_date(c)
                if ipo and len(ipo) >= 10:
                    from datetime import date as _d
                    try:
                        ipo_d = _d(int(ipo[:4]), int(ipo[5:7]), int(ipo[8:10]))
                        if (_d(2026,9,4) - ipo_d).days < 420:
                            continue  # 上市 < 14 月
                    except Exception: pass
                hist = bs_history(c)
                if hist.empty or len(hist) < 130:
                    fail += 1; continue
                last = hist.iloc[-1]
                if pd.isna(last["ma120"]):
                    fail += 1; continue
                close60 = hist["close"].tail(60)
                close20 = hist["close"].tail(20)
                hi60 = close60.max(); lo60 = close60.min()
                hi20 = close20.max(); lo20 = close20.min()
                ret60 = (last["close"] / hist["close"].iloc[-60] - 1) * 100
                dd20 = ((hi20 - close20.min()) / hi20) * 100 if hi20 > 0 else 0
                vol_ratio = (hist["turn"].tail(20).mean() or 0) / (hist["turn"].tail(60).mean() or 1)
                q = quotes.get(c, {})
                rows.append({
                    "代码": c,
                    "名称": q.get("name",""),
                    "现价": q.get("price", last["close"]),
                    "今日涨幅%": q.get("change_pct", 0),
                    "流通市值亿": q.get("float_mcap_yi", 0),
                    "PE_TTM": q.get("pe_ttm", 0),
                    "PB": q.get("pb", 0),
                    "量比_今日": q.get("vol_ratio", 0),
                    "MA20": round(last["ma20"], 3),
                    "MA60": round(last["ma60"], 3),
                    "MA120": round(last["ma120"], 3),
                    "60日涨幅%": round(ret60, 2),
                    "20日最大回撤%": round(dd20, 2),
                    "量比_20_60": round(vol_ratio, 3),
                    "近60高": round(hi60, 2),
                    "近60低": round(lo60, 2),
                    "近20高": round(hi20, 2),
                    "近20低": round(lo20, 2),
                    "上市日": ipo,
                })
            except Exception:
                fail += 1
                continue
            if (i+1) % 30 == 0:
                print(f"  ... {i+1}/{len(valid)} (fail={fail})", flush=True)
            time.sleep(0.1)
    finally:
        bs.logout()

    df = pd.DataFrame(rows)
    # 债 4 修法 ①：每行落价格快照时点（ISO 8601），便于下游脚本做时点强校验
    df["price_snapshot_time"] = NOW_ISO
    df["price_snapshot_source"] = "tencent+q+baostock_kf"
    print(f"[4/4] 写 CSV: {len(df)} 行 (fail={fail})", flush=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")

    # 债 4 修法 ①：同时落 pool_meta.json（汇总元数据，下游 guard 用）
    meta = {
        "csv_path": str(OUT),
        "snapshot_time_iso": NOW_ISO,
        "snapshot_date": TODAY,
        "snapshot_timezone": "Asia/Shanghai",
        "row_count": len(df),
        "fail_count": fail,
        "valid_after_prefix": len(codes),
        "valid_after_active": len(valid),
        "sources": {
            "industry_list": "swresearch.com (SwClass2021)",
            "quote": "tencent (qt.gtimg.cn)",
            "kline_history": "baostock (adjustflag=3, T+1)",
        },
        "snapshot_warn": (
            "此 meta 中的 snapshot_time_iso 是行情快照时点，下游验证脚本若读到超过 1 小时"
            "会自动 WARN（不阻断）。K 线当日 bar 必须走 mootdx/腾讯重拉，禁止用此 CSV 现价兜底。"
        ),
    }
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  落 pool_meta.json: {META}", flush=True)

    if not df.empty:
        print(f"  流通市值: min={df['流通市值亿'].min():.0f} max={df['流通市值亿'].max():.0f} median={df['流通市值亿'].median():.0f}", flush=True)
        print(f"  60日涨幅: min={df['60日涨幅%'].min():.1f} max={df['60日涨幅%'].max():.1f} median={df['60日涨幅%'].median():.1f}", flush=True)
        print(f"  MA 多头(MA20>MA60>MA120): {((df['MA20']>df['MA60']) & (df['MA60']>df['MA120'])).sum()} 只", flush=True)
        print(f"  MA 空头(MA20<MA60<MA120): {((df['MA20']<df['MA60']) & (df['MA60']<df['MA120'])).sum()} 只", flush=True)

if __name__ == "__main__":
    main()
