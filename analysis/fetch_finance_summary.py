#!/usr/bin/env python3
"""
财务体检 fetcher：东财 datacenter 主要财务指标 (RPT_F10_FINANCE_MAINFINADATA)
============================================================================

契约: fetch_finance_summary.fetch_finance_summary(code) -> dict
  - 永不抛异常，失败返回 {"error": str}
  - 成功返回:
      {
        "reports": [按报告期倒序的 4-8 期],      # 每期字段见 _ONE_PERIOD 注释
        "latest":  {最新一期},
        "source": "datacenter RPT_F10_FINANCE_MAINFINADATA",
        "fetched_at": ISO8601 字符串,
      }

口径说明 (以实测数据校验):
  - TOTALOPERATEREVE / PARENTNETPROFIT 单位=元，年度内为累计值 (Q1<中报<Q3<年报 单调递增)。
  - 同比 = 累计值 vs 上年同期累计 (与东财内置 TOTALOPERATEREVETZ/PARENTNETPROFITTZ 字段
    逐项核对一致，如 603319 2025 年报营收同比 13.54%、净利同比 -35.82%)。
  - 环比 = 单季值 vs 上一报告期单季值 (单季值 = 本年累计 - 本年内上一期累计；Q1 单季=本身)。
  - ROEJQ/XSMLL/ZCFZL 接口直接返回百分数 (如 2.22 = 2.22%)。

免责声明: 本工具仅供数据分析参考，不构成任何投资建议。
"""

import json
import re
import requests
from datetime import datetime, timedelta

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
EM_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_HEADERS = {"User-Agent": UA, "Referer": "https://emweb.securities.eastmoney.com/"}
EM_TIMEOUT = 15


def _secucode(code: str) -> str:
    """6位数字 → SECUCODE：6开头 .SH，0/3 开头 .SZ，8/4/9 开头 .BJ。"""
    c = re.sub(r"\.\w+$", "", str(code).strip())
    if not re.fullmatch(r"\d{6}", c):
        raise ValueError(f"无法识别的股票代码: {code}")
    if c[0] == "6":
        return c + ".SH"
    if c[0] in ("0", "3"):
        return c + ".SZ"
    if c[0] in ("4", "8", "9"):
        return c + ".BJ"
    raise ValueError(f"无法识别的股票代码: {code}")


def _num(v):
    """容错转 float：空/'-'/'--'/None → None。"""
    if v is None or isinstance(v, str) and v.strip() in ("", "-", "--", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _period_date(row) -> str:
    """REPORT_DATE '2026-06-30 00:00:00' → '2026-06-30'。"""
    return str(row.get("REPORT_DATE", ""))[:10]


def _pct_growth(cur, base) -> float:
    """(cur-base)/base*100；任一为 None 或 base<=0 → None。"""
    if cur is None or base is None or base <= 0:
        return None
    return round((cur - base) / base * 100.0, 2)


def fetch_finance_summary(code: str) -> dict:
    """东财主要财务指标 → 报告期列表 + 最新一期（同比/环比自行计算）。永不抛异常。"""
    try:
        params = {
            "reportName": "RPT_F10_FINANCE_MAINFINADATA",
            "columns": "ALL",
            "filter": f'(SECUCODE="{_secucode(code)}")',
            "pageNumber": "1",
            "pageSize": "8",
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
        }
        r = requests.get(EM_URL, params=params, headers=EM_HEADERS, timeout=EM_TIMEOUT)
        r.raise_for_status()
        rows = (r.json().get("result") or {}).get("data") or []
        if not rows:
            return {"error": f"{code} 无财务数据"}

        # 去重（同 REPORT_DATE 只留一条）并按报告期倒序
        seen, raw = set(), []
        for row in rows:
            d = _period_date(row)
            if d and d not in seen:
                seen.add(d)
                raw.append(row)
        raw.sort(key=lambda x: _period_date(x), reverse=True)

        # 每期解析；内部保留累计原值 (cum_rev/cum_profit) 供同比/环比计算
        periods = []
        for row in raw:
            rev_yuan = _num(row.get("TOTALOPERATEREVE"))
            profit_yuan = _num(row.get("PARENTNETPROFIT"))
            eps = _num(row.get("EPSJB"))
            roe = _num(row.get("ROEJQ"))
            gm = _num(row.get("XSMLL"))
            debt = _num(row.get("ZCFZL"))
            periods.append({
                "report_date": _period_date(row),
                "eps": round(eps, 4) if eps is not None else None,
                "revenue_yi": round(rev_yuan / 1e8, 2) if rev_yuan is not None else None,
                "profit_yi": round(profit_yuan / 1e8, 2) if profit_yuan is not None else None,
                "roe": round(roe, 2) if roe is not None else None,
                "gross_margin": round(gm, 2) if gm is not None else None,
                "debt_ratio": round(debt, 2) if debt is not None else None,
                "_cum_rev": rev_yuan, "_cum_profit": profit_yuan,
                "yoy_revenue": None, "yoy_profit": None,
                "qoq_revenue": None, "qoq_profit": None,
            })

        # --- 同比：累计 vs 上年同期（同日-月，年份-1）---
        by_md = {}
        for p in periods:
            by_md.setdefault(p["report_date"][5:], []).append(p)
        for p in periods:
            y, md = int(p["report_date"][:4]), p["report_date"][5:]
            for q in by_md.get(md, []):
                if q["report_date"].startswith(str(y - 1)):
                    p["yoy_revenue"] = _pct_growth(p["_cum_rev"], q["_cum_rev"])
                    p["yoy_profit"] = _pct_growth(p["_cum_profit"], q["_cum_profit"])
                    break

        # --- 环比：单季值 vs 上一报告期单季值 ---
        # 单季值 = 本报告期累计 - 本年内上一报告期累计；Q1 无本年内上期则单季 = 累计本身
        def _to_single(plist, idx):
            """idx 期 (倒序列表) 的单季营收/净利值 → (rev, profit)。
            无本年内上一期累计可减：Q1 单季=累计本身；其余 (如窗口最老的三季报)
            单季值不可得 → (None, None)。"""
            p = plist[idx]
            for q in plist[idx + 1:]:
                if q["report_date"][:4] == p["report_date"][:4]:
                    rev = (p["_cum_rev"] - q["_cum_rev"]
                           if p["_cum_rev"] is not None and q["_cum_rev"] is not None else None)
                    profit = (p["_cum_profit"] - q["_cum_profit"]
                              if p["_cum_profit"] is not None and q["_cum_profit"] is not None else None)
                    return (rev, profit)
            if p["report_date"].endswith("-03-31"):
                return (p["_cum_rev"], p["_cum_profit"])
            return (None, None)

        for i, p in enumerate(periods[:-1]):  # 最老一期无环比基础
            cur_sp = _to_single(periods, i)
            prev_sp = _to_single(periods, i + 1)
            p["qoq_revenue"] = _pct_growth(cur_sp[0], prev_sp[0])
            p["qoq_profit"] = _pct_growth(cur_sp[1], prev_sp[1])

        # 剔除内部字段，latest = 倒序第一
        reports = [{k: v for k, v in p.items() if not k.startswith("_")} for p in periods]
        latest = dict(reports[0]) if reports else None
        return {
            "reports": reports,
            "latest": latest,
            "source": "datacenter RPT_F10_FINANCE_MAINFINADATA",
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    except Exception as e:
        return {"error": f"{code} 财务数据抓取失败: {e}"}


if __name__ == "__main__":
    import time
    t0 = time.time()
    result = fetch_finance_summary("603319")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n# 耗时: {time.time() - t0:.2f}s", file=__import__("sys").stderr)
