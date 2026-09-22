#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公告速览 fetcher —— 主源东财公告 / 降级源巨潮 cninfo，永不抛异常。

用法:
    from fetch_announcements import fetch_announcements
    res = fetch_announcements("603319", days=30)

返回结构:
    {
      "announcements": [{"date", "title", "category", "sentiment", "url"}, ...],
      "count": int,
      "source": "eastmoney" | "cninfo",          # 实际命中的源
      "fetched_at": ISO8601 字符串,
    }
失败返回 {"error": str}。

自跑:
    bash scripts/run_in_venv.sh \
    analysis/fetch_announcements.py
"""

import json
import re
from datetime import datetime, timedelta

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ---- 源端点 ----
EM_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"          # 主源：东财
CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"    # 降级源：巨潮
CNINFO_ORGID_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"     # 巨潮 股票→orgId 官方映射表

# ---- 情绪关键词（标题匹配） ----
# 利空优先：如「终止回购」同时含 回购/终止，按利空处理。
NEGATIVE_KW = ("减持", "诉讼", "处罚", "商誉减值", "质押", "预亏", "终止", "问询", "违规")
POSITIVE_KW = ("中标", "回购", "增持", "业绩预增", "重大合同", "分红", "激励", "获批")

# 沪市指数白名单（000xxx 与深市个股同段，需白名单区分；仅巨潮 orgId 硬编码 fallback 用）
_SH_INDEX = {"000300", "000905", "000016", "000688", "000852", "000010"}

# 巨潮 股票→orgId 映射（模块级缓存，首次调用拉取一次，全程复用）
_CNINFO_ORGID_MAP = {}


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _norm_code(code: str) -> str:
    """归一化为纯 6 位数字代码（容忍 sh000001 / 000001.SH 等写法）。"""
    c = str(code).strip().lower()
    for suf in (".sh", ".sz", ".bj"):
        if c.endswith(suf):
            c = c[:-3]
    if c.startswith(("sh", "sz", "bj")):
        c = c[2:]
    if not re.fullmatch(r"\d{6}", c):
        raise ValueError(f"无法识别的股票代码: {code!r}")
    return c


def _cutoff(days: int):
    """days>0 → 近 N 日的起算日期 (YYYY-MM-DD)；days<=0 → 不过滤。"""
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        return None
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def _norm_date(v):
    """把源里的日期值统一成 YYYY-MM-DD（巨潮返回 Unix 毫秒整数，东财返回时间串）。"""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000).strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s[:10]


def _sentiment(title: str) -> str:
    """标题关键词 → 利好 / 利空 / 中性。"""
    t = title or ""
    if any(k in t for k in NEGATIVE_KW):
        return "利空"
    if any(k in t for k in POSITIVE_KW):
        return "利好"
    return "中性"


def _result(source: str, anns: list) -> dict:
    """按日期倒序（无日期的沉底）组装统一返回结构。"""
    anns = sorted(anns, key=lambda a: a.get("date") or "0000-00-00", reverse=True)
    return {
        "announcements": anns,
        "count": len(anns),
        "source": source,
        "fetched_at": datetime.now().astimezone().isoformat(),
    }


# ---------------------------------------------------------------------------
# 主源：东财公告（2026-09-06 实测结构：
#   data.list[] = {art_code, title, title_ch, notice_date("YYYY-MM-DD HH:MM:SS"),
#                  columns[{column_code, column_name}], codes[{stock_code}], ...}）
# 公告详情页惯例 URL：https://data.eastmoney.com/notices/detail/{code}/{art_code}.html
# ---------------------------------------------------------------------------
def _fetch_eastmoney(code: str, days: int) -> list:
    cutoff = _cutoff(days)
    out = []
    sess = requests.Session()
    page_index = 1
    while page_index <= 3:          # 每页 50 条，最多翻 3 页（150 条），窗口内已取完即提前停
        params = {
            "page_size": 50,
            "page_index": page_index,
            "ann_type": "A",
            "client_source": "web",
            "stock_list": code,
        }
        r = sess.get(EM_URL, params=params, headers={"User-Agent": UA}, timeout=20)
        r.raise_for_status()
        d = r.json()
        lst = ((d.get("data") or {}).get("list")) or []
        if not lst:
            break
        for item in lst:
            title = (item.get("title") or item.get("title_ch") or "").strip()
            date = _norm_date(item.get("notice_date"))
            if not title:
                continue
            if cutoff and (not date or date < cutoff):
                continue
            codes = item.get("codes") or []
            stk = next((x.get("stock_code") for x in codes
                        if x.get("stock_code") == code), None) or (codes[0].get("stock_code") if codes else code)
            columns = [c.get("column_name", "") for c in (item.get("columns") or [])]
            out.append({
                "date": date,
                "title": title,
                "category": "、".join(c for c in columns if c),
                "sentiment": _sentiment(title),
                "url": f"https://data.eastmoney.com/notices/detail/{stk}/{item.get('art_code', '')}.html",
            })
        # 列表按时间倒序：本页最后一条已落在窗口外 → 无需再翻页
        oldest = _norm_date((lst[-1] or {}).get("notice_date"))
        if not cutoff or not oldest or oldest < cutoff:
            break
        page_index += 1
    return out


# ---------------------------------------------------------------------------
# 降级源：巨潮 cninfo（改编自 SKILL.md §7.1，orgId 动态映射逻辑完整保留）
# ---------------------------------------------------------------------------
def _get_prefix(code: str) -> str:
    """6位代码 → 市场前缀（sh/sz/bj）。支持显式前缀/后缀透传（同 SKILL.md §市场前缀规则）。"""
    c = code.lower().strip()
    if c.endswith((".sh", ".sz", ".bj")):
        return c[-2:]
    if c.startswith(("sh", "sz", "bj")):
        return c[:2]
    if c.startswith("92"):                    # 北交所 2024-10 起新号段，必须先于 9x 判断
        return "bj"
    if c.startswith(("5", "6", "9")):         # 5x=沪ETF/LOF，6/9=沪个股
        return "sh"
    if c.startswith(("4", "8")):              # 4x/8x=北交所老号段
        return "bj"
    if c in _SH_INDEX:                        # 沪深300/上证50 等沪指数（000xxx）
        return "sh"
    return "sz"


def _cninfo_orgid(code: str) -> str:
    """查股票真实 orgId。巨潮 orgId 并非统一 `gssx0{code}` 格式（如 601318→9900002221、
    601398→jjxt0000019、688017→9900041602），硬编码会导致大量股票（尤其 601xxx 段）
    返回 totalAnnouncement=0、查不到公告（SKILL.md #19）。优先动态查官方映射表，
    查不到再回退硬编码规则。"""
    global _CNINFO_ORGID_MAP
    if not _CNINFO_ORGID_MAP:
        try:
            r = requests.get(CNINFO_ORGID_URL, headers={"User-Agent": UA}, timeout=20)
            r.raise_for_status()
            _CNINFO_ORGID_MAP = {s["code"]: s["orgId"]
                                 for s in r.json().get("stockList", [])}
        except Exception:
            pass    # 映射表拉取失败 → 走下方硬编码 fallback（仅部分老股票适用）
    org = _CNINFO_ORGID_MAP.get(code)
    if org:
        return org
    return f"gs{_get_prefix(code)}0{code}"


def _fetch_cninfo(code: str, days: int) -> list:
    """巨潮公告全文检索。返回 [{date, title, category, sentiment, url}]。"""
    org_id = _cninfo_orgid(code)          # 动态查真实 orgId（自带硬编码 fallback）
    payload = {
        "stock": f"{code},{org_id}",
        "tabName": "fulltext",
        "pageSize": "50",
        "pageNum": "1",
        "column": "",
        "category": "",
        "plate": "",
        "seDate": "",
        "searchkey": "",
        "secid": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.cninfo.com.cn/new/disclosure",
        "Origin": "https://www.cninfo.com.cn",
    }
    r = requests.post(CNINFO_QUERY_URL, data=payload, headers=headers, timeout=20)
    r.raise_for_status()
    d = r.json()

    cutoff = _cutoff(days)
    out = []
    for item in d.get("announcements") or []:
        title = (item.get("announcementTitle") or "").strip()
        date = _norm_date(item.get("announcementTime"))
        if not title:
            continue
        if cutoff and (not date or date < cutoff):
            continue
        out.append({
            "date": date,
            "title": title,
            "category": (item.get("announcementTypeName") or "").strip(),
            "sentiment": _sentiment(title),
            "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}",
        })
    return out


# ---------------------------------------------------------------------------
# 对外入口：主源失败自动降级，永不抛异常
# ---------------------------------------------------------------------------
def fetch_announcements(code: str, days: int = 30) -> dict:
    try:
        code = _norm_code(code)
    except Exception as e:
        return {"error": f"非法股票代码: {e}"}

    hard_errors = []
    last_ok = None
    for source, fn in (("eastmoney", _fetch_eastmoney), ("cninfo", _fetch_cninfo)):
        try:
            anns = fn(code, days)
        except Exception as e:
            hard_errors.append(f"{source}: {e}")
            continue
        last_ok = source
        if anns:
            return _result(source, anns)
    if last_ok:
        return _result(last_ok, [])   # 有源成功返回但窗口内无公告
    return {"error": " / ".join(hard_errors) or "未知错误"}


if __name__ == "__main__":
    result = fetch_announcements("603319")
    print(json.dumps(result, ensure_ascii=False, indent=2))
