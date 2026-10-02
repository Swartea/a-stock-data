"""V3 编排层的低风险通用辅助函数。

Phase 1A 先从 ``analysis.pipeline`` 复制出不依赖 V2 monkey-patch、
不读写全局 source meta、也不改变量化业务口径的时间/新鲜度逻辑。

注意：本阶段仅建立独立模块与契约测试；pipeline 的调用切换放到下一小步，
确保每次变更都能单独回退和验证。
"""

import time
from datetime import date, datetime, timedelta
from datetime import time as dtime

from analysis.research.trading_calendar import TradingDayStatus
from analysis.research.trading_calendar_szse_fetch import fetch_szse_trading_calendar

#: A 股连续竞价开盘时点；此前不把「今天」算作最新交易日。
_MARKET_OPEN_TIME = dtime(9, 30)

#: 单月交易日历证据的最长缓存时长。
_CALENDAR_CACHE_TTL = timedelta(hours=24)

#: 向前回溯最多加载的月份数（覆盖月末/年末跨月与年初长假）。
_CALENDAR_MAX_MONTHS = 2

#: 向前逐日回溯的硬上限，防止任何情况下出现无界循环。
_CALENDAR_MAX_SCAN_DAYS = 62

#: 缓存条目上限，超出后按抓取时间淘汰最旧的一条。
_CALENDAR_CACHE_MAX_ENTRIES = 8

#: ``(year, month) -> (evidence, fetched_at_monotonic)``；仅缓存有效官方证据。
_calendar_cache: dict[tuple[int, int], tuple[object, float]] = {}


def _clear_trading_calendar_cache() -> None:
    """清空月度交易日历缓存（测试与长驻进程使用）。"""
    _calendar_cache.clear()


def _evict_oldest_calendar_entry() -> None:
    while len(_calendar_cache) > _CALENDAR_CACHE_MAX_ENTRIES:
        oldest = min(_calendar_cache.items(), key=lambda item: item[1][1])[0]
        del _calendar_cache[oldest]


def _calendar_evidence(year: int, month: int, now: datetime, *, allow_fetch: bool = True):
    """返回该月官方交易日历证据，24 小时内复用缓存。

    ``allow_fetch=False`` 时只读缓存。抓取失败不会写入缓存，下一次调用会重试；
    调用方据此回退到工作日估计，而不是把「拿不到证据」当成休市。
    """
    key = (year, month)
    cached = _calendar_cache.get(key)
    monotonic_now = time.monotonic()
    if (cached is not None
            and monotonic_now - cached[1] < _CALENDAR_CACHE_TTL.total_seconds()):
        return cached[0]
    if not allow_fetch:
        return None

    try:
        evidence = fetch_szse_trading_calendar(
            year,
            month,
            fetched_at=now.astimezone().isoformat(timespec="seconds"),
        )
    except Exception:
        # 网络/协议/行校验失败都视为「无证据」，绝不由失败推断休市。
        return None

    if getattr(evidence, "calendar", None) is None or not hasattr(
        evidence.calendar, "status_on"
    ):
        return None

    _calendar_cache[key] = (evidence, time.monotonic())
    _evict_oldest_calendar_entry()
    return evidence


def _latest_explicit_open_day(now: datetime) -> date | None:
    """按官方日历回溯出最近一个「明确开市」的交易日。

    9:30 之后今天本身可能已开市，9:30 之前今天还没开市，故起点不同。
    遇到 ``CLOSED`` 继续向前；遇到 ``UNKNOWN``（证据缺行）立即放弃，因为缺行
    不等于休市。回溯最多覆盖 ``_CALENDAR_MAX_MONTHS`` 个月，返回 ``None``
    表示证据不足，由调用方回退到工作日估计。
    """
    today = now.date()
    cursor = today if now.time() >= _MARKET_OPEN_TIME else today - timedelta(days=1)

    loaded: set[tuple[int, int]] = set()
    for _ in range(_CALENDAR_MAX_SCAN_DAYS):
        key = (cursor.year, cursor.month)
        if key in loaded:
            evidence = _calendar_evidence(cursor.year, cursor.month, now, allow_fetch=False)
        elif len(loaded) >= _CALENDAR_MAX_MONTHS:
            return None
        else:
            evidence = _calendar_evidence(cursor.year, cursor.month, now)
            loaded.add(key)
            if evidence is None:
                return None
        if evidence is None:
            return None

        status = evidence.calendar.status_on(cursor.isoformat())
        if status is TradingDayStatus.OPEN:
            return cursor
        if status is TradingDayStatus.UNKNOWN:
            return None
        cursor = cursor - timedelta(days=1)
    return None


def _weekday_trading_day_estimate(now: datetime) -> date:
    """工作日口径的旧行为：周末回退周五；工作日 9:30 前回退上一工作日。

    与原 ``analysis.pipeline._latest_trading_day`` 保持同一行为。
    """
    d = now.date()
    if now.weekday() >= 5:
        d = d - timedelta(days=now.weekday() - 4)
    elif now.time() < _MARKET_OPEN_TIME:
        d = d - timedelta(days=1)
        while d.weekday() >= 5:
            d = d - timedelta(days=1)
    return d


def _latest_trading_day() -> date:
    """最新交易日：优先采用官方交易日历，证据不足时回退工作日估计。

    优先用深交所官方月历显式证明开市/休市，从而修正法定节假日。
    若证据不可用、跨月超出回溯范围，或某日状态为 ``UNKNOWN``，则退回既有的
    工作日估计——缺行永远不会被推断成休市。返回类型仍是 ``date``，
    调用方契约不变。
    """
    now = datetime.now()
    return _latest_explicit_open_day(now) or _weekday_trading_day_estimate(now)


def _kline_freshness(chip_data: dict) -> dict:
    """K 线最后 bar 与最新交易日比较，返回 ``ok / warn / na``。"""
    exp = _latest_trading_day().isoformat()
    last_bar = None
    if chip_data and isinstance(chip_data, dict) and "error" not in chip_data:
        klines = chip_data.get("kline") or []
        if klines:
            last_bar = str(klines[-1].get("date", ""))[:10]
        if not last_bar:
            last_bar = str(chip_data.get("window_end", ""))[:10] or None

    if not last_bar:
        err = (chip_data or {}).get("error", "无K线数据")
        return {
            "last_bar": None,
            "expected": exp,
            "level": "na",
            "text": f"无K线(筹码模块失败: {err}), 无法校验K线时点",
        }

    if last_bar >= exp:
        return {
            "last_bar": last_bar,
            "expected": exp,
            "level": "ok",
            "text": f"K线最后交易日 {last_bar} 已到最新交易日, 新鲜",
        }

    return {
        "last_bar": last_bar,
        "expected": exp,
        "level": "warn",
        "text": (
            f"K线停在 {last_bar}, 最新交易日 {exp} — "
            "若为法定节假日/周末属正常, 否则需关注数据延迟"
        ),
    }


def _record_kline_freshness_guard(run_log: dict, freshness: dict) -> None:
    """把 K 线 freshness 结果投影到现有 run_log guard/fallback 契约。"""
    run_log["guard"]["kline_freshness"] = (
        f"last_bar={freshness['last_bar'] or 'N/A'} vs 最新交易日={freshness['expected']} -> "
        f"{freshness['level']} ({freshness['text']})"
    )
    if freshness["level"] == "warn":
        run_log["fallback_chain"].append(f"K线时点: {freshness['text']} [WARN]")


def _initialize_run_log(started) -> dict:
    """按现有 V3 契约创建一次分析运行的初始 run_log。"""
    return {
        "started_at": started.astimezone().isoformat(timespec="seconds"),
        "finished_at": None,
        "total_sec": None,
        "sources": {},
        "source_meta": {},
        "guard": {
            "status": "N/A 单票流程不用池CSV",
            "kline_freshness": None,
        },
        "fallback_chain": [],
        "fatal": None,
    }


def _finalize_run_log_timing(run_log: dict, started, now_fn, time_fn) -> None:
    """按现有 V3 契约写入 run_log 的结束时点与总耗时。"""
    run_log["finished_at"] = now_fn().astimezone().isoformat(timespec="seconds")
    run_log["total_sec"] = round(time_fn() - started.timestamp(), 1)
