"""因子数据源状态 → 报告缺失标注 (2026-09-22, 因子缺失显式标注整改)。

背景: 数据源失败时 v2 打分沿用中性兜底分 (典型: 申万表加载失败 → sw_stability=5),
但此前报告/CLI 均未标注, 读者会把 mock 兜底分误认为真实评分。

本模块只做"判定 + 文案", 不改任何打分逻辑 (历史报告可比性不动):
- factor_notes_from_sources(run_log_sources, score): MD/HTML 渲染用
  (run_log.sources 状态串以 "error:" / "fallback:" 开头 → 该因子标缺失)
- factor_notes_from_data(result_like, score): v2 CLI 因子明细打印用
  (无 run_log 场景, 直接按数据字段判定, 口径与
   analysis.orchestration.source_status._record_v2_source_statuses 对齐)
- cli_note(factor_key, notes): CLI 行内后缀

注意: 本模块可被顶层模块 quant_analyzer_v2 以 `analytics.factor_status`
路径导入 (analysis/ 在 sys.path), 因此内部不得 import analysis.* 包路径。
"""

# 10 因子 key → (中文名, run_log sources 标签, result 数据字段)
# sources 标签与 analysis.orchestration.legacy_bridge._FIELD_OF 一致
FACTOR_SOURCES = {
    "trend":            ("趋势",     "行情",         "quote"),
    "valuation":        ("估值",     "估值一致预期", "valuation"),
    "valuation_pctile": ("估值分位", "估值历史分位", "valuation_hist"),
    "capital":          ("资金",     "当日资金流",   "fund"),
    "momentum":         ("动量",     "行情",         "quote"),
    "sentiment":        ("情绪",     "概念板块",     "blocks"),
    "risk":             ("风险",     "解禁日历",     "lockup"),
    "chip":             ("筹码",     "筹码K线",      "chip_data"),
    "sw_stability":     ("申万稳定", "申万分类",     "sw_data"),
    "dragon":           ("龙虎榜",   "龙虎榜",       "dragon"),
}

# 标注文案模板 (X = 实际计入的兜底分)
NOTE_TEMPLATE = "⚠数据缺失，按中性 {x} 分计入"


def _is_degraded_status(status) -> bool:
    """run_log.sources 状态串: error: / fallback: 开头视为缺失/兜底。"""
    s = str(status or "")
    return s.startswith("error:") or s.startswith("fallback:")


def factor_notes_from_sources(sources, score) -> dict:
    """run_log sources 状态 → {factor_key: 标注文案} (MD/HTML 渲染用)。

    只标注 error/fallback 的源; ok 或源记录缺失 (老 result JSON) 不标注。
    """
    notes = {}
    sources = sources if isinstance(sources, dict) else {}
    score = score if isinstance(score, dict) else {}
    for key, (_cn, src_label, _field) in FACTOR_SOURCES.items():
        if _is_degraded_status(sources.get(src_label)):
            notes[key] = NOTE_TEMPLATE.format(x=score.get(key, "?"))
    return notes


def _data_field_degraded(field, data) -> bool:
    """数据字段级缺失/兜底判定 (与 source_status._record_v2_source_statuses 同口径)。"""
    if field == "blocks":
        # 概念板块: list; 空表 = fallback(接口返回0条, 可能风控); 元素带 error = error
        if isinstance(data, list):
            if not data:
                return True
            return any(isinstance(it, dict) and "error" in it for it in data)
        return True  # 非 list = 未拉取/异常
    if not isinstance(data, dict) or not data:
        return True  # 未拉取 / 空 dict (v2 打分走 else 分支按中性计)
    if "error" in data:
        return True
    # fallback: 当日无成交或分钟数据
    return bool(field == "fund" and not data.get("klines"))


def factor_notes_from_data(result_like, score) -> dict:
    """result/字段 dict → {factor_key: 标注文案} (v2 CLI 因子明细打印用)。"""
    notes = {}
    result_like = result_like if isinstance(result_like, dict) else {}
    score = score if isinstance(score, dict) else {}
    for key, (_cn, _src_label, field) in FACTOR_SOURCES.items():
        if _data_field_degraded(field, result_like.get(field)):
            notes[key] = NOTE_TEMPLATE.format(x=score.get(key, "?"))
    return notes


def cli_note(factor_key, notes) -> str:
    """CLI 因子明细行内后缀: 有缺失返回 ' (⚠数据缺失，按中性 X 分计入)', 否则空串。"""
    n = (notes or {}).get(factor_key)
    return f" ({n})" if n else ""


def notes_summary(notes) -> str:
    "{factor_key: 文案} → '申万稳定: ⚠数据缺失，按中性 5 分计入； …' (HTML 脚注用)。"
    parts = []
    for key, note in (notes or {}).items():
        cn = FACTOR_SOURCES.get(key, (key,))[0]
        parts.append(f"{cn}: {note}")
    return "；".join(parts)
