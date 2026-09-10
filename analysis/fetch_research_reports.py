#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_research_reports.py — 研报观点汇总 fetcher

主源：东财研报 reportapi.eastmoney.com/report/list（个股研报 qType=0，
     code 传纯 6 位，如 603319；用 beginTime/endTime 限定近 N 天窗口）
降级：同花顺 basic.10jqka.com.cn/{code}/worth.html（研报评级/盈利预测，
     requests + 正则解析，GBK 页面）
     东财降级后的取数逻辑：东财窗口内 0 篇或请求失败 → 转同花顺；
     同花顺窗口内有数据 → source="ths"；两源都无窗口数据 → 返回
     东财的 0 篇结果（count=0，这是真实答案而非错误）。

对外 API：
    fetch_research_reports(code: str, days: int = 90) -> dict
    永不抛异常；全部源请求级失败时返回 {"error": str, ...}。

返回结构：
    {
      "reports": [{"date", "org", "title", "rating", "target_price"}, ...最新5篇],
      "rating_dist": {"买入": n, "增持": n, ...},   # 窗口内评级计数
      "count": int,                                  # 窗口内研报总数
      "source": "eastmoney" | "ths",                 # 实际使用的数据源
      "fetched_at": ISO8601 字符串
    }
    target_price 只从 predictNextYearEps 数值字段或标题/正文「目标价 xx」提取，
    提取不到为 None —— 绝不编造。

实测（2026-09-06）：603319 东财全部研报仅 9 篇、最新 2025-12-08（山西证券/增持），
近 90 日窗口内 0 篇属真实无覆盖；同花顺 worth.html 另有 2026-04-25 国盛证券/买入
等研报评级（东财库里没有），窗口拉长时作为降级补充。

自测：bash scripts/run_in_venv.sh analysis/fetch_research_reports.py 603319 200
"""
import html as _html
import json
import random
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Optional

import requests

REPORT_API = "https://reportapi.eastmoney.com/report/list"
THS_URL_TPL = "https://basic.10jqka.com.cn/{code}/worth.html"
THS_URL_NEW_TPL = "https://basic.10jqka.com.cn/new/{code}/worth.html"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 评级词表（长词在前，先匹配更具体词）
RATING_WORDS = ("强烈推荐", "审慎推荐", "谨慎推荐", "增持", "推荐",
                "优于大市", "跑赢行业", "买入", "持有", "中性",
                "减持", "回避", "卖出")
_RATING_RE = re.compile("|".join(sorted(RATING_WORDS, key=len, reverse=True)))
_DATE_RE = re.compile(r"(20\d{2})[年/.\-](\d{1,2})[月/.\-](\d{1,2})日?")
_TP_RE = re.compile(r"目标价[约为]?\s*[：:]?\s*([\d.]+)")
_CODE_RE = re.compile(
    r"^(?:(sh|sz|bj)(\d{6})|(\d{6})(?:\.(?:sh|sz|bj))?)$", re.IGNORECASE)


# ────────────────────────────── 工具函数 ──────────────────────────────

def _normalize_code(code: str) -> str:
    """任意写法 → 纯 6 位（reportapi 只认纯 6 位，如 SH603319 → 603319）。"""
    m = _CODE_RE.match(str(code).strip())
    if not m:
        raise ValueError(
            f"无法解析股票代码 {code!r}：支持 603319 / SH603319 / 603319.SH")
    return m.group(2) or m.group(3)


def _fmt_date(value) -> str:
    """publishDate 等 → YYYY-MM-DD（容忍时间戳/ISO/中文日期写法）。"""
    if not value:
        return ""
    s = str(value).strip()
    m = _DATE_RE.search(s)
    if m:
        return "%04d-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return s[:10] if len(s) >= 10 and s[:4].isdigit() else ""


def _parse_float(value) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ("-", "--", "None", "nan", "N/A", "暂无"):
        return None
    try:
        return round(float(re.sub(r"[^\d.]", "", s)), 2)
    except (TypeError, ValueError):
        return None


def _strip_tags_find(word: str, text: str) -> str:
    """去掉 HTML 标签/空白后，在 text 中找评级词（兼容 买&nbsp;入 / 买　　入）。"""
    plain = _html.unescape(re.sub(r"<[^>]+>", "", text))
    plain = re.sub(r"\s+", "", plain)
    m = _RATING_RE.search(plain)
    return m.group(0) if m else (word if word in plain else "")


def _rating_of(rec: dict) -> str:
    """东财 record → 评级文本（emRatingName 优先，退化 sRatingName）。"""
    for key in ("emRatingName", "sRatingName", "ratingName"):
        v = rec.get(key)
        if v and str(v).strip() and str(v).strip().lower() not in ("-", "none"):
            return str(v).strip()
    return ""


def _extract_target_price(rec: dict, row_text: str = "") -> Optional[float]:
    """目标价提取：优先 predictNextYearEps 数值字段，其次标题/行文
    「目标价 xx」。提取不到返回 None —— 不许编造。"""
    for key in ("predictNextYearEps", "predictNextTwoYearEps", "predictThisYearEps"):
        v = _parse_float(rec.get(key))
        if v is not None:
            return v
    for text in (rec.get("title") or "", row_text):
        m = _TP_RE.search(text)
        if m:
            v = _parse_float(m.group(1))
            if v is not None:
                return v
    return None


def _build_result(items: list, days: int, source: str, fetched_at: str) -> dict:
    """items（可含窗口外行）→ 按近 days 日窗口聚合：评级分布 + 最新 5 篇。"""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    recent = [it for it in items if it.get("date") and it["date"] >= cutoff]
    recent.sort(key=lambda x: x.get("date", ""), reverse=True)
    rating_cnt = Counter()
    for it in recent:
        r = (it.get("rating") or "").strip()
        if r:
            rating_cnt[r] += 1
    return {
        "reports": recent[:5],
        "rating_dist": dict(rating_cnt),
        "count": len(recent),
        "source": source,
        "fetched_at": fetched_at,
    }


# ────────────────────────────── 主源：东财 ──────────────────────────────

def _fetch_eastmoney(code: str, days: int, fetched_at: str) -> dict:
    """东财 reportapi 个股研报（qType=0，纯 6 位 code，时间窗）。
    健康响应一律返回 dict（窗口内 0 篇也返回 count=0 的 dict）；
    仅请求/解析级失败才抛异常（由上层决定降级）。"""
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    begin = date.today() - timedelta(days=days)
    end = date.today() + timedelta(days=1)              # 容错当日发布
    records = []
    for page in range(1, 4):                            # 时间窗内一页即够，防御翻页
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin.isoformat(), "endTime": end.isoformat(),
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        r = sess.get(REPORT_API, params=params,
                     headers={"Referer": "https://data.eastmoney.com/"},
                     timeout=30)
        r.raise_for_status()
        d = r.json()
        rows = d.get("data") or []
        if not rows:
            break
        records.extend(rows)
        try:
            total_page = int(d.get("TotalPage") or 1)
        except (TypeError, ValueError):
            total_page = 1
        if page >= total_page or len(records) >= 300:
            break
        time.sleep(random.uniform(0.5, 1.0))            # 东财限流：翻页间歇

    items = []
    for rec in records:
        items.append({
            "date": _fmt_date(rec.get("publishDate")),
            "org": rec.get("orgSName") or "",
            "title": rec.get("title") or "",
            "rating": _rating_of(rec),
            "target_price": _extract_target_price(rec),
        })
    return _build_result(items, days, "eastmoney", fetched_at)


# ────────────────────────────── 降级源：同花顺 ──────────────────────────────

def _ths_dl_items(html_text: str) -> list:
    """同花顺 worth.html 研报评级区是 <dl class="hover"> 结构：
        <span class="subtitle">买　　入</span>
        <span class="title">国盛证券：研报标题</span>
        <span class="date">2026-04-25</span>
        <dd>摘要…（含「目标价 xx」时才填 target_price）</dd>
    实测（2026-09-06）东财库里没有的研报（如国盛证券 2026-04-25 买入）会出现在这里。"""
    out = []
    for dl in re.findall(r'<dl[^>]*class="[^"]*hover[^"]*"[^>]*>(.*?)</dl>',
                         html_text, re.S):
        m_sub = re.search(r'<span class="subtitle">(.*?)</span>', dl, re.S)
        m_title = re.search(r'<span class="title">(.*?)</span>', dl, re.S)
        m_date = re.search(r'<span class="date">(.*?)</span>', dl, re.S)
        if not (m_sub and m_title and m_date):
            continue
        rating = _strip_tags_find("", m_sub.group(1))
        if not rating:
            continue                                    # 非评级条目
        title = re.sub(r"\s+", " ", _html.unescape(
            re.sub(r"<[^>]+>", "", m_title.group(1)))).strip()
        date_s = _fmt_date(_html.unescape(
            re.sub(r"<[^>]+>", "", m_date.group(1))))
        if not date_s:
            continue
        # 机构名：标题首段「机构：」或「机构:」
        org = ""
        for sep in ("：", ":"):
            head = title.split(sep)[0].strip()
            if 2 <= len(head) <= 24 and not _DATE_RE.search(head) \
                    and not _RATING_RE.search(head):
                org = head
                break
        # target_price：仅当 dd 摘要出现「目标价」表述
        target_price = None
        dd = dl.split("</dt>", 1)
        if len(dd) == 2:
            dd_plain = re.sub(r"\s+", "", _html.unescape(
                re.sub(r"<[^>]+>", "", dd[1])))
            if "目标价" in dd_plain:
                m = _TP_RE.search(dd_plain)
                if m:
                    target_price = _parse_float(m.group(1))
        out.append({"date": date_s, "org": org, "title": title,
                    "rating": rating, "target_price": target_price})
    return out


def _ths_table_rows(html_text: str) -> list:
    """通用后备：<tr> 行内同时含日期 + 评级词（旧版式机构评级表）。"""
    out = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S):
        cells = []
        for td in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S):
            t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", td)).strip()
            if t:
                cells.append(t)
        date_s = rating = org = ""
        for c in cells:
            if not date_s:
                date_s = _fmt_date(c)
            if not rating and not _DATE_RE.search(c) and len(c) <= 12:
                rating = _strip_tags_find("", c)
        if not (date_s and rating):
            continue
        for c in cells:
            if c in (date_s, rating) or _DATE_RE.search(c):
                continue
            if not org and _RATING_RE.search(c) is None \
                    and re.fullmatch(r"[\d.,%+()（）\-\s]+", c) is None \
                    and len(c) <= 30:
                org = c
        joined = "|".join(cells)
        out.append({"date": date_s, "org": org, "title": "",
                    "rating": rating,
                    "target_price": _extract_target_price({}, joined)})
    return out


def _parse_ths(html_text: str) -> list:
    """两种版式都试：新版 <dl class=hover> + 旧版表格行。按 (date,rating,org) 去重。"""
    items, seen = [], set()
    for it in _ths_dl_items(html_text) + _ths_table_rows(html_text):
        key = (it["date"], it["rating"], it["org"])
        if key in seen:
            continue
        seen.add(key)
        items.append(it)
    return items


def _fetch_ths(code: str, days: int, fetched_at: str) -> dict:
    """同花顺 basic.10jqka.com.cn worth.html 降级源（requests + 正则，GBK）。
    健康页面解析后一律返回 dict（0 条评级也返回 count=0）；请求失败才抛。"""
    headers = {"User-Agent": UA, "Referer": "https://basic.10jqka.com.cn/"}
    errors = []
    for tpl in (THS_URL_TPL, THS_URL_NEW_TPL):
        try:
            url = tpl.format(code=code)
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code != 200:
                errors.append(f"{url} HTTP {r.status_code}")
                continue
            text = None
            for enc in ("gbk", "utf-8"):
                t = r.content.decode(enc, errors="ignore")
                if "盈利预测" in t or "研报评级" in t:
                    text = t
                    break
            if text is None:
                errors.append(f"{url} 页面非预期内容(疑似验证墙)，长度={len(r.content)}")
                continue
            items = _parse_ths(text)
            if not items:
                errors.append(f"{url} 页面内未解析到评级条目")
                continue
            return _build_result(items, days, "ths", fetched_at)
        except Exception as e:                          # noqa: BLE001 —— 每个 URL 独立尝试
            errors.append(f"{tpl}: {e}")
    raise RuntimeError("；".join(errors))


# ────────────────────────────── 对外入口 ──────────────────────────────

def fetch_research_reports(code: str, days: int = 90) -> dict:
    """研报观点汇总 fetcher。永不抛异常。

    code: 603319 / SH603319 / 603319.SH 均可；days: 回看天数（默认 90）。
    返回结构见模块 docstring；仅当所有源请求级失败才返回 {"error": str}。
    """
    try:
        fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    except Exception:                                   # noqa: BLE001
        fetched_at = datetime.now().isoformat(timespec="seconds")
    try:
        days = int(days)
        if days <= 0:
            raise ValueError("days 必须为正整数")
    except (TypeError, ValueError) as e:
        return {"error": f"参数错误: {e}", "fetched_at": fetched_at}
    try:
        code6 = _normalize_code(code)
    except ValueError as e:
        return {"error": str(e), "fetched_at": fetched_at}

    # 主源：东财（健康响应返回 dict，可能是 count=0）
    em_err = None
    try:
        em_result = _fetch_eastmoney(code6, days, fetched_at)
    except Exception as e:                              # noqa: BLE001 —— 永不向上抛
        em_result, em_err = None, f"{type(e).__name__}: {e}"
    if em_result is not None and em_result["count"] > 0:
        return em_result

    # 降级：同花顺（东财窗口内 0 篇或请求失败都试一把——两源研报库并集更大）
    try:
        ths_result = _fetch_ths(code6, days, fetched_at)
    except Exception as e:                              # noqa: BLE001
        ths_err = f"{type(e).__name__}: {e}"
        if em_result is not None:
            # 东财本身健康只是窗口内无研报 → 返回东财 0 篇结果（真实答案），不算错误
            return em_result
        return {"error": f"东财主源失败({em_err})；同花顺降级亦失败: {ths_err}",
                "fetched_at": fetched_at}
    if ths_result["count"] > 0:
        return ths_result
    return em_result if em_result is not None else ths_result


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "603319"
    ndays = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    t0 = time.time()
    result = fetch_research_reports(code, ndays)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n# 耗时 {time.time() - t0:.2f}s", file=sys.stderr)
