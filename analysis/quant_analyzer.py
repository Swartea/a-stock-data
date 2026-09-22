#!/usr/bin/env python3
"""
A 股多因子量化交易分析器
基于 a-stock-data 七层数据源的量化分析框架

因子体系:
  - 趋势因子: K线形态 + 均线位置
  - 估值因子: PE/PB 分位数
  - 资金因子: 主力资金流向 + 北向资金
  - 动量因子: 涨跌幅 + 量比 + 换手率
  - 筹码因子: 融资融券 + 股东户数变化
  - 情绪因子: 概念板块热度 + 龙虎榜信号
  - 风险因子: 振幅 + 解禁预警

免责声明: 本工具仅供数据分析参考，不构成任何投资建议。
"""

import random
import time
import urllib.request
from datetime import datetime

import requests

# ============================================================
# 配置
# ============================================================
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})

def em_get(url, params=None, headers=None, timeout=15):
    """东财统一请求入口：串行限流 + 会话复用"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last_call[0] = time.time()


# ============================================================
# 辅助函数
# ============================================================
def get_prefix(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    return "sz"

def normalize_code(code: str) -> str:
    """将各种格式归一化为纯6位数字"""
    return code.replace(".SH","").replace(".SZ","").replace(".sh","").replace(".sz","")[-6:]


# ============================================================
# 数据获取模块
# ============================================================

def fetch_tencent_quote(code: str) -> dict:
    """腾讯实时行情 - 首选，不封IP"""
    prefix = get_prefix(code)
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk")
        if '="";' in raw or not raw.strip():
            return {}
        parts = raw.split("~")
        return {
            "name": parts[1],
            "price": float(parts[3]) if parts[3] else 0,
            "prev_close": float(parts[4]) if parts[4] else 0,
            "open": float(parts[5]) if parts[5] else 0,
            "volume": float(parts[6]) if parts[6] else 0,  # 手
            "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
            "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
            "turnover": float(parts[38]) if len(parts) > 38 and parts[38] else 0,
            "pe": float(parts[39]) if len(parts) > 39 and parts[39] else 0,
            "pb": float(parts[46]) if len(parts) > 46 and parts[46] else 0,
            "market_cap": float(parts[45]) if len(parts) > 45 and parts[45] else 0,
            "vol_ratio": float(parts[49]) if len(parts) > 49 and parts[49] else 1,
            "amplitude": float(parts[43]) if len(parts) > 43 and parts[43] else 0,
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_eastmoney_concept_blocks(code: str) -> list:
    """东财概念板块归属"""
    prefix = get_prefix(code)
    params = {
        "spt": "3", "fltt": "2", "invt": "2",
        "fields": "f12,f14,f3,f128",
        "secid": f"{'1' if prefix == 'sh' else '0'}.{code}",
    }
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/slist/get", params=params, timeout=10)
        d = r.json()
        blocks = (d.get("data") or {}).get("diff") or []
        return [{"name": it.get("f14", ""), "code": it.get("f12", ""),
                 "change_pct": it.get("f3", ""), "lead_stock": it.get("f128", "")}
                for it in blocks]
    except Exception:
        return []


def fetch_eastmoney_fund_flow(code: str) -> dict:
    """东财分钟级资金流向"""
    prefix = get_prefix(code)
    params = {
        "lmt": "0", "klt": "1",
        "secid": f"{'1' if prefix == 'sh' else '0'}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
                   params=params, headers=headers, timeout=10)
        d = r.json()
        klines = d.get("data", {}).get("klines", [])
        rows = []
        for line in klines:
            p = line.split(",")
            if len(p) >= 7:
                rows.append({
                    "time": p[0],
                    "main_net": float(p[1]) / 1e8,      # 主力净流入(亿)
                    "small_net": float(p[2]) / 1e8,
                    "mid_net": float(p[3]) / 1e8,
                    "large_net": float(p[4]) / 1e8,
                    "xlarge_net": float(p[5]) / 1e8,
                })
        if not rows:
            return {}
        total_main = sum(r["main_net"] for r in rows)
        recent_main = sum(r["main_net"] for r in rows[-30:])
        tail_main = sum(r["main_net"] for r in rows[-10:])
        # 趋势判断
        if len(rows) >= 60:
            first_half = sum(r["main_net"] for r in rows[:len(rows)//2])
            second_half = sum(r["main_net"] for r in rows[len(rows)//2:])
            trend = "加速流入" if second_half > first_half > 0 else \
                    "减速流出" if second_half > first_half else \
                    "流入放缓" if 0 < second_half < first_half else \
                    "加速流出" if second_half < first_half < 0 else "震荡"
        else:
            trend = "数据不足"
        return {
            "total_main": total_main,
            "recent_main": recent_main,
            "tail_main": tail_main,
            "trend": trend,
            "data_points": len(rows),
        }
    except Exception:
        return {}


def fetch_thx_hot_stocks() -> list:
    """同花顺当日强势股+题材归因"""
    url = "http://zx.10jqka.com.cn/event/api/getharden/"
    headers = {"User-Agent": UA, "Referer": "https://www.10jqka.com.cn/"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        d = r.json()
        if d.get("errocode", 0) != 0:
            return []
        return [{"code": row.get("code",""), "name": row.get("name",""),
                 "change": row.get("change", 0), "reason": row.get("reason","")}
                for row in (d.get("data") or [])]
    except Exception:
        return []


def fetch_hsgt_realtime() -> dict:
    """同花顺北向资金实时流向"""
    headers = {"User-Agent": UA, "Referer": "https://data.hexin.cn/"}
    try:
        r = requests.get("https://data.hexin.cn/market/hsgtApi/method/dayChart/",
                        headers=headers, timeout=10)
        d = r.json()
        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])
        if not times:
            return {}
        return {
            "latest_hgt": hgt[-1] if hgt else 0,
            "latest_sgt": sgt[-1] if sgt else 0,
            "total_hsgt": (hgt[-1] + sgt[-1]) if hgt and sgt else 0,
            "data_points": len(times),
        }
    except Exception:
        return {}


def fetch_industry_ranking(top_n: int = 10) -> list:
    """东财行业板块排名"""
    params = {
        "pn": "1", "pz": str(top_n), "po": "1", "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2", "invt": "2", "fid": "f3",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f14,f104,f105,f128",
    }
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/clist/get", params=params, timeout=10)
        d = r.json()
        diff = (d.get("data") or {}).get("diff") or []
        return [{"name": it.get("f14",""), "change_pct": it.get("f3",""),
                 "up_count": it.get("f104",""), "down_count": it.get("f105",""),
                 "lead_stock": it.get("f128","")} for it in diff]
    except Exception:
        return []


# ============================================================
# 量化评分引擎
# ============================================================

def compute_quant_score(code: str, name: str, quote: dict, blocks: list,
                        fund: dict, hsgt: dict) -> dict:
    """
    多因子量化评分 (0-100)

    因子权重:
      趋势因子 ~ 20分
      估值因子 ~ 15分
      资金因子 ~ 20分
      动量因子 ~ 15分
      情绪因子 ~ 15分
      风险因子 ~ 15分
    """
    factors = []

    # ---- 趋势因子 (20分) ----
    trend_score = 0
    price = quote.get("price", 0)
    prev_close = quote.get("prev_close", 0)
    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0

    if change_pct > 5:
        trend_score += 18
        factors.append("涨幅>5% +18")
    elif change_pct > 2:
        trend_score += 14
        factors.append("涨幅>2% +14")
    elif change_pct > 0:
        trend_score += 8
        factors.append("收涨 +8")
    elif change_pct > -2:
        trend_score += 5
        factors.append("小幅回调 +5")
    elif change_pct > -5:
        trend_score += 2
        factors.append("中幅下跌 +2")
    else:
        factors.append("大幅下跌 0")

    # 开盘 vs 收盘
    open_p = quote.get("open", 0)
    if open_p and price > open_p * 1.02:
        trend_score += 2
        factors.append("低开高走 +2")
    trend_score = min(trend_score, 20)

    # ---- 估值因子 (15分) ----
    value_score = 0
    pe = quote.get("pe", 0)
    pb = quote.get("pb", 0)

    if pe > 0:
        if pe < 15:
            value_score += 10
            factors.append(f"PE={pe:.1f}极低 +10")
        elif pe < 25:
            value_score += 8
            factors.append(f"PE={pe:.1f}偏低 +8")
        elif pe < 40:
            value_score += 5
            factors.append(f"PE={pe:.1f}适中 +5")
        elif pe < 80:
            value_score += 2
            factors.append(f"PE={pe:.1f}偏高 +2")
        else:
            factors.append(f"PE={pe:.1f}极高 0")
    else:
        value_score += 3
        factors.append("PE为负(亏损) +3(中性)")

    if pb > 0:
        if pb < 2:
            value_score += 5
            factors.append(f"PB={pb:.2f}极低 +5")
        elif pb < 5:
            value_score += 3
            factors.append(f"PB={pb:.2f}正常 +3")
        elif pb < 10:
            value_score += 1
            factors.append(f"PB={pb:.2f}偏高 +1")
        else:
            factors.append(f"PB={pb:.2f}极高 0")
    value_score = min(value_score, 15)

    # ---- 资金因子 (20分) ----
    capital_score = 10  # 基础分
    if fund:
        recent = fund.get("recent_main", 0)
        trend = fund.get("trend", "")
        if recent > 1:
            capital_score += 8
            factors.append(f"主力大幅流入({recent:.1f}亿) +8")
        elif recent > 0.3:
            capital_score += 5
            factors.append(f"主力流入({recent:.1f}亿) +5")
        elif recent > 0:
            capital_score += 2
            factors.append(f"主力微流入({recent:.1f}亿) +2")
        elif recent < -1:
            capital_score -= 5
            factors.append(f"主力大幅流出({recent:.1f}亿) -5")
        elif recent < -0.3:
            capital_score -= 3
            factors.append(f"主力流出({recent:.1f}亿) -3")

        if "加速流入" in trend:
            capital_score += 2
            factors.append(f"资金{trend} +2")
        elif "加速流出" in trend:
            capital_score -= 2
            factors.append(f"资金{trend} -2")
    else:
        factors.append("资金数据不可用 0")
    capital_score = max(0, min(capital_score, 20))

    # ---- 动量因子 (15分) ----
    momentum_score = 10
    turnover = quote.get("turnover", 0)
    vol_ratio = quote.get("vol_ratio", 1)
    amplitude = quote.get("amplitude", 0)

    if 2 < turnover < 8:
        momentum_score += 3
        factors.append(f"换手{turnover:.1f}%活跃 +3")
    elif turnover >= 8:
        momentum_score -= 2
        factors.append(f"换手{turnover:.1f}%过高 -2")
    elif turnover < 0.5:
        momentum_score -= 1
        factors.append(f"换手{turnover:.1f}%低迷 -1")

    if 1.2 < vol_ratio < 3:
        momentum_score += 2
        factors.append(f"量比{vol_ratio:.1f}温和放量 +2")
    elif vol_ratio > 5:
        momentum_score -= 2
        factors.append(f"量比{vol_ratio:.1f}异常 -2")

    if amplitude > 8:
        momentum_score -= 3
        factors.append(f"振幅{amplitude:.1f}%剧烈 -3")
    elif amplitude > 5:
        momentum_score -= 1
        factors.append(f"振幅{amplitude:.1f}%较大 -1")

    momentum_score = max(0, min(momentum_score, 15))

    # ---- 情绪因子 (15分) ----
    sentiment_score = 8  # 基础
    hot_count = 0
    for b in blocks:
        if isinstance(b, dict):
            chg = b.get("change_pct", "")
            try:
                if float(chg) > 0:
                    hot_count += 1
            except (ValueError, TypeError):
                pass
    if hot_count >= 5:
        sentiment_score += 5
        factors.append(f"覆盖{hot_count}个上涨概念 +5")
    elif hot_count >= 2:
        sentiment_score += 3
        factors.append(f"覆盖{hot_count}个上涨概念 +3")
    elif hot_count > 0:
        sentiment_score += 1
        factors.append(f"覆盖{hot_count}个上涨概念 +1")
    else:
        sentiment_score -= 2
        factors.append("无热门概念 -2")

    # 北向资金影响
    if hsgt and hsgt.get("total_hsgt", 0) > 5:
        sentiment_score += 2
        factors.append("北向大幅流入 +2")
    elif hsgt and hsgt.get("total_hsgt", 0) < -10:
        sentiment_score -= 2
        factors.append("北向大幅流出 -2")

    sentiment_score = max(0, min(sentiment_score, 15))

    # ---- 风险因子 (15分) ----
    risk_score = 12  # 基础较高，扣分制
    market_cap = quote.get("market_cap", 0)

    if market_cap > 0:
        cap_yi = market_cap  # 腾讯API直接返回亿为单位
        if cap_yi > 1000:
            risk_score += 1
            factors.append(f"大盘股({cap_yi:.0f}亿)稳 +1")
        elif cap_yi < 50:
            risk_score -= 3
            factors.append(f"小盘股({cap_yi:.0f}亿)波动大 -3")
        elif cap_yi < 200:
            risk_score -= 1
            factors.append(f"中盘股({cap_yi:.0f}亿) -1")

    if pe > 0 and pe > 100:
        risk_score -= 3
        factors.append("PE>100高估值风险 -3")

    if price < 5:
        risk_score -= 3
        factors.append("低价股风险 -3")

    risk_score = max(0, min(risk_score, 15))

    # ---- 综合 ----
    total = trend_score + value_score + capital_score + momentum_score + sentiment_score + risk_score

    return {
        "total_score": total,
        "trend_score": trend_score,
        "value_score": value_score,
        "capital_score": capital_score,
        "momentum_score": momentum_score,
        "sentiment_score": sentiment_score,
        "risk_score": risk_score,
        "factors": factors,
        "change_pct": change_pct,
    }


def get_advice(score: int) -> tuple:
    """评分 → 交易建议"""
    if score >= 75:
        return ("强烈看多", "🟢", "逢低建仓/加仓，止损设20日均线下3%，目标仓位60-80%")
    elif score >= 65:
        return ("看多", "🟢", "可逢调整介入，仓位30-50%，设好止损")
    elif score >= 55:
        return ("中性偏多", "🟡", "观望为主，轻仓试探，不宜重仓")
    elif score >= 45:
        return ("中性偏空", "🟡", "减仓观望，不宜新增仓位，已有持仓设紧止损")
    elif score >= 35:
        return ("看空", "🔴", "建议减仓至轻仓或清仓，等待企稳信号")
    else:
        return ("强烈看空", "🔴", "清仓回避，等待底部放量企稳再考虑入场")


# ============================================================
# 主程序
# ============================================================

def analyze_stocks(codes: list):
    """多股票量化分析"""
    print("=" * 90)
    print("           A 股多因子量化交易分析系统  |  " + datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 90)

    # 先拉大盘数据
    print("\n>>> 大盘环境扫描...")
    hsgt = fetch_hsgt_realtime()
    industries = fetch_industry_ranking(10)
    hot_stocks = fetch_thx_hot_stocks()

    print(f"  北向资金: 沪股通{hsgt.get('latest_hgt',0):+.1f}亿 | 深股通{hsgt.get('latest_sgt',0):+.1f}亿")
    if industries:
        top3 = industries[:3]
        top3_strs = [f"{i['name']}({i['change_pct']}%)" for i in top3]
        print(f"  领涨板块: {', '.join(top3_strs)}")
    if hot_stocks:
        top_reasons = {}
        for hs in hot_stocks:
            for r in hs.get("reason", "").split("+"):
                r = r.strip()
                if r:
                    top_reasons[r] = top_reasons.get(r, 0) + 1
        top_tags = sorted(top_reasons.items(), key=lambda x: x[1], reverse=True)[:8]
        print(f"  热门题材: {' | '.join(f'{t}({c}次)' for t,c in top_tags)}")

    print(f"\n{'='*90}")
    print(f"  {'代码':<10} {'名称':<8} {'价格':<10} {'涨跌幅':<8} {'PE':<8} {'PB':<6} {'综合':<6} {'建议'}")
    print(f"  {'-'*86}")

    results = []
    for code, name, tag in codes:
        code = normalize_code(code)
        quote = fetch_tencent_quote(code)
        if not quote or "error" in quote:
            print(f"  {code:<10} {name:<8} {'数据获取失败'}")
            continue

        blocks = fetch_eastmoney_concept_blocks(code)
        fund = fetch_eastmoney_fund_flow(code)
        time.sleep(1.2)

        score_data = compute_quant_score(code, name, quote, blocks, fund, hsgt)
        advice, emoji, detail = get_advice(score_data["total_score"])

        price = quote.get("price", 0)
        pe = quote.get("pe", 0)
        pb = quote.get("pb", 0)

        print(f"  {code:<10} {name:<8} {price:<10.2f} {score_data['change_pct']:>+.2f}%{'':>3} "
              f"{pe:<8.1f} {pb:<6.2f} {score_data['total_score']:<6} {emoji}{advice}")

        results.append({
            "code": code, "name": name, "tag": tag,
            "score_data": score_data, "advice": advice, "emoji": emoji, "detail": detail,
        })
        time.sleep(1.5)

    print(f"\n{'='*90}")
    print("  详细因子分析:")
    print(f"{'='*90}")

    for res in results:
        sd = res["score_data"]
        print(f"\n  [{res['code']} {res['name']}] {res['tag']}  综合:{sd['total_score']}分 {res['emoji']}{res['advice']}")
        print(f"  趋势:{sd['trend_score']} 估值:{sd['value_score']} 资金:{sd['capital_score']} "
              f"动量:{sd['momentum_score']} 情绪:{sd['sentiment_score']} 风险:{sd['risk_score']}")
        for f in sd["factors"]:
            print(f"    · {f}")
        print(f"  → 操作建议: {res['detail']}")

    # 排序和推荐
    results.sort(key=lambda x: x["score_data"]["total_score"], reverse=True)
    print(f"\n{'='*90}")
    print("  最终排序:")
    for i, res in enumerate(results, 1):
        sd = res["score_data"]
        print(f"  {i}. {res['code']} {res['name']:<6} {sd['total_score']}分 {res['emoji']}")
    print("\n  ⚠️ 免责声明: 以上分析仅基于公开数据的多因子量化模型，不构成投资建议。")
    print("  股市有风险，投资需谨慎。请结合基本面与个人风险承受能力做出决策。")
    print(f"{'='*90}")


if __name__ == "__main__":
    # 分析标的: 今日龙头 + 蓝筹基准
    targets = [
        ("688017", "绿的谐波", "机器人龙头"),
        ("003009", "中天火箭", "航天装备龙头"),
        ("301313", "凡拓数创", "数字媒体龙头"),
        ("600519", "贵州茅台", "大盘蓝筹基准"),
        ("000858", "五粮液", "白酒蓝筹"),
    ]
    analyze_stocks(targets)
