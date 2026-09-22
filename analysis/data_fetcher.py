"""analysis/ 数据采集层 — V3 内部 fetcher 集中 (P2-A Phase 4, 2026-09-13)

按规范 §2 模块边界 + §4 数据契约, 把 V3 主文件 3 个内部 fetcher 抽到 data_fetcher.py:
- fetch_fund_flow_daily(code, days): 资金面-5日主力 (东财 push2his fflow daykline)
- fetch_margin_history(code, n): 两融历史 (东财 datacenter RPTA_WEB_RZRQ_GGMX)
- fetch_concept_peers(code, blocks, max_concepts): 同业对比 (东财 clist f37+f105)
- fetch_news_em_via_import(): 4 独立 fetcher 之一, 软导入 (V3 已经有)

§1 '不修改业务口径' — 函数体照搬 v3, 仅搬位置; 端点 / 字段 / 错误处理不动。
§4 状态: 仍返回老 ad-hoc {"error": str, "rows": []} / 字典, 由 fetcher_contract.from_legacy
   适配为标准 status 契约 (P0-B 整改)。

向后兼容: v3 顶层 `from analysis.data_fetcher import _fetch_fund_flow_daily, ...`,
          老 `from analysis.quant_analyzer_v3 import _fetch_fund_flow_daily` 仍能拿到 (re-export)。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List

import analysis.quant_analyzer_v2 as v2
from analysis.utils import num_or_none


# ============================================================
# 资金面-5日主力 (东财 push2his fflow daykline)
# ============================================================
def fetch_fund_flow_daily(code: str, days: int = 5) -> Dict[str, Any]:
    """近 N 日主力资金 (东财 push2 fflow kline, klt=101 日线 — 与 v2 分钟线同源)。

    返回每行字段: date / main_net_yi / large_super_yi / close / chg_pct
    债 6 修法 (Task 7.3): 资金面 5 行大表 5 列 — 主力/大单+超大单/融资余额变化/股价/当日涨跌幅
    重试 3 次 (Task 7.3 稳定性): push2his 易遇 SSL EOF/网络抖动, 指数退避 0.6/1.2/2.4s
    """
    code = v2.normalize_code(code)
    secid = f"{v2.em_market_code(code)}.{code}"
    params = {"secid": secid, "klt": 101, "lmt": days,
              "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57,f12"}
    headers = {"User-Agent": v2.UA, "Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    last_err = None
    for attempt in range(3):
        try:
            d = v2.em_get("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                          params=params, headers=headers, timeout=15).json()
            if d.get("data") and (d["data"].get("klines") or []):
                break  # 拿到数据, 跳出重试
        except Exception as e:  # noqa: BLE001
            last_err = e
        if attempt < 2:
            time.sleep(0.6 * (2 ** attempt))  # 0.6s, 1.2s
    else:
        return {"error": str(last_err) if last_err else "push2his fetch failed after 3 retries",
                "rows": []}
    rows = []
    for line in (d.get("data") or {}).get("klines") or []:
        p = line.split(",")
        if len(p) >= 7:
            # 兼容老格式 (len=7) 与新加 f57/f12 (len=9)
            row = {
                "date": str(p[0])[:10],
                "main_net_yi": round(float(p[1]) / 1e8, 3),
                "large_super_yi": round((float(p[4]) + float(p[5])) / 1e8, 3),
            }
            if len(p) >= 8:
                # f57 = 收盘价 (元), 兼容 None/空字符串
                try:
                    row["close"] = float(p[7]) if p[7] not in ("", "None", "null") else None
                except (TypeError, ValueError):
                    row["close"] = None
            rows.append(row)
    if not rows:
        return {"error": "近5日主力资金无数据", "rows": []}
    # 计算每日涨跌幅 (基于 close 序列, 错位一日)
    closes = [r.get("close") for r in rows]
    for i, r in enumerate(rows):
        if i + 1 < len(closes) and closes[i + 1] and r.get("close"):
            r["chg_pct"] = round((r["close"] - closes[i + 1]) / closes[i + 1] * 100, 2)
        else:
            r["chg_pct"] = None
    return {"rows": rows, "total_main_yi": round(sum(r["main_net_yi"] for r in rows), 3),
            "start": rows[0]["date"], "end": rows[-1]["date"],
            "as_of": datetime.now().strftime("%Y-%m-%d")}


# 别名
def _fetch_fund_flow_daily(code: str, days: int = 5) -> Dict[str, Any]:
    return fetch_fund_flow_daily(code, days)


# ============================================================
# 两融历史 (东财 datacenter RPTA_WEB_RZRQ_GGMX)
# ============================================================
def fetch_margin_history(code: str, n: int = 8) -> Dict[str, Any]:
    """两融余额近 n 期 (东财 datacenter — 与 v2.fetch_margin_trading 同源同接口)。"""
    params = {
        "reportName": "RPTA_WEB_RZRQ_GGMX", "columns": "ALL",
        "filter": f'(SCODE="{code}")', "pageNumber": "1", "pageSize": str(n),
        "sortColumns": "DATE", "sortTypes": "-1",
    }
    try:
        d = v2.em_get("https://datacenter-web.eastmoney.com/api/data/v1/get",
                      params=params, headers={"User-Agent": v2.UA,
                          "Referer": "https://data.eastmoney.com/"}, timeout=15).json()
        rows = (d.get("result") or {}).get("data") or []
        out = []
        for r in rows[:n]:
            out.append({
                "date": str(r.get("DATE", ""))[:10],
                "rzye_yi": round(float(r.get("RZYE", 0) or 0) / 1e8, 3),
                "rqye_yi": round(float(r.get("RQYE", 0) or 0) / 1e8, 3),
                "rzmr_yi": round(float(r.get("RZMRE", 0) or 0) / 1e8, 3),
                "rzch_yi": round(float(r.get("RZCHE", 0) or 0) / 1e8, 3),
            })
        if not out:
            return {"error": "两融历史无数据", "rows": []}
        # 方向: 融资余额较前一期增减
        for i, row in enumerate(out):
            if i + 1 < len(out):
                row["rzye_chg_yi"] = round(row["rzye_yi"] - out[i + 1]["rzye_yi"], 3)
            else:
                row["rzye_chg_yi"] = None
        return {"rows": out, "as_of": datetime.now().strftime("%Y-%m-%d")}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "rows": []}


# 别名
def _fetch_margin_history(code: str, n: int = 8) -> Dict[str, Any]:
    return fetch_margin_history(code, n)


# ============================================================
# 同业对比 (东财 clist f37+f105)
# ============================================================
def fetch_concept_peers(code: str, blocks: List[Dict], max_concepts: int = 6) -> Dict[str, Any]:
    """同业对比(近似口径): 取本票所属东财概念板块的市值前100, 标出本票市值排名。
    数据源: 东财 push2 clist (与 v2 行业排名同端点家族)。

    债 6 修法 (Task 7.3): 7 维表 — 补 ROE (f37) + 5 日涨跌 (f105), 营收增速东财 clist 行情接口
    无标准字段, 标 None 显示 '—'。
    """
    code = v2.normalize_code(code)
    if not isinstance(blocks, list):
        return {"error": "无概念板块数据(概念归属缺失), 无法取成分股做同业对比"}
    concepts = [b for b in blocks if isinstance(b, dict) and b.get("code") and "error" not in b]
    if not concepts:
        return {"error": "概念板块列表为空(东财 slist 返回 0 条, 可能风控), 无法做同业对比"}
    tried = []
    for b in concepts[:max_concepts]:
        bcode = str(b.get("code", ""))
        params = {"pn": "1", "pz": "100", "po": "1", "np": "1", "fltt": "2", "invt": "2",
                  "fid": "f20", "fs": f"b:{bcode}",
                  # f12=code f14=name f2=price f3=chg% f9=PE f23=PB f20=total_mcap f21=float_mcap
                  # f37=ROE(%) f105=5日涨跌(%) — 营收增速 clist 行情接口无, 标 None
                  "fields": "f12,f14,f2,f3,f9,f23,f20,f21,f37,f105"}
        try:
            d = v2.em_get("https://push2.eastmoney.com/api/qt/clist/get",
                          params=params, headers={"User-Agent": v2.UA,
                              "Referer": "https://quote.eastmoney.com/"}, timeout=15).json()
            data = d.get("data") or {}
            diff = data.get("diff") or []
            total = int(data.get("total", 0) or 0)
            rows = []
            for it in diff:
                rows.append({
                    "code": str(it.get("f12", "")), "name": str(it.get("f14", "")),
                    "price": num_or_none(it.get("f2")), "chg": num_or_none(it.get("f3")),
                    "pe": num_or_none(it.get("f9")), "pb": num_or_none(it.get("f23")),
                    "total_mcap_yi": num_or_none(it.get("f20")),
                    "float_mcap_yi": num_or_none(it.get("f21")),
                    "roe_pct": num_or_none(it.get("f37")),
                    "chg_5d_pct": num_or_none(it.get("f105")),
                    "rev_growth_pct": None,  # 东财 clist 行情接口无, 独立 fetcher 待立
                })
            rank = next((i + 1 for i, r in enumerate(rows) if r["code"] == code), None)
            tried.append({"concept": b.get("name"), "code": bcode, "total": total,
                          "fetched": len(rows), "rank": rank})
            if rank is not None:
                return {"block_used": b.get("name"), "block_code": bcode,
                        "total": total, "rank": rank,
                        "rows": rows, "as_of": datetime.now().strftime("%Y-%m-%d")}
        except Exception as e:  # noqa: BLE001
            tried.append({"concept": b.get("name"), "code": bcode, "error": str(e)})
    # 全部未命中/失败 → 用第一概念的前列作参考 + 说明
    fallback = {"error": "本票未进入所查概念的市值前100或接口失败",
                "tried": tried, "rows": None}
    return fallback


# 别名
def _fetch_concept_peers(code: str, blocks: list, max_concepts: int = 6) -> Dict[str, Any]:
    return fetch_concept_peers(code, blocks, max_concepts)
