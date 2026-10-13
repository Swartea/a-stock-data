"""股票池过滤 V3：用东财 clist 拉全 A 清单 + 流通市值过滤 + baostock K 线。
避免 push2 hisdata 风控（已知 push2 在沙盒外也是 502），用 list 接口不同字段。
"""
import sys
import time
from pathlib import Path

import baostock as bs
import pandas as pd
import requests

OUT = Path(__file__).parent / "screener_pool.csv"

def fetch_all_a_share():
    """东财 clist 全 A 清单分页拉（pn=页码, pz=每页）。
    fields: f12=代码 f14=名称 f20=总市值 f9=市盈率(动) f21=流通市值 f3=涨幅
    """
    out = []
    for pn in range(1, 30):
        url = "https://80.push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": str(pn), "pz": "200", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            # m:0+t:6=深A, m:0+t:13=深B, m:0+t:80=深创业, m:1+t:2=沪A, m:1+t:23=沪B
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f20,f21,f9",
            "_": "1",
        }
        try:
            r = requests.get(url, params=params, timeout=15,
                headers={"User-Agent":"Mozilla/5.0","Referer":"https://quote.eastmoney.com/"})
            data = r.json().get("data", {})
            items = data.get("diff", [])
            if not items:
                break
            for it in items:
                code = str(it.get("f12","")).zfill(6)
                if not code.startswith(("60","00","30","20")):
                    continue
                out.append({
                    "代码": code,
                    "名称": it.get("f14",""),
                    "总市值亿": round(it.get("f20",0)/1e8, 2) if it.get("f20") else 0,
                    "流通市值亿": round(it.get("f21",0)/1e8, 2) if it.get("f21") else 0,
                    "PE": it.get("f9",0),
                })
        except Exception as e:
            print(f"  page {pn} err: {e}", flush=True)
            break
        if pn % 5 == 0:
            print(f"  ... page {pn}, {len(out)} 只累计", flush=True)
        time.sleep(0.4)
    return out

def bs_code_of(code: str) -> str:
    if code.startswith(("4","8","92","920")):
        raise ValueError(f"bs 不支持 {code}")
    if code.startswith(("5","6","9")) or code.startswith("000"):
        return f"sh.{code}"
    return f"sz.{code}"

def bs_ipo_date(code: str) -> str:
    bs_code = bs_code_of(code)
    rs = bs.query_stock_basic(code=bs_code)
    if rs.error_code != "0":
        return ""
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return ""
    df = pd.DataFrame(rows, columns=rs.fields)
    return str(df.iloc[0].get("ipoDate", "") or "")

def bs_history(code: str, days: int = 250) -> pd.DataFrame:
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
    print("[1/4] 东财 clist 全 A 清单 ...", flush=True)
    all_a = fetch_all_a_share()
    print(f"  -> 共 {len(all_a)} 只 (沪深主板+创业板)", flush=True)
    if not all_a:
        print("EMPTY"); return
    df_a = pd.DataFrame(all_a)
    # 流通 50-500 亿 + 非 ST + 价格>0
    df_a = df_a[
        (df_a["流通市值亿"] >= 50) & (df_a["流通市值亿"] <= 500) &
        (~df_a["名称"].str.contains("ST|退", na=False, regex=True))
    ].reset_index(drop=True)
    print(f"  -> 流通 50-500 亿过滤后: {len(df_a)} 只", flush=True)
    # 取现价（腾讯批量）
    codes = list(df_a["代码"])
    print(f"[2/4] 腾讯批量行情 {len(codes)} 只 ...", flush=True)
    SH_INDEX = {"000300","000905","000016","000688","000852","000010"}
    quotes = {}
    for i in range(0, len(codes), 80):
        batch = codes[i:i+80]
        prefixed, key_of = [], {}
        for c in batch:
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
        try:
            req = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=15)
            data = req.content.decode("gbk", errors="ignore")
            for line in data.strip().split(";"):
                if '"' not in line or "=" not in line:
                    continue
                key = line.split("=")[0].split("_")[-1]
                vals = line.split('"')[1].split("~")
                if len(vals) < 53: continue
                code = key_of.get(key, key[2:])
                try:
                    quotes[code] = {
                        "price": float(vals[3]) if vals[3] else 0,
                        "change_pct": float(vals[32]) if vals[32] else 0,
                        "amount_wan": float(vals[37]) if vals[37] else 0,
                        "turnover_pct": float(vals[38]) if vals[38] else 0,
                        "pe_ttm": float(vals[39]) if vals[39] else 0,
                        "pb": float(vals[46]) if vals[46] else 0,
                        "vol_ratio": float(vals[49]) if vals[49] else 0,
                    }
                except Exception:
                    continue
        except Exception as e:
            print(f"  batch {i} err: {e}", flush=True)
        if (i // 80) % 3 == 0:
            print(f"  ... {min(i+80,len(codes))}/{len(codes)}", flush=True)
        time.sleep(0.3)
    # 过滤仍在交易 + 现价>0
    valid = [c for c in codes if quotes.get(c,{}).get("price",0) > 0
             and quotes.get(c,{}).get("amount_wan",0) > 1000]
    print(f"  -> 活跃过滤: {len(valid)} 只 (成交额>1000万)", flush=True)

    print(f"[3/4] baostock 上市日 + 250 日 K 线 ({len(valid)} 只) ...", flush=True)
    bs.login()
    try:
        rows = []
        for i, c in enumerate(valid):
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
                name = df_a.loc[df_a["代码"]==c, "名称"].iloc[0] if not df_a[df_a["代码"]==c].empty else ""
                rows.append({
                    "代码": c,
                    "名称": name,
                    "现价": q.get("price", last["close"]),
                    "今日涨幅%": q.get("change_pct", 0),
                    "流通市值亿": df_a.loc[df_a["代码"]==c, "流通市值亿"].iloc[0] if not df_a[df_a["代码"]==c].empty else 0,
                    "PE_TTM": q.get("pe_ttm", 0),
                    "PB": q.get("pb", 0),
                    "量比": q.get("vol_ratio", 0),
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
            if (i+1) % 30 == 0:
                print(f"  ... {i+1}/{len(valid)}", flush=True)
            time.sleep(0.15)
    finally:
        bs.logout()

    df = pd.DataFrame(rows)
    print(f"[4/4] 写 CSV: {len(df)} 行候选池", flush=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    if not df.empty:
        print(f"  流通市值: min={df['流通市值亿'].min():.0f} max={df['流通市值亿'].max():.0f} median={df['流通市值亿'].median():.0f}", flush=True)
        print(f"  60日涨幅: min={df['60日涨幅%'].min():.1f} max={df['60日涨幅%'].max():.1f} median={df['60日涨幅%'].median():.1f}", flush=True)
        print(f"  MA 多头(MA20>MA60>MA120): {((df['MA20']>df['MA60']) & (df['MA60']>df['MA120'])).sum()} 只", flush=True)
        print(f"  MA 空头(MA20<MA60<MA120): {((df['MA20']<df['MA60']) & (df['MA60']<df['MA120'])).sum()} 只", flush=True)

if __name__ == "__main__":
    main()
