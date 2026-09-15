"""Scoring-breakdown business semantics.

Extracted from ``analysis.pipeline`` in Phase 1D. Keep the existing five-group
aggregation, neutral fallbacks, clamping rules, labels, and total contract
unchanged while moving the responsibility out of orchestration.
"""

# 把 V2 10 维评分聚合成 5 维, 让总评分不再是黑盒 (技术/资金/估值/情绪/风险)
# 满分 = 100, 与综合评分 total 口径一致
# - tech:      trend(12) + momentum(8) + chip(8)             = 28
# - capital:   capital(15) + dragon(10)                      = 25
# - valuation: valuation(15) + valuation_pctile(8) + sw_stability(6) = 29
# - sentiment: sentiment(8)                                  = 8
# - risk:      risk(10)                                      = 10
# - total:     28 + 25 + 29 + 8 + 10 = 100
# 缺失子维: 按 50% 满分 (中性), 在 dims 标 None 便于报告层标注
# 5 维 dict 的 key 顺序固定 (按报告渲染顺序, 不可乱)
_SCORING_BREAKDOWN_GROUPS = (
    ("tech", "技术", ("trend", "momentum", "chip")),
    ("capital", "资金", ("capital", "dragon")),
    ("valuation", "估值", ("valuation", "valuation_pctile", "sw_stability")),
    ("sentiment", "情绪", ("sentiment",)),
    ("risk", "风险", ("risk",)),
)

# 子维 → 满分 (与 quant_analyzer_v2.compute_quant_score_v2 的 max(0, min(.., max_dim)) 一致)
_SCORE_DIM_MAX = {
    "trend": 12,
    "valuation": 15,
    "valuation_pctile": 8,
    "capital": 15,
    "momentum": 8,
    "sentiment": 8,
    "risk": 10,
    "chip": 8,
    "sw_stability": 6,
    "dragon": 10,
}


def _build_scoring_breakdown(score: dict) -> dict:
    """V2 10 维 score → 5 维聚合 (痛 7 修法, 批次 C)。

    输入: quant_analyzer_v2.compute_quant_score_v2 返回的 score dict
          (含 trend/valuation/valuation_pctile/capital/momentum/sentiment/
           risk/chip/sw_stability/dragon/total/factors/change_pct)
    输出: 5 维 dict + total
          {
            "tech":      {"score": int, "max": 28, "pct": float, "dims": {trend: 1, momentum: 1, chip: 4}},
            "capital":   {"score": int, "max": 25, "pct": float, "dims": {capital: 7, dragon: 3}},
            "valuation": {"score": int, "max": 29, "pct": float, "dims": {valuation: 2, valuation_pctile: 3, sw_stability: 5}},
            "sentiment": {"score": int, "max": 8,  "pct": float, "dims": {sentiment: 4}},
            "risk":      {"score": int, "max": 10, "pct": float, "dims": {risk: 4}},
            "total":     {"score": 34, "max": 100, "pct": 34.0},
          }
    兜底:
      - score 缺失/None → 按 50% 满分 (中性计), 在 dims 标 None
      - 子维负数或 > max → clamp 到 [0, max]
      - 5 维之和应 ≈ score.total (允许 ±2 误差, 详见 _verify_breakdown_consistency)
    """
    breakdown = {}
    for key, label, sub_dims in _SCORING_BREAKDOWN_GROUPS:
        grp_score = 0
        grp_max = 0
        grp_dims = {}
        for d in sub_dims:
            mx = _SCORE_DIM_MAX[d]
            grp_max += mx
            raw = score.get(d) if isinstance(score, dict) else None
            if raw is None:
                # 缺失子维: 按 50% 满分中性计, dims 标 None
                grp_dims[d] = None
                grp_score += mx * 0.5
            else:
                try:
                    v = float(raw)
                except (TypeError, ValueError):
                    v = mx * 0.5
                    grp_dims[d] = None
                else:
                    v = max(0, min(v, mx))
                    grp_dims[d] = round(v, 1)
                grp_score += v
        pct = round(grp_score / grp_max * 100, 1) if grp_max else 0.0
        breakdown[key] = {
            "label": label,
            "score": round(grp_score, 1),
            "max": grp_max,
            "pct": pct,
            "dims": grp_dims,
        }
    # 顶层 total: 用 score["total"] 兜底 (即真实算分), 满分 100
    raw_total = score.get("total") if isinstance(score, dict) else None
    try:
        total_v = round(float(raw_total), 1) if raw_total is not None else None
    except (TypeError, ValueError):
        total_v = None
    total_max = sum(_SCORE_DIM_MAX.values())  # 100
    breakdown["total"] = {
        "label": "综合",
        "score": total_v if total_v is not None else 0,
        "max": total_max,
        "pct": round((total_v or 0) / total_max * 100, 1) if total_v is not None else 0.0,
    }
    return breakdown
