"""analysis/ fetcher 调度器 (P2-A Phase 4 Task 4.2, 2026-09-13)

按规范 §2 采集层 + P0-B fetcher 状态契约 (§4), 把 V3 主文件 4 个独立 fetcher
(公告/财务/研报/新闻) 软导入 + 状态总线抽到 fetcher_dispatcher.py:
- 软导入容错: import 失败不崩整脚本 (V3 历史上这一段就是 fallback 链)
- 4 fetcher 入口统一: NEW_FETCHERS 字典 (label -> {ok, err, fn})
- 向后兼容: v3 顶层 `from analysis.fetcher_dispatcher import _NEW_IMPORTS` (别名)

§1 '不修改业务口径' — 软导入顺序/异常处理/字典结构照搬, 仅搬位置。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional


# ============================================================
# 4 个独立 fetcher 软导入 (P0-B §4 容错接入 + Phase 1 7-task plan 入仓)
# ============================================================
NEW_FETCHERS: Dict[str, Dict[str, Any]] = {
    # label -> {"ok": bool, "err": str, "fn": callable}
    "公告":    {"ok": False, "err": "", "fn": None},
    "财务":    {"ok": False, "err": "", "fn": None},
    "研报":    {"ok": False, "err": "", "fn": None},
    "新闻":    {"ok": False, "err": "", "fn": None},
}

# 4 独立 fetcher 文件均在 analysis/ 同级目录, 软导入容错
# (历史原因: 这些模块在 analysis/ 下与 v3 同级, V3 主分析器在 runtime 才 import,
#  因此 4 个模块可独立演化/未到位时 V3 仍能跑)
try:
    from analysis.fetch_announcements import fetch_announcements as _fn_ann
    NEW_FETCHERS["公告"]["ok"], NEW_FETCHERS["公告"]["fn"] = True, _fn_ann
except Exception as e:  # noqa: BLE001
    NEW_FETCHERS["公告"]["err"] = f"数据源暂缺: {e}"
try:
    from analysis.fetch_finance_summary import fetch_finance_summary as _fn_fin
    NEW_FETCHERS["财务"]["ok"], NEW_FETCHERS["财务"]["fn"] = True, _fn_fin
except Exception as e:  # noqa: BLE001
    NEW_FETCHERS["财务"]["err"] = f"数据源暂缺: {e}"
try:
    from analysis.fetch_research_reports import fetch_research_reports as _fn_res
    NEW_FETCHERS["研报"]["ok"], NEW_FETCHERS["研报"]["fn"] = True, _fn_res
except Exception as e:  # noqa: BLE001
    NEW_FETCHERS["研报"]["err"] = f"数据源暂缺: {e}"
try:
    from analysis.fetch_news_em import fetch_news_em as _fn_news
    NEW_FETCHERS["新闻"]["ok"], NEW_FETCHERS["新闻"]["fn"] = True, _fn_news
except Exception as e:  # noqa: BLE001
    NEW_FETCHERS["新闻"]["err"] = f"数据源暂缺: {e}"


# 别名 (兼容老调用 _NEW_IMPORTS)
_NEW_IMPORTS = NEW_FETCHERS


# ============================================================
# 工具: 调用 fetcher + 状态分类
# ============================================================
def call_fetcher(label: str, *args, **kwargs) -> Optional[Dict[str, Any]]:
    """统一调用入口: 走 NEW_FETCHERS[label]["fn"], 失败返回 None (不抛).

    用法:
        r = call_fetcher("公告", code)
        if r and "error" not in r:
            ...
    """
    spec = NEW_FETCHERS.get(label)
    if not spec or not spec.get("ok") or not spec.get("fn"):
        return None
    try:
        return spec["fn"](*args, **kwargs)
    except Exception:  # noqa: BLE001
        return None


def get_fetcher_status(label: str) -> Dict[str, Any]:
    """读 fetcher 状态 (ok/err/fn), 给 run_log.sources 用."""
    return NEW_FETCHERS.get(label, {"ok": False, "err": "未知 label", "fn": None})


def list_ok_fetchers() -> list[str]:
    """列出已成功 import 的 fetcher label, 给 §7 报告首页用."""
    return [label for label, spec in NEW_FETCHERS.items() if spec.get("ok")]


def list_failed_fetchers() -> list[str]:
    """列出 import 失败的 fetcher label, 给 §7 报告首页用."""
    return [label for label, spec in NEW_FETCHERS.items() if not spec.get("ok")]
