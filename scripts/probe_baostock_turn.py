"""探针：baostock 拿 12 只 9-3 截止换手率 + 腾讯拿 9-4 当日 turn。
验证：1) baostock 实测通不通；2) 当日 turn 能不能拼上。"""
import json
import sys
from pathlib import Path

CODES = [
    ("002014", "永新股份"), ("002120", "韵达股份"), ("002191", "劲嘉股份"),
    ("002216", "三全食品"), ("002332", "仙琚制药"), ("002603", "以岭药业"),
    ("002606", "大连电瓷"), ("002737", "葵花药业"), ("002901", "大博医疗"),
    ("600109", "国金证券"), ("600483", "福能股份"), ("603128", "华贸物流"),
]


def get_bs_turn_history(code: str, end_date: str = "2026-09-03"):
    """§6.5 baostock 估值历史 → 换手率序列（T+1 滞后，最多到 9-3）"""
    import baostock as bs
    bs_code = code[:2] in ("60", "68", "90") and f"sh.{code}" or f"sz.{code}"
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login fail: {lg.error_msg}")
    try:
        # 取近 250 个交易日，覆盖 chip_distribution 需要的窗口
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,close,turn,tradestatus",
            start_date="2024-01-01", end_date=end_date,
            frequency="d", adjustflag="3",
        )
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        df_data = rows
        fields = rs.fields
    finally:
        bs.logout()
    return df_data, fields


def get_tencent_turn(code: str):
    """§1.2 腾讯实时行情 → 当日 turn（9-4 收盘后跑就是 9-4 数据）"""
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
        "name": vals[1],
        "price": float(vals[3]),
        "last_close": float(vals[4]),
        "high": float(vals[33]),
        "low": float(vals[34]),
        "turnover_pct": float(vals[38]) if vals[38] else 0,
        "amount_wan": float(vals[37]),
    }


if __name__ == "__main__":
    print("=== 探针 1：腾讯实时 turn（9-4 当日）===")
    tencent_ok = 0
    for code, name in CODES[:3]:  # 先测 3 只
        try:
            q = get_tencent_turn(code)
            if q:
                print(f"  ✅ {code} {name}: price={q['price']} turn={q['turnover_pct']}% amt={q['amount_wan']}万")
                tencent_ok += 1
            else:
                print(f"  ❌ {code} {name}: 解析失败")
        except Exception as e:
            print(f"  ❌ {code} {name}: {e}")
    print(f"腾讯成功率: {tencent_ok}/3")

    print("\n=== 探针 2：baostock 换手率序列（9-3 截止）===")
    data, fields = get_bs_turn_history("002014")
    print(f"  002014 永新股份: {len(data)} 行，最后 3 行:")
    for row in data[-3:]:
        print(f"    {dict(zip(fields, row))}")
