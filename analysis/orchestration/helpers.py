"""V3 编排层的低风险通用辅助函数。

Phase 1A 先从 ``analysis.pipeline`` 复制出不依赖 V2 monkey-patch、
不读写全局 source meta、也不改变量化业务口径的时间/新鲜度逻辑。

注意：本阶段仅建立独立模块与契约测试；pipeline 的调用切换放到下一小步，
确保每次变更都能单独回退和验证。
"""

from datetime import date, datetime, time as dtime, timedelta


def _latest_trading_day() -> date:
    """最新交易日估计：周末回退周五；工作日 9:30 前回退上一工作日。

    与原 ``analysis.pipeline._latest_trading_day`` 保持同一行为。
    法定节假日不在本函数处理范围内，只用于新鲜度提示。
    """
    now = datetime.now()
    d = now.date()
    if now.weekday() >= 5:
        d = d - timedelta(days=now.weekday() - 4)
    elif now.time() < dtime(9, 30):
        d = d - timedelta(days=1)
        while d.weekday() >= 5:
            d = d - timedelta(days=1)
    return d


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


def _finalize_run_log_timing(run_log: dict, started, now_fn, time_fn) -> None:
    """按现有 V3 契约写入 run_log 的结束时点与总耗时。"""
    run_log["finished_at"] = now_fn().astimezone().isoformat(timespec="seconds")
    run_log["total_sec"] = round(time_fn() - started.timestamp(), 1)
