# -*- coding: utf-8 -*-
"""
fetch_news_em.py — 个股新闻舆情 fetcher（A股）

契约:
    fetch_news_em(code: str, limit: int = 20) -> dict
    永不抛异常；失败返回 {"error": str}

返回结构:
    {
      "news": [{"date","title","summary","source","url","sentiment"}],  # sentiment: pos/neg/neutral
      "positive": [利好前3条(含 sentiment 的完整条目)],
      "negative": [利空前3条],
      "count": int,
      "source": str,        # 实际命中的源: "eastmoney_search_jsonp" / "sina_7x24_zhibo"
      "fetched_at": ISO8601
    }

数据源（2026-09 实测，优先级从高到低自动降级）:
    1) 东财 search-api-web JSONP（个股新闻，关键词=代码）——实测通（603319: 186 hits）
       说明: 规格里猜的 np-listapi.eastmoney.com/comm/web/getNewsByColumns 经实测
       (column=290/344..400 共 14 组) 是纯栏目快讯流，mTypeAndCode 参数被服务端忽略、
       不会按个股过滤，故不作为个股新闻源；真正的东财个股新闻走 search-api-web。
       该接口有间歇风控（只回 passportWeb 无文章列表，SKILL §5.1 注 #18），模块内 3 次退避重试。
    2) 新浪财经个股资讯页（vCB_AllNewsStock）——个股相关新闻列表，独立于东财。
    3) 新浪 7×24 直播流（zhibo.sina.com.cn，zhibo_id=152）——按 代码/公司名 过滤，
       周末/晚间个股快讯稀疏时可能无命中（SKILL 后备表同款）。

情绪分类（标题关键词）:
    利好: 中标/回购/增持/业绩预增/增长/合同/分红/获批/创新高
    利空: 减持/诉讼/处罚/亏损/下滑/质押/终止/问询/违规/爆雷
    其余中性。先判利好后判利空。
"""
import json
import re
import time
from datetime import datetime, timezone

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

TIMEOUT = 15

POS_WORDS = ["中标", "回购", "增持", "业绩预增", "增长", "合同", "分红", "获批", "创新高"]
NEG_WORDS = ["减持", "诉讼", "处罚", "亏损", "下滑", "质押", "终止", "问询", "违规", "爆雷"]

_TAG_RE = re.compile(r"<[^>]+>")


# ---------------------------------------------------------------- 工具函数

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _strip_html(text: str) -> str:
    """去掉 HTML 标签并压缩空白。"""
    if not text:
        return ""
    t = _TAG_RE.sub("", str(text))
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", t).strip()


def _classify(title: str) -> str:
    """标题关键词情绪分类: pos / neg / neutral。"""
    t = title or ""
    for w in POS_WORDS:
        if w in t:
            return "pos"
    for w in NEG_WORDS:
        if w in t:
            return "neg"
    return "neutral"


def _split_sentiment(news: list) -> tuple:
    """news 已按时间新→旧排序; positive/negative 各取前 3。"""
    pos = [n for n in news if n.get("sentiment") == "pos"][:3]
    neg = [n for n in news if n.get("sentiment") == "neg"][:3]
    return pos, neg


def _ok(news: list, source: str) -> dict:
    pos, neg = _split_sentiment(news)
    return {
        "news": news,
        "positive": pos,
        "negative": neg,
        "count": len(news),
        "source": source,
        "fetched_at": _now_iso(),
    }


# ---------------------------------------------------------------- 源1: 东财 JSONP

def _fetch_eastmoney_search(code: str, limit: int) -> list:
    """
    东财 search-api-web JSONP 个股新闻（SKILL §5.1 直连实现改编）。
    关键词 = 6 位代码。返回 [{date,title,summary,source,url,sentiment}] 或抛异常。
    """
    cb = "jQuery_news"
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    inner = json.dumps({
        "uid": "",
        "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                  "pageIndex": 1, "pageSize": limit, "preTag": "", "postTag": ""}},
    }, separators=(',', ':'))
    params = {"cb": cb, "param": inner}
    headers = {"User-Agent": UA, "Referer": "https://so.eastmoney.com/"}
    # 东财对该接口有间歇风控（SKILL §5.1 注 #18：只回 passportWeb 无文章列表），
    # 重试 + 退避可显著提升命中率。
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
            r.raise_for_status()
            text = r.text
            if "(" not in text or not text.rstrip().endswith(")"):
                raise ValueError("非 JSONP 响应: %s" % text[:120])
            d = json.loads(text[text.index("(") + 1: text.rindex(")")])
            if d.get("code") not in (0, "0", None):
                raise ValueError("东财接口业务错误: %s" % str(d.get("msg")))
            result = d.get("result") or {}
            articles = result.get("cmsArticleWebOld") or []
            if isinstance(articles, dict):      # 防御: 个别形态返回 {list:[...]}
                articles = articles.get("list") or []
            if result.get("passportWeb") and not articles:
                raise ValueError("东财 JSONP 间歇风控（只回 passportWeb），见 SKILL §5.1 注")
            if articles:
                rows, seen = [], set()
                for a in articles:
                    url_v = a.get("url") or a.get("uniqueUrl") or ""
                    if url_v in seen:
                        continue
                    seen.add(url_v)
                    title = _strip_html(a.get("title"))
                    if not title:
                        continue
                    rows.append({
                        "date": a.get("date") or a.get("showTime") or "",
                        "title": title,
                        "summary": _strip_html(a.get("content"))[:200]
                        or _strip_html(a.get("summary"))[:200],
                        "source": a.get("mediaName") or a.get("source") or "东方财富",
                        "url": url_v,
                        "sentiment": _classify(title),
                    })
                if rows:
                    return rows[:limit]
        except (requests.RequestException, ValueError, json.JSONDecodeError, TypeError) as e:
            last_err = "%s" % e
            if attempt == 2:
                break
        time.sleep(0.8 + 1.2 * attempt)    # 0.8, 2.0, 3.2s 替代 3, 7, 11s
    raise ValueError("东财 JSONP 连续 %d 次失败: %s" % (3, last_err))


# ---------------------------------------------------------------- 源2: 新浪个股资讯页

def _fetch_sina_stock_page(code: str, limit: int) -> list:
    """
    新浪财经个股资讯页（vCB_AllNewsStock，GB18030 HTML），个股相关新闻列表。
    code→symbol 前缀: 6/9→sh，0/2/3→sz。返回条目同契约结构。
    """
    symbol = "%s%s" % (_mkt_prefix(code), code)
    url = ("https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/"
           "%s.phtml" % symbol)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "gb18030"
    m = re.search(r'<div class="datelist">(.*?)</div>\s*</td>', r.text, re.S)
    chunk = m.group(1) if m else r.text
    chunk = chunk.replace("&nbsp;", " ")        # 行间用 &nbsp; 分隔，先归一化
    rows = []
    name = _resolve_name(code)
    pat = re.compile(
        r"(\d{4}-\d{2}-\d{2})(?:\s*(\d{2}:\d{2}))?\s*<a[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
        re.S)
    for mm in pat.finditer(chunk):
        date, hm, href, title = mm.group(1), mm.group(2), mm.group(3), mm.group(4)
        title = _strip_html(title)
        # 新浪把同概念/同行业文章也标成"个股相关资讯"——只保留标题确实提到
        # 该股代码/简称的条目，避免把 特斯拉/宇树 等噪声混进单股舆情。
        if (not title or "vReport_Show" in href          # 研报 PDF 入口非新闻，跳过
                or (code not in title and not (name and name in title))):
            continue
        if len(rows) >= limit:
            break
        rows.append({
            "date": "%s %s:00" % (date, hm) if hm else "%s 00:00:00" % date,
            "title": title,
            "summary": "",
            "source": "新浪财经-个股资讯",
            "url": href,
            "sentiment": _classify(title),
        })
    if not rows:
        raise ValueError("新浪个股资讯页无新闻条目（symbol=%s）" % symbol)
    return rows[:limit]


# ---------------------------------------------------------------- 源3: 新浪 7×24

def _mkt_prefix(code: str) -> str:
    """6/9 开头→sh，0/2/3→sz，4/8→bj。"""
    if code[0] in ("6", "9"):
        return "sh"
    if code[0] in ("4", "8"):
        return "bj"
    return "sz"


def _resolve_name(code: str):
    """腾讯行情接口取公司简称（独立于东财，主源挂掉时仍可用）。失败返回 None。"""
    try:
        r = requests.get("https://qt.gtimg.cn/q=%s%s" % (_mkt_prefix(code), code),
                         headers={"User-Agent": UA}, timeout=8)
        r.encoding = "gbk"
        parts = r.text.split("~")
        name = (parts[1] if len(parts) > 1 else "").strip()
        if name and not name.startswith("v_"):
            return name
        return None
    except Exception:
        return None


def _fetch_sina_zhibo(code: str, limit: int) -> list:
    """新浪 7×24 直播流按 代码/公司名 过滤（SKILL 后备表 zhibo_id=152）。"""
    name = _resolve_name(code)
    url = "https://zhibo.sina.com.cn/api/zhibo/feed"
    headers = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn/7x24/"}
    rows, seen, got = [], set(), 0
    for page in (1, 2, 3):                                  # 最近 ~3 天，300 条
        try:
            r = requests.get(url, params={
                "page": page, "page_size": 100, "zhibo_id": 152,
                "tag_id": 0, "dire": "f", "dpc": 1,
            }, headers=headers, timeout=TIMEOUT)
            r.raise_for_status()
            lst = ((r.json().get("result") or {}).get("data") or {}).get("feed") or {}
            items = lst.get("list") or []
        except Exception:
            items = []
        if not items:
            break
        got += len(items)
        for it in items:
            rich = it.get("rich_text") or ""
            text_plain = _strip_html(rich)
            if code not in rich and not (name and name in text_plain):
                continue
            uid = str(it.get("id"))
            if uid in seen:
                continue
            seen.add(uid)
            title = text_plain.split("。")[0][:60] or text_plain[:60]
            m = re.search(r'href="(https?://[^"]+)"', rich)
            link = m.group(1) if m else "https://finance.sina.com.cn/7x24/"
            rows.append({
                "date": it.get("create_time") or it.get("update_time") or "",
                "title": title,
                "summary": text_plain[:200],
                "source": "新浪财经7×24",
                "url": link,
                "sentiment": _classify(title),
            })
            if len(rows) >= limit:
                return rows[:limit]
    if not rows:
        raise ValueError("新浪7×24 近200条中无该股相关快讯（got=%d）" % got)
    return rows[:limit]


# ---------------------------------------------------------------- 主入口

def fetch_news_em(code: str, limit: int = 20) -> dict:
    """个股新闻舆情。永不抛异常；失败返回 {"error": str}。"""
    limit = max(1, min(int(limit), 50))
    code = re.sub(r"\D", "", str(code))                     # 清洗为纯数字
    if len(code) != 6:
        return {"error": "invalid code: %r" % code, "fetched_at": _now_iso()}

    last_err = None
    chain = (
        ("eastmoney_search_jsonp", lambda: _fetch_eastmoney_search(code, limit)),
        ("sina_stock_news", lambda: _fetch_sina_stock_page(code, limit)),
        ("sina_7x24_zhibo", lambda: _fetch_sina_zhibo(code, limit)),
    )
    for source, fn in chain:
        try:
            news = fn()
        except Exception as e:                              # noqa: BLE001 全兜底
            last_err = "%s: %s" % (source, e)
            time.sleep(0.5)
            continue
        if not news:
            last_err = "%s: 空结果" % source
            continue
        res = _ok(news, source)
        res["_degraded"] = (source != chain[0][0])
        return res
    return {"error": "所有源均失败: %s" % last_err, "fetched_at": _now_iso()}


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "603319"
    t0 = time.time()
    out = fetch_news_em(target)
    print("耗时 %.2fs" % (time.time() - t0), file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=2))
