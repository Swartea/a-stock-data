"""股票池过滤 V2：同花顺热点 + 沪深300 + 中证500 成分股，海选更广。
输出: scripts/screener_pool.csv (候选池 ~150-250 只，含 MA/涨幅/回撤/量比)
"""
import csv
import json
import sys
import time
from pathlib import Path

import baostock as bs
import pandas as pd
import requests

OUT = Path(__file__).parent / "screener_pool.csv"
HS300_FILE = Path(__file__).parent / "hs300.csv"
ZZ500_FILE = Path(__file__).parent / "zz500.csv"

# ===== 沪深 300 + 中证 500 成分股（从腾讯/东财指数成分查） =====
def fetch_index_constituents():
    """腾讯指数成分接口：返回 list of {code, name}"""
    result = {}
    # 沪深 300 (sh000300) + 中证 500 (sh000905)
    for idx_code, idx_name in [("sh000300", "沪深300"), ("sh000905", "中证500")]:
        url = f"https://qt.gtimg.cn/q={idx_code}"
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=15)
        # 指数字段格式不同，需要另一接口
        # 改用东方财富成分接口
        pass
    # 实际拿成分股用东财 pc 接口
    constituents = {}
    for secid, name in [("1.000300","沪深300"), ("1.000905","中证500")]:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn":"1","pz":"500","po":"1","np":"1","fltt":"2","invt":"2",
            "fid":"f3","fs":f"b:{secid}","fields":"f12,f14","_":"1"
        }
        try:
            r = requests.get(url, params=params,
                headers={"User-Agent":"Mozilla/5.0",
                    "Referer":"https://quote.eastmoney.com/"}, timeout=15)
            data = r.json()
            for item in data.get("data",{}).get("diff",[]):
                constituents[item["f12"]] = name
        except Exception as e:
            print(f"  skip {name}: {e}", flush=True)
    return constituents

# ===== 同花顺热点 (Layer 3.1) =====
def ths_hot_reason(date: str = "2026-09-04") -> list[str]:
    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        if data.get("errocode", 0) != 0:
            return []
        return [str(row["code"]).zfill(6) for row in (data.get("data") or [])]
    except Exception:
        return []

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
                "float_mcap_yi": float(vals[44]) if vals[44] else 0,
                "mcap_yi": float(vals[45]) if vals[45] else 0,
                "pb": float(vals[46]) if vals[46] else 0,
                "vol_ratio": float(vals[49]) if vals[49] else 0,
            }
        except (ValueError, IndexError):
            continue
    return result

# ===== baostock =====
def _bs_code(code: str) -> str:
    if code.startswith(("4","8","92","920")):
        raise ValueError(f"baostock 不支持 {code}")
    if code.startswith(("5","6","9")) or code.startswith("000"):
        return f"sh.{code}"
    return f"sz.{code}"

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
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,close,turn,tradestatus,isST",
        start_date="2025-08-01", end_date="2026-09-04",
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

def main():
    print("[1/5] 沪深 300 + 中证 500 成分股 ...", flush=True)
    idx = fetch_index_constituents()
    print(f"  -> 拿到 {len(idx)} 只 (沪深300 ∪ 中证500)", flush=True)

    print("[2/5] 同花顺热点 ...", flush=True)
    hot = ths_hot_reason("2026-09-04")
    print(f"  -> 拿到 {len(hot)} 只", flush=True)

    # 合并去重
    all_codes = set(idx.keys()) | set(hot)
    # 前缀过滤：60/00/30
    all_codes = sorted([c for c in all_codes
                       if c.startswith(("60","00","30"))])
    print(f"[3/5] 合并去重 + 前缀过滤: {len(all_codes)} 只", flush=True)

    # 限速分批（腾讯批量上限 ~80/请求）
    print("[4/5] 腾讯批量行情 ...", flush=True)
    quotes = {}
    for i in range(0, len(all_codes), 80):
        batch = all_codes[i:i+80]
        quotes.update(tencent_quote(batch))
        print(f"  ... {min(i+80, len(all_codes))}/{len(all_codes)}", flush=True)
        time.sleep(0.3)

    # 过滤流通市值 50-500 亿 + 非 ST + 流通>0
    def ok_quote(q):
        if q.get("float_mcap_yi", 0) < 50 or q.get("float_mcap_yi", 0) > 500:
            return False
        n = str(q.get("name", ""))
        if "ST" in n.upper() or "退" in n:
            return False
        return q.get("price", 0) > 0
    filtered = [c for c, q in quotes.items() if ok_quote(q)]
    print(f"  -> 流通市值过滤后: {len(filtered)} 只", flush=True)

    print("[5/5] baostock 上市日 + K 线 ...", flush=True)
    bs.login()
    try:
        rows = []
        for i, c in enumerate(filtered):
            try:
                ipo = bs_ipo_date(c)
                if ipo and len(ipo) >= 10:
                    from datetime import date as _d
                    try:
                        ipo_d = _d(int(ipo[:4]), int(ipo[5:7]), int(ipo[8:10]))
                        if (_d(2026,9,4) - ipo_d).days < 420:
                            continue
                    except Exception:
                        pass
                hist = bs_history(c, 250)
                if hist.empty or len(hist) < 130:
                    continue
                last = hist.iloc[-1]
                if pd.isna(last["ma120"]):
                    continue
                close60 = hist["close"].tail(60)
                close20 = hist["close"].tail(20)
                hi60 = close60.max(); lo60 = close60.min()
                hi20 = close20.max(); lo20 = close20.min()
                ret60 = (last["close"] / hist["close"].iloc[-60] - 1) * 100 if len(hist) >= 60 else 0
                dd20 = ((hi20 - close20.min()) / hi20) * 100 if hi20 > 0 else 0
                avg_turn_20 = hist["turn"].tail(20).mean() or 0
                avg_turn_60 = hist["turn"].tail(60).mean() or 1
                vol_ratio = avg_turn_20 / avg_turn_60 if avg_turn_60 else 0
                q = quotes.get(c, {})
                rows.append({
                    "代码": c,
                    "名称": q.get("name", ""),
                    "来源": "热点" if c in hot else "沪深300/中证500",
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
                print(f"  skip {c}: {type(e).__name__}: {str(e)[:60]}", flush=True)
                continue
            if (i+1) % 20 == 0:
                print(f"  ... {i+1}/{len(filtered)}", flush=True)
            time.sleep(0.2)
    finally:
        bs.logout()

    df = pd.DataFrame(rows)
    print(f"[done] {len(df)} 行候选池", flush=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    if not df.empty:
        print(f"  流通市值: min={df['流通市值亿'].min():.0f} max={df['流通市值亿'].max():.0f} median={df['流通市值亿'].median():.0f}", flush=True)
        print(f"  60日涨幅: min={df['60日涨幅%'].min():.1f} max={df['60日涨幅%'].max():.1f} median={df['60日涨幅%'].median():.1f}", flush=True)
        print(f"  MA 多头(MA20>MA60>MA120): {( (df['MA20']>df['MA60']) & (df['MA60']>df['MA120']) ).sum()} 只", flush=True)

if __name__ == "__main__":
    main()
