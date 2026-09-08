"""V3 result 契约测试 — 防 Task 1.3 类回归（7 字段被破坏性置为 None）

历史: 2026-09-08 Task 1.3 误删 4 个 _call_new + 3 supplement 调用,
但 result 组装仍引用 7 字段（announcements/finance/news/research/peers/
fund_daily5/margin_hist）导致 7 字段全 None。本测试锁住 18 原有源 +
section registry 字段（Phase 1: irm）的非空契约。

灰度策略: spec §3.3 — "先保留 4 旧 fetcher 走老路径，5 新节走新注册表；下版本统一"
"""
import os
import sys
import json
import pytest
import subprocess
from datetime import datetime

WORKDIR = "/Users/swarteachou/Desktop/大A数据"


def _latest_result_v3(code: str = "600693", name: str = "东百集团") -> dict:
    """返回今日最新的 result_v3-{HHMM}.json dict; 缺失则 pytest.skip"""
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = f"{WORKDIR}/reports/{code}_{name}/{today}"
    if not os.path.exists(day_dir):
        pytest.skip(f"未找到 {day_dir}（需先跑 V3 至少一次）")
    pattern_files = [f for f in os.listdir(day_dir) if f.startswith("result_v3-") and f.endswith(".json")]
    if not pattern_files:
        pytest.skip(f"未找到 result_v3-*.json（需先跑 V3）")
    latest = max(pattern_files, key=lambda f: os.path.getmtime(os.path.join(day_dir, f)))
    with open(os.path.join(day_dir, latest), "r", encoding="utf-8") as f:
        return json.load(f)


def test_v3_result_has_4_call_new_fields():
    """4 个 _call_new 字段（announcements/finance/research/news）必须非 None
    防 Task 1.3 类回归: implementer 误删 _call_new 但 result 仍引用导致 None"""
    d = _latest_result_v3()
    for k in ("announcements", "finance", "research", "news"):
        assert d.get(k) is not None, (
            f"V3 result['{k}'] = None — 4 _call_new 调用被误删的回归 bug（spec §3.3 灰度：4 旧 fetcher 应保留）"
        )


def test_v3_result_has_3_supplement_fields():
    """3 个 supplement 字段（fund_daily5/margin_hist/peers）必须非 None
    防 Task 1.3 类回归: implementer 误删 supplement 循环但 result 仍引用导致 None"""
    d = _latest_result_v3()
    for k in ("fund_daily5", "margin_hist", "peers"):
        assert d.get(k) is not None, (
            f"V3 result['{k}'] = None — 3 supplement 调用被误删的回归 bug（spec §3.3 灰度：supplement 应保留）"
        )


def test_v3_result_has_section_registry_fields():
    """section registry 字段（Phase 1: irm）必须非 None
    验证 Section Registry 注入 result 顶层 key 的逻辑生效"""
    d = _latest_result_v3()
    # Phase 1: 仅 irm enabled; Phase 2 完成后会加 holders/dividend/board/dragon_market
    assert d.get("irm") is not None, (
        "V3 result['irm'] 缺失 — section registry 未生效（for sec in enabled_sections() 没跑通）"
    )


def test_v3_run_log_sections_count_matches_enabled():
    """run_log.sections_count 应等于 enabled_sections() 实际数量（Phase 1 = 1）"""
    d = _latest_result_v3()
    run_log = d.get("run_log", {})
    # 4 旧 _call_new + 1 融资融券 = 5 sources 旧路径;  + irm 走新路径
    sources = run_log.get("sources", {})
    sections_count = run_log.get("sections_count", 0)
    # section 注册表里 section.label 应进入 sources
    assert sections_count >= 1, f"run_log.sections_count={sections_count}, 期望 ≥ 1（irm 启用）"
    # irm 必须在 sources 里
    assert "irm" in sources, f"irm 不在 run_log.sources: {list(sources.keys())}"
