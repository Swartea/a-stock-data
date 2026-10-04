"""golden result_v3 fixture 生成器 + 加载器 (Phase 1H 验收补齐)

背景
----
`tests/test_scoring_breakdown.py` 与 `tests/test_three_levels.py` 里有一批
"golden-file" 端到端测试, 它们按 `reports/<code>_<name>/<date>/result_v3-<HHMM>.json`
去找**历史跑批产物**。CI 的 pytest 矩阵 job 里 `reports/` 只有 `.gitkeep`,
所以这批测试在矩阵里 100% skip —— docs/10 的 Phase 1H 验收规则
("Ubuntu 3.10/3.11/3.12 + macOS 3.12 Pytest 全绿") 实际上没有覆盖 result_v3 契约。

本模块把"仓库内已存在的真实证据"固化成**版本化的 golden fixture**,
让这批测试在 CI 里真正跑起来, 而不是 skip。

三类 fixture 的可确定性不一样, 必须分清:

| 代码 | 证据来源 | 性质 | 可确定性 |
|------|----------|------|----------|
| 600693 | 本仓库 `reports/600693_东百集团/2026-10-03/result_v3-1618.json` 真实跑批产物 | **capture** (裁剪+归一) | 完全确定 |
| 002353 | 仓库内文档与测试中已记录的标量 | **curation** (按证据拼装) | 完全确定 (无 K 线, 不可重算技术位) |
| 002353 / 600693 / 605162 精确值基线 | 2026-09-12 / 2026-09-11 真实跑批 K 线序列 | **缺失** | 不可得 —— 见 `README.md` |

硬约束
------
1. **不使用网络 / 实时行情**, 不新造市场数据。
2. **不落盘生成的 PDF/报告**: `_files` / `pdf_*` / `artifacts.sizes_bytes` /
   任何绝对路径都在归一化阶段剥掉。
3. 生成的 JSON 必须 **byte-stable**: `sort_keys=True` + 固定 indent + 末尾换行。
4. 裁剪掉的字段必须在 `README.md` 里有出处说明, 不允许静默丢弃。

重新生成
--------
    python tests/fixtures/golden/golden_fixtures.py

600693 fixture 依赖 `reports/` 下的真实产物 (默认已被 .gitignore 排除),
缺失或被改动时生成器会 **fail loud** 并打印期望的 sha256, 不会静默重造。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

GOLDEN_DIR = Path(__file__).resolve().parent
WORKDIR = GOLDEN_DIR.parents[2]

# 600693 真实跑批产物 (capture 源)。该文件在 reports/ 下, 属未追踪的本地产物,
# 因此这里同时钉住 sha256: 产物被重跑/改动后生成器会拒绝覆盖, 防止 golden 基线
# 在无人察觉的情况下被"刷新成另一份数据"。
SOURCE_600693 = WORKDIR / "reports/600693_东百集团/2026-10-03/result_v3-1618.json"
SOURCE_600693_SHA256 = "609708186c3e26894484223d477b7a788c6d18180d28e55f9e93cb273b08d177"

# ---------------------------------------------------------------------------
# 600693: 保留的顶层键 (白名单)
# ---------------------------------------------------------------------------
# 选取原则 = "渲染层/契约层真正读到的键" + "稳定语义"。被裁掉的键见 README。
KEEP_600693 = (
    # 身份与结论
    "code", "name", "report_date", "advice", "emoji", "detail",
    "deliverable_status",
    # 行情 / 估值 / 评分 (10 因子原值)
    "quote", "valuation", "score",
    # 交易计划与三价位 (批次 D/E 修法产物)
    "trading_plan", "three_levels", "signals",
    # 板块 / 筹码 / 宏观
    "fund", "lockup", "dragon", "sw_data", "chip_data", "macro", "blocks",
    # 估值分位 (只留标量分位, 丢掉 2 万行级时间序列)
    "valuation_hist",
    # 4 个 _call_new + 3 个 supplement + section registry (result_v3 契约键集)
    "announcements", "finance", "news", "research",
    "margin", "margin_hist", "peers", "fund_daily5",
    "irm", "holders", "dividend", "board", "dragon_market",
    # 编排可观测性 (run_log 会剥离时间轴, 保留 sources/guard/sections_count)
    "run_log",
)

# 嵌套裁剪: 键 -> 要丢弃的子键 (大体量 / 可重算的日期序列)
DROP_NESTED: Dict[str, List[str]] = {
    # 180 根 baostock 前复权 OHLCV 序列; 正是精确值三价位基线缺失的那份数据,
    # 故意不落到 golden 里, 以免有人误以为可以拿它当精确基线。
    "chip_data": ["kline"],
    # PE/PB/close 历史序列 (报告渲染不需要原始序列, 只需要分位标量)
    "valuation_hist": ["pe_series", "pb_series", "close_series"],
}

# 会被整体剥离的顶层键: 落盘产物引用 / 本机路径 / PDF 渲染器错误串
DROP_TOP_LEVEL_600693 = ("_files", "pdf_path", "pdf_status", "scoring_breakdown")

# 时点说明 (诚实边界, 别把 fixture 说成"渲染全确定"):
# - "生成时间"行由 run_log.finished_at 喂给 fmt_gen_time (report_md.py:346),
#   该值来自 fixture → 这一行是确定的。
# - 但 report_md.py:313 另有 `now = datetime.now().strftime("%Y-%m-%d %H:%M")`,
#   并在 :698 / :1283 作为 "数据时点 {now}" 页脚直接打印 → **活墙钟**。
#   所以 golden fixture 只保证 JSON 字节确定, 不保证渲染出的 Markdown 逐字节确定。
#   golden 用例断言的是结构 (章节/列数/守恒), 不依赖该页脚, 因此不受影响。
#   本文件不冻结该值, 也不改 report_md 行为。

# run_log 里整体剥离的块。该块只记录"生成了哪些文件 / 多大 / Chrome 与
# LibreOffice 报了什么" —— 即落盘产物元数据。report_md / html_report_v3 都不读
# 它 (只由 pipeline 写), 剥掉不损失任何渲染覆盖, 同时满足"不落盘生成的
# PDF/报告"这条硬约束 (它含 Chrome 本机绝对路径与产物字节数)。
DROP_RUN_LOG_BLOCKS = ("artifacts",)

# 状态串尾部的 ", 1716ms" 是耗时抖动, 但前缀 ("ok:eastmoney" /
# "fallback:接口返回0条(可能风控)" / "error:申万表加载失败") 是**数据质量证据**,
# 必须保留 —— 报告用它解释降级章节。只刮掉耗时尾巴, 不整条丢。
_MS_TAIL = re.compile(r",\s*\d+(?:\.\d+)?ms\s*$")


# ---------------------------------------------------------------------------
# 002353: 按仓库内已记录标量拼装的 curated fixture
# ---------------------------------------------------------------------------
# 这只票**没有**任何 result_v3 产物落在仓库里。以下每个标量的出处都写在
# EVIDENCE_002353 的注释里, README 有汇总表。缺的一律不补, 不猜。
EVIDENCE_002353: Dict[str, Any] = {
    "code": "002353",
    "name": "杰瑞股份",
    # analysis/references/three-levels-rules.md §六 例子 5: "price = 118.94"
    "report_date": "2026-09-12",
    # advice / emoji: report_md.py:397 对这两个键是**硬索引** (`r['emoji']` /
    # `r['advice']`), 缺键直接 KeyError, 所以不能简单不写。但仓库里没有留存
    # 002353 该次跑批的观测值 —— docs/09 批次 E 痛 3 只记了"改之前的 区间操作"
    # 和改法规则的两个候选 ("轻仓试探" / "观望"), 两者都不是那天的实际输出。
    # 这里落**自述式占位**: 字符串本身就是"未记录"的说明, 既让 MD 可渲染, 又不会
    # 让任何人把推断当成观测到的操作结论 (渲染出来一眼可辨)。
    "advice": "（未记录：002353 该次跑批的 advice 未在仓库留存，见 fixtures/golden/README.md）",
    "emoji": "（未记录）",
    "detail": "002353 golden fixture (curated, 见 tests/fixtures/golden/README.md)",
    "quote": {
        "name": "杰瑞股份",
        "price": 118.94,          # three-levels-rules.md 例子 5
    },
    "valuation": {
        "name": "杰瑞股份",
        "code": "002353",
        "price": 118.94,          # three-levels-rules.md 例子 5
    },
    "valuation_hist": {
        # docs/09 批次 E 痛 3: "杰瑞股份 53 分 vs PE 分位 87.8% 自相矛盾"
        "pe_percentile_3y": 87.8,
    },
    # tests/test_scoring_breakdown.py:117-119 明确标注 "002353" 的真实 10 因子原值
    "score": {
        "trend": 8, "valuation": 10, "valuation_pctile": 6, "capital": 6,
        "momentum": 3, "sentiment": 2, "risk": 8, "chip": 1,
        "sw_stability": 3, "dragon": 6, "total": 53,
        # 因子文案串未在仓库记录 → 留空列表 (MD 会渲染成"无明细"), 不编造。
        # 注意: change_pct / state / template_used 等**未记录**字段一律"缺键",
        # 不写显式 None —— report_md 对这些键走 .get(k, 默认值), 显式 None 会
        # 让 report_md.py:422 的 `change_pct >= 0` 直接 TypeError。
        "factors": [],
    },
    # trading_plan **整体缺键**: 仓库只记录了 002353 的 stop_loss=110.61
    # (three-levels-rules.md 例子 5 / docs/09 批次 D 痛 2), entry_low/entry_high/
    # tp1/tp2/tp3/stop_loss_pct/position/period 全都没有记录。而 report_md.py:636
    # 起对 plan 是**硬索引** (`plan["entry_low"]` … 8 个键), 只填一半会 KeyError。
    # 缺的部分不补 → 整块不落, stop_loss 由 three_levels.stop_loss 承载。
    "three_levels": {
        # tests/test_three_levels.py:585-594 记录的批次 E 修法后期望值
        "support": 108.37,
        "support_op_key": "boll_lower",
        "support_extreme": 104.87,
        "stop_loss": 110.61,
        "stop_loss_method": "trading_plan",
        # resistance / resistance_candidates 无记录 → 缺键 (不写 null)
    },
    # chip_data 必须为**空 dict**, 不能放 {"kline": []}: v2._interpret_chips 只判
    # `if not cd or "error" in cd`, 非空 dict 会硬索引 cd["profit_ratio"] 直接
    # KeyError。002353 的筹码数据 (profit_ratio / peak_price / avg_cost) 仓库里
    # 没有记录 → 整块留空, 与 conftest.rendered_markdown_v3 的兜底口径一致。
    # K 线序列缺失这一事实记录在 README「缺失源数据」, 不在 fixture 里假装有。
    "chip_data": {},
    "signals": {"good": [], "bad": []},
    "blocks": [],
    "fund": {}, "lockup": {}, "dragon": {}, "sw_data": {}, "macro": {},
    "announcements": None, "finance": None, "news": None, "research": None,
    "margin": None, "margin_hist": {}, "peers": {}, "fund_daily5": {},
    "irm": {}, "holders": {}, "dividend": {}, "board": {}, "dragon_market": {},
    "run_log": {
        "sources": {},
        "sections_count": 0,
        "fallback_chain": [],
        "tls_recommendations": [],
        "guard": {"status": "N/A curated fixture"},
        "started_at": "2026-09-12T17:58:00+08:00",
        "finished_at": "2026-09-12T17:58:00+08:00",
        "total_sec": 0,
    },
}


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------
def _strip_local_paths(obj: Any) -> Any:
    """递归剔除任何含仓库绝对路径的字符串 (落盘产物引用 / 本机泄漏)。"""
    if isinstance(obj, str):
        if str(WORKDIR) in obj or obj.startswith("/Users/") or obj.startswith("/home/"):
            return None
        return obj
    if isinstance(obj, list):
        return [_strip_local_paths(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_local_paths(v) for k, v in obj.items()}
    return obj


def _scrub_ms(value: Any) -> Any:
    """剥掉状态串尾部的耗时 (", 1716ms"), 保留 ok/fallback/error 语义。"""
    if isinstance(value, str):
        return _MS_TAIL.sub("", value)
    return value


def _normalize_source_meta(meta: Any) -> Any:
    """source_meta: 保留 status/detail 语义, 剥掉 ms 数值键。"""
    if not isinstance(meta, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, val in meta.items():
        if isinstance(val, dict):
            val = {k: _scrub_ms(v) for k, v in val.items()}
            val.pop("ms", None)
        else:
            val = _scrub_ms(val)
        out[key] = val
    return out


def build_golden_600693(source: Optional[Path] = None) -> Dict[str, Any]:
    """从真实跑批产物裁剪出 600693 golden fixture。"""
    src = source or SOURCE_600693
    if not src.exists():
        raise FileNotFoundError(
            f"600693 golden 的 capture 源不存在: {src}\n"
            "该文件是 reports/ 下的本地产物 (未追踪)。请先跑一次 "
            "`python analysis/quant_analyzer_v3.py 600693 东百集团`, "
            "或手动调整 SOURCE_600693 / SOURCE_600693_SHA256。\n"
            "本模块不会凭空构造行情数据。"
        )
    raw = json.loads(src.read_text(encoding="utf-8"))

    out: Dict[str, Any] = {}
    for key in KEEP_600693:
        if key in raw:
            out[key] = raw[key]

    for container, drop_keys in DROP_NESTED.items():
        if isinstance(out.get(container), dict):
            for dk in drop_keys:
                out[container].pop(dk, None)

    for key in DROP_TOP_LEVEL_600693:
        out.pop(key, None)

    run_log = out.get("run_log")
    if isinstance(run_log, dict):
        for key in DROP_RUN_LOG_BLOCKS:
            run_log.pop(key, None)
        for bucket in ("sources", "supplements"):
            if isinstance(run_log.get(bucket), dict):
                run_log[bucket] = {k: _scrub_ms(v) for k, v in run_log[bucket].items()}
        run_log["source_meta"] = _normalize_source_meta(run_log.get("source_meta"))

    out = _strip_local_paths(out)

    # 固定时点下 report_md.fmt_gen_time 拿得到确定值, 不依赖 datetime.now()
    out.setdefault("report_date", "2026-10-03")
    return out


def build_golden_002353() -> Dict[str, Any]:
    """002353 curated fixture (无 capture 源, 全部标量带出处)。"""
    return json.loads(json.dumps(EVIDENCE_002353, ensure_ascii=False))


def dump(obj: Dict[str, Any]) -> str:
    """byte-stable 序列化: sort_keys + 固定缩进 + 末尾换行。"""
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def golden_path(code: str) -> Optional[Path]:
    """代码 → golden fixture 路径; 该票没有 golden 时返回 None。"""
    mapping = {
        "600693": GOLDEN_DIR / "result_v3-600693-20261003.json",
        "002353": GOLDEN_DIR / "result_v3-002353-20260912.json",
    }
    return mapping.get(code)


def load_golden_result(code: str) -> Optional[Dict[str, Any]]:
    """读取某票的 golden fixture; 不存在返回 None (调用方自行 skip / 回落)。"""
    p = golden_path(code)
    if p is None or not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_capture_source() -> Optional[str]:
    """校验 capture 源指纹。返回 None = 通过; 返回字符串 = 失败原因。

    必须在**任何写盘之前**跑: 否则源漂移会先被裁剪成 golden 覆盖掉基线,
    等于用一份来路不明的产物静默改写已版本化的 fixture。
    """
    if not SOURCE_600693.exists():
        return (
            f"capture 源不存在: {SOURCE_600693}\n"
            "该文件是 reports/ 下的本地产物 (未追踪)。请先跑 "
            "`python analysis/quant_analyzer_v3.py 600693 东百集团`, "
            "或手动调整 SOURCE_600693 / SOURCE_600693_SHA256。\n"
            "本模块不会凭空构造行情数据。"
        )
    actual = sha256_of(SOURCE_600693)
    if actual != SOURCE_600693_SHA256:
        return (
            f"capture 源 sha256 漂移, 拒绝生成:\n"
            f"  期望 {SOURCE_600693_SHA256}\n"
            f"  实际 {actual}\n"
            f"  源文件 {SOURCE_600693}\n"
            "请人工确认后再更新 SOURCE_600693_SHA256 (或换回原产物)。"
        )
    return None


def main(argv: Optional[List[str]] = None) -> int:
    """生成 golden fixture。

    退出码:
      0  全部写盘成功 / 或已是最新 (no-op)
      1  capture 源漂移或缺失 —— 在任何写盘之前失败
      2  已存在基线与本次生成结果不一致 —— **不写盘**; 需要显式 --force 才更新

    初始创建 (目标文件不存在) 始终允许。只有"已存在的基线被改写"才需要 --force。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    force = "--force" in args

    # --- 1. capture 源校验 (先于任何写盘) ---
    src_error = _check_capture_source()
    if src_error:
        print(f"✗ {src_error}", file=sys.stderr)
        return 1

    # --- 2. 构建 ---
    plans: List[tuple] = []
    for code, builder in (("600693", build_golden_600693),
                          ("002353", build_golden_002353)):
        target = golden_path(code)
        assert target is not None
        plans.append((code, target, dump(builder())))

    # --- 3. 已存在基线漂移检测 (仍不写盘) ---
    drifted = [
        (code, target, sha256_of(target),
         hashlib.sha256(payload.encode("utf-8")).hexdigest())
        for code, target, payload in plans
        if target.exists() and target.read_text(encoding="utf-8") != payload
    ]
    if drifted and not force:
        for code, target, on_disk, rebuilt in drifted:
            print(
                f"✗ 已存在基线漂移, 拒绝覆盖: {code} -> {target}\n"
                f"    仓库内基线 sha256 {on_disk}\n"
                f"    本次生成将写入     {rebuilt}",
                file=sys.stderr,
            )
        print(
            "已存在基线不会被自动改写。确认要更新请显式加 --force "
            "(会改写已版本化 fixture, 请一并复查 README 的出处表)。",
            file=sys.stderr,
        )
        return 2

    # --- 4. 写盘 ---
    written: List[str] = []
    for code, target, payload in plans:
        before = target.read_text(encoding="utf-8") if target.exists() else None
        target.write_text(payload, encoding="utf-8")
        if before is None:
            action = "创建"
        elif before == payload:
            action = "已是最新 (no-op)"
        else:
            action = "覆盖 (--force)"
        written.append(f"{code} -> {target} ({action}, {len(payload)} 字符)")

    print("\n".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
