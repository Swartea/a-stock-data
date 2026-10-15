"""Render offline Market Snapshot JSON as a self-contained HTML page."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from typing import Any


def _text(value: Any, fallback: str = "未知") -> str:
    return fallback if value is None or value == "" else html.escape(str(value), quote=True)


def _number(value: Any, suffix: str = "") -> str:
    if not _is_number(value):
        return "不可用"
    return f"{html.escape(str(value), quote=True)}{suffix}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _state(observation: Mapping[str, Any]) -> tuple[str, str]:
    availability = observation.get("availability", "unknown")
    if availability == "unavailable":
        return "不可用", "unavailable"
    if availability == "delayed" or observation.get("freshness") == "stale":
        return "延迟", "delayed"
    if availability != "available":
        return "未知", "unknown"
    change = observation.get("change")
    if not _is_number(change):
        return "持平/涨跌未知", "unknown"
    if change > 0:
        return "上涨", "positive"
    if change < 0:
        return "下跌", "negative"
    return "持平", "unchanged"


def _evidence(evidence: Any) -> str:
    if not isinstance(evidence, list) or not evidence:
        return '<p class="muted">暂无可用证据记录。</p>'
    rows = []
    for item in evidence:
        item = _mapping(item)
        provider = _mapping(item.get("provider"))
        quality = _mapping(item.get("quality"))
        time = _mapping(item.get("time"))
        raw_flags = quality.get("quality_flags", [])
        flags = ", ".join(map(str, raw_flags)) if isinstance(raw_flags, list) else "无"
        flags = flags or "无"
        rows.append(
            "<li><strong>{}</strong> · 指标 {} · 观测值 {} · 来源 {} ({}) · 数据时点 {} · "
            "抓取时点 {} · 新鲜度 {} · 完整性 {} · 质量标记 {} · PIT {}</li>".format(
                _text(item.get("evidence_id")),
                _text(item.get("metric")),
                _number(item.get("observation")),
                _text(provider.get("display_name")),
                _text(provider.get("provider_id")),
                _text(time.get("data_as_of")),
                _text(time.get("fetched_at")),
                _text(quality.get("freshness")),
                _text(quality.get("completeness")),
                _text(flags),
                _text(item.get("pit_status")),
            )
        )
    return "<ul>" + "".join(rows) + "</ul>"


def render_market_snapshot(record: dict[str, Any]) -> str:
    """Return deterministic responsive HTML for every scenario in a snapshot record."""
    if not isinstance(record, Mapping):
        raise ValueError("snapshot record must be an object")
    scenarios = record.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("snapshot record must contain a scenarios list")
    cards: list[str] = []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("snapshot scenarios must contain only objects")
        snapshot = _mapping(scenario.get("snapshot"))
        observation = _mapping(snapshot.get("observation"))
        state_label, state_class = _state(observation)
        provider = observation.get("provider")
        degraded = observation.get("degraded") is True
        attempts = scenario.get("provider_attempts", [])
        attempt_text = " → ".join(
            f"{_mapping(attempt).get('provider') or '未知'}: "
            f"{_mapping(attempt).get('status') or '未知'}"
            for attempt in attempts if isinstance(attempt, Mapping)
        ) if isinstance(attempts, list) else ""
        attempt_text = attempt_text or "无提供方尝试记录"
        change = observation.get("change")
        percent = observation.get("change_percent")
        change_text = _number(change)
        if _is_number(change) and change > 0:
            change_text = "+" + change_text
        percent_text = _number(percent, "%")
        if _is_number(percent) and percent > 0:
            percent_text = "+" + percent_text
        cards.append(
            '<article class="scenario"><header><div><p class="eyebrow">场景</p>'
            '<h2>{}</h2></div><span class="state {}">{}</span></header>'
            '<div class="index"><h3>{}</h3><p class="identity">{}</p></div>'
            '<dl class="metrics"><div><dt>收盘</dt><dd>{}</dd></div>'
            '<div><dt>涨跌</dt><dd>{}</dd></div><div><dt>涨跌幅</dt><dd>{}</dd></div>'
            '<div><dt>数据交易日</dt><dd>{}</dd></div></dl>'
            '<p class="badges"><span>提供方：{}</span>{}<span>可用性：{}</span>'
            '<span>新鲜度：{}</span></p><p class="reason">{}</p>'
            '<details><summary>证据与来源尝试</summary><p>提供方尝试：{}</p>{}</details></article>'.format(
                _text(scenario.get("id")), state_class, state_label,
                _text(observation.get("name")), _text(observation.get("identity")),
                _number(observation.get("close")), change_text, percent_text,
                _text(observation.get("data_date"), "暂无数据"), _text(provider),
                '<span class="degraded">降级回退</span>' if degraded else "",
                _text(observation.get("availability")), _text(observation.get("freshness")),
                _text(observation.get("reason"), "无异常说明"), _text(attempt_text),
                _evidence(observation.get("evidence")),
            )
        )
    title = "A股市场快照"
    snapshots = [
        scenario.get("snapshot")
        for scenario in scenarios
        if isinstance(scenario, dict) and isinstance(scenario.get("snapshot"), dict)
    ]

    def snapshot_value(key: str) -> Any:
        values = [snapshot[key] for snapshot in snapshots if snapshot.get(key) not in (None, "")]
        if not values:
            return "unknown"
        if any(value != values[0] for value in values[1:]):
            return "各场景不同"
        return values[0]

    market = snapshot_value("market")
    status = snapshot_value("trading_day_status")
    snapshot_id = snapshot_value("snapshot_id")
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><title>{title}</title><style>
:root{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#17252b;background:#f3f6f4;font-synthesis:none}}
*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1000px;margin:auto;padding:clamp(1rem,4vw,2.5rem)}}
.hero{{background:#123e3a;color:#fff;padding:clamp(1.25rem,4vw,2rem);border-radius:1rem;margin-bottom:1.2rem}}
h1{{font-size:clamp(1.6rem,5vw,2.5rem);margin:.2rem 0 .5rem}}h2{{font-size:1.15rem;overflow-wrap:anywhere;margin:.2rem 0}}
.hero p,.eyebrow,.identity,.muted{{color:#bdcfca}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr));gap:1rem}}
.scenario{{background:#fff;border:1px solid #dce5e0;border-radius:1rem;padding:1.2rem;box-shadow:0 5px 20px #193d3210;min-width:0}}
.scenario header{{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start}}.eyebrow{{font-size:.75rem;text-transform:uppercase;margin:0}}
.state,.degraded,.badges span{{display:inline-block;border:1px solid #cbd5d1;border-radius:99px;padding:.25rem .6rem;font-size:.82rem}}
.positive{{color:#12633d}}.negative{{color:#a52d30}}.unchanged{{color:#39464d}}.delayed{{color:#875400}}.unavailable{{color:#8c3030}}.unknown{{color:#555f66}}
.index{{border-top:1px solid #e7ece9;margin-top:1rem;padding-top:.5rem}}h3{{margin:.5rem 0 0;font-size:1.35rem}}.identity{{margin:.2rem 0;color:#62716d;font-size:.85rem;overflow-wrap:anywhere}}
.metrics{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.7rem;margin:1rem 0}}.metrics div{{background:#f5f8f6;padding:.75rem;border-radius:.65rem;min-width:0}}
dt{{color:#63716c;font-size:.8rem}}dd{{margin:.25rem 0 0;font-weight:650;overflow-wrap:anywhere}}.badges{{display:flex;flex-wrap:wrap;gap:.4rem}}
.degraded{{color:#765000;border-color:#d7bd78}}.reason{{overflow-wrap:anywhere;color:#5e6b67}}details{{border-top:1px solid #e7ece9;padding-top:.75rem;margin-top:.9rem}}
summary{{cursor:pointer;font-weight:600}}li{{margin:.45rem 0;overflow-wrap:anywhere;line-height:1.55}}footer{{color:#66736e;font-size:.85rem;padding:1.2rem .2rem}}
.legend{{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1rem}}.legend span{{border:1px solid #cbd5d1;border-radius:99px;padding:.3rem .65rem;font-size:.85rem}}
@media(max-width:520px){{main{{padding:.8rem}}.scenario{{padding:1rem}}.metrics{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main><header class="hero"><p>离线合成服务输出 · {eval_time}</p><h1>{title}</h1>
<p>市场：{market}　·　市场日历状态：{trading_status}　·　快照 ID：{snapshot_id}</p>
<p>涨跌状态同时以文字和符号信息表达；颜色仅作辅助。数据日期由数据源证据提供。</p></header>
<section class="legend" aria-label="状态示例"><span class="positive">上涨 ↑</span><span class="negative">下跌 ↓</span><span class="unchanged">持平 →</span><span class="delayed">延迟</span><span class="unavailable">不可用</span><span class="unknown">未知</span></section>
<section class="grid" aria-label="市场指数快照">{cards}</section>
<footer>记录版本 {schema_version} · {source_inputs}</footer></main></body></html>
""".format(
        title=html.escape(title), eval_time=_text(record.get("evaluation_time")),
        market=_text(market), trading_status=_text(status),
        snapshot_id=_text(snapshot_id),
        cards="".join(cards), schema_version=_text(record.get("schema_version")),
        source_inputs=_text(record.get("source_inputs")),
    )


def load_snapshot_json(raw: str) -> dict[str, Any]:
    """Parse JSON input and ensure the root is an object."""
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("snapshot JSON root must be an object")
    return result
