import analysis.orchestration.helpers as helpers
import analysis.pipeline as pipeline
from analysis.orchestration.helpers import _record_kline_freshness_guard


def _run_log():
    return {
        "guard": {},
        "fallback_chain": [],
    }


def test_pipeline_uses_kline_guard_boundary():
    assert pipeline._record_kline_freshness_guard is helpers._record_kline_freshness_guard


def test_guard_helper_formats_exact_ok_status_without_fallback():
    run_log = _run_log()
    freshness = {
        "last_bar": "2026-09-15",
        "expected": "2026-09-15",
        "level": "ok",
        "text": "K线已更新到最新交易日",
    }

    result = _record_kline_freshness_guard(run_log, freshness)

    assert result is None
    assert run_log["guard"]["kline_freshness"] == (
        "last_bar=2026-09-15 vs 最新交易日=2026-09-15 -> "
        "ok (K线已更新到最新交易日)"
    )
    assert run_log["fallback_chain"] == []


def test_guard_helper_uses_na_for_missing_last_bar_without_fallback():
    run_log = _run_log()
    freshness = {
        "last_bar": None,
        "expected": "2026-09-15",
        "level": "na",
        "text": "无K线数据",
    }

    _record_kline_freshness_guard(run_log, freshness)

    assert run_log["guard"]["kline_freshness"] == (
        "last_bar=N/A vs 最新交易日=2026-09-15 -> na (无K线数据)"
    )
    assert run_log["fallback_chain"] == []


def test_guard_helper_warn_appends_exact_fallback_once():
    run_log = _run_log()
    freshness = {
        "last_bar": "2026-09-12",
        "expected": "2026-09-15",
        "level": "warn",
        "text": "K线落后最新交易日",
    }

    _record_kline_freshness_guard(run_log, freshness)

    assert run_log["guard"]["kline_freshness"] == (
        "last_bar=2026-09-12 vs 最新交易日=2026-09-15 -> "
        "warn (K线落后最新交易日)"
    )
    assert run_log["fallback_chain"] == ["K线时点: K线落后最新交易日 [WARN]"]


def test_guard_helper_only_exact_lowercase_warn_adds_fallback():
    run_log = _run_log()
    freshness = {
        "last_bar": "2026-09-12",
        "expected": "2026-09-15",
        "level": "WARN",
        "text": "大写状态",
    }

    _record_kline_freshness_guard(run_log, freshness)

    assert run_log["guard"]["kline_freshness"].endswith("WARN (大写状态)")
    assert run_log["fallback_chain"] == []


def test_guard_helper_preserves_existing_fallback_entries_and_appends_warn():
    run_log = {
        "guard": {"existing": "keep"},
        "fallback_chain": ["已有降级"],
    }
    freshness = {
        "last_bar": "2026-09-12",
        "expected": "2026-09-15",
        "level": "warn",
        "text": "K线延迟",
    }

    _record_kline_freshness_guard(run_log, freshness)

    assert run_log["guard"]["existing"] == "keep"
    assert run_log["fallback_chain"] == [
        "已有降级",
        "K线时点: K线延迟 [WARN]",
    ]
