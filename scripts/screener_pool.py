"""股票池过滤：同花顺热点 + 腾讯市值 + baostock 上市日/ST/历史 K 线。
输出: scripts/screener_pool.csv (候选池 ~30-60 只，含 MA/涨幅/回撤/量比)
"""
import csv
import sys
import time
from pathlib import Path

import baostock as bs
import pandas as pd
import requests

OUT = Path(__file__).parent / "screener_pool.csv"

# ===== 同花顺热点 (Layer 3.1) =====
def ths_hot_reason(date: str = "2026-09-04") -> pd.DataFrame:
    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"}
    r = requests.get(url, headers=headers, timeout=15)
    data = r.json()
    if data.get("errocode", 0) != 0:
        raise RuntimeError(f"ths_hot_reason err: {data.get('errormsg','')}")
    rows = data.get("data") or []
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    rename = {
        "name":"名称","code":"代码","reason":"题材归因",
        "close":"收盘价","zhangdie":"涨跌额","zhangfu":"涨幅%",
        "huanshou":"换手率%","chengjiaoe":"成交额","chengjiaoliang":"成交量",
        "ddejingliang":"大单净量","market":"市场",
    }
    return df.rename(columns=rename)

# ===== 腾讯财经批量 (Layer 1.2) =====
SH_INDEX = {"000300","000905","000016","000688","000852","000010"}
def tencent_quote(codes: list[str]) -> dict[str, dict]:
    prefixed, key_of = [], {}
    for c in codes:
        low = c.lower()
        if low.startswith(("sh","sz","bj")):
            p = low
        elif c.startswith("92"):
            p = f"bj{c}"
        elif c in SH_INDEX or c.startswith(("5","6","9")):
            p = f"sh{c}"
        elif c.startswith(("4","8")):
            p = f"bj{c}"
        else:
            p = f"sz{c}"
        prefixed.append(p); key_of[p] = c
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=15)
    data = req.content.decode("gbk", errors="ignore")
    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53: continue
        code = key_of.get(key, key[2:])
        try:
            result[code] = {
                "name": vals[1],
                "price": float(vals[3]) if vals[3] else 0,
                "last_close": float(vals[4]) if vals[4] else 0,
                "change_pct": float(vals[32]) if vals[32] else 0,
                "amount_wan": float(vals[37]) if vals[37] else 0,
                "turnover_pct": float(vals[38]) if vals[38] else 0,
                "pe_ttm": float(vals[39]) if vals[39] else 0,
                "float_mcap_yi": float(vals[44]) if vals[44] else 0,   # 流通市值
                "mcap_yi": float(vals[45]) if vals[45] else 0,         # 总市值
                "pb": float(vals[46]) if vals[46] else 0,
                "vol_ratio": float(vals[49]) if vals[49] else 0,
            }
        except (ValueError, IndexError):
            continue
    return result

# ===== baostock: 上市日 + ST + 250 日 K 线 + MA =====
def _bs_code(code: str) -> str:
    if code.startswith(("4","8","92","920")):
        raise ValueError(f"baostock 不支持 {code}")
    if code.startswith(("5","6","9")) or code.startswith("000"):
        return f"sh.{code}"
    return f"sz.{code}"

def bs_session():
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"bs login fail: {lg.error_msg}")
    return None

def bs_logout():
    bs.logout()

def bs_ipo_date(code: str) -> str:
    bs_code = _bs_code(code)
    rs = bs.query_stock_basic(code=bs_code)
    if rs.error_code != "0":
        return ""
    rows = []
    while (rs.error_code == "0") and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return ""
    df = pd.DataFrame(rows, columns=rs.fields)
    return str(df.iloc[0].get("ipoDate", "") or "")

def bs_history(code: str, days: int = 250) -> pd.DataFrame:
    bs_code = _bs_code(code)
    end = "2026-09-04"
    # 取 250 个交易日，按 365 天回溯
    start = "2025-08-01"
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,close,turn,tradestatus,isST",
        start_date=start, end_date=end,
        frequency="d", adjustflag="3",
    )
    if rs.error_code != "0":
        raise RuntimeError(f"bs history fail: {rs.error_msg}")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    if df.empty:
        return df
    for c in ("close","turn"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["tradestatus"] == "1"].copy()
    df = df.tail(days).reset_index(drop=True)
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["ma120"] = df["close"].rolling(120).mean()
    return df

# ===== 主流程 =====
def main():
    print("[1/4] 拉同花顺热点 ...", flush=True)
    hot = ths_hot_reason("2026-09-04")
    print(f"  -> 拿到 {len(hot)} 只", flush=True)
    if hot.empty:
        print("EMPTY"); return
    # 过滤：60/00/30 开头 + 名称不含 ST
    def ok(row):
        c = str(row["代码"]).zfill(6)
        if not (c.startswith(("60","00","30"))):
            return False
        n = str(row["名称"])
        if "ST" in n.upper() or "退" in n:
            return False
        return True
    hot = hot[hot.apply(ok, axis=1)].reset_index(drop=True)
    print(f"  -> 前缀过滤后 {len(hot)} 只", flush=True)
    if hot.empty:
        print("EMPTY after prefix filter"); return

    print("[2/4] 腾讯批量行情 ...", flush=True)
    codes = [str(c).zfill(6) for c in hot["代码"]]
    quotes = tencent_quote(codes)
    print(f"  -> 拿到 {len(quotes)} 只报价", flush=True)

    print("[3/4] baostock 上市日 + K 线 ...", flush=True)
    bs_session()
    try:
        rows = []
        for i, c in enumerate(codes):
            try:
                ipo = bs_ipo_date(c)
                if ipo and len(ipo) >= 10:
                    # 上市 > 250 交易日 ≈ 上市 > ~14 个月（按 250/365 比例）
                    from datetime import date as _d
                    try:
                        ipo_d = _d(int(ipo[:4]), int(ipo[5:7]), int(ipo[8:10]))
                        if (_d(2026,9,4) - ipo_d).days < 420:  # 约 14 个月
                            continue
                    except Exception:
                        pass
                hist = bs_history(c, 250)
                if hist.empty or len(hist) < 130:
                    continue
                last = hist.iloc[-1]
                if pd.isna(last["ma120"]):
                    continue
                # K 线核心指标
                close60 = hist["close"].tail(60)
                close20 = hist["close"].tail(20)
                close5 = hist["close"].tail(5)
                hi60 = close60.max(); lo60 = close60.min()
                hi20 = close20.max(); lo20 = close20.min()
                # 涨幅 60 日 = (现/60日前) - 1
                ret60 = (last["close"] / hist["close"].iloc[-60] - 1) * 100 if len(hist) >= 60 else 0
                # 最大回撤 20 日 = (20 日最高 - 期间最低)/20 日最高
                dd20 = ((hi20 - close20.min()) / hi20) * 100 if hi20 > 0 else 0
                # 量比 (20 日均量 / 60 日均量 近似 — turn)
                avg_turn_20 = close20.iloc[-1] and hist["turn"].tail(20).mean() or 0
                avg_turn_60 = hist["turn"].tail(60).mean() or 1
                vol_ratio = avg_turn_20 / avg_turn_60 if avg_turn_60 else 0
                # 近 5 日涨停数 (近 5 个交易日中涨幅 ≥ 9.8% 的天数)
                hot_tail = hot[hot["代码"].astype(str).str.zfill(6) == c]
                if not hot_tail.empty:
                    name = str(hot_tail.iloc[0]["名称"])
                    theme = str(hot_tail.iloc[0]["题材归因"]) if "题材归因" in hot_tail.columns else ""
                else:
                    name = quotes.get(c, {}).get("name", "")
                    theme = ""
                q = quotes.get(c, {})
                rows.append({
                    "代码": c,
                    "名称": name,
                    "题材": theme[:40],
                    "现价": q.get("price", last["close"]),
                    "今日涨幅%": q.get("change_pct", 0),
                    "流通市值亿": q.get("float_mcap_yi", 0),
                    "PE_TTM": q.get("pe_ttm", 0),
                    "PB": q.get("pb", 0),
                    "MA20": round(last["ma20"], 3) if not pd.isna(last["ma20"]) else 0,
                    "MA60": round(last["ma60"], 3) if not pd.isna(last["ma60"]) else 0,
                    "MA120": round(last["ma120"], 3) if not pd.isna(last["ma120"]) else 0,
                    "60日涨幅%": round(ret60, 2),
                    "20日最大回撤%": round(dd20, 2),
                    "量比_20_60": round(vol_ratio, 3),
                    "近60高": round(hi60, 2),
                    "近60低": round(lo60, 2),
                    "近20高": round(hi20, 2),
                    "近20低": round(lo20, 2),
                    "上市日": ipo,
                })
            except Exception as e:
                print(f"  skip {c}: {type(e).__name__}: {e}", flush=True)
                continue
            if (i+1) % 5 == 0:
                print(f"  ... {i+1}/{len(codes)}", flush=True)
            time.sleep(0.3)
    finally:
        bs_logout()

    df = pd.DataFrame(rows)
    print(f"[4/4] 写 CSV ... {len(df)} 行", flush=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    # 顺带输出关键分布
    if not df.empty:
        print(f"  流通市值分布: min={df['流通市值亿'].min():.1f} max={df['流通市值亿'].max():.1f} median={df['流通市值亿'].median():.1f}", flush=True)
        print(f"  60日涨幅分布: min={df['60日涨幅%'].min():.1f} max={df['60日涨幅%'].max():.1f} median={df['60日涨幅%'].median():.1f}", flush=True)

if __name__ == "__main__":
    main()
