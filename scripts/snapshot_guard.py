"""债 4 修法 ②：价格快照时点强校验共享库。

强校验规则（梁大锋序列 53/57 拍板）：
- 若 price_snapshot_time 字段缺失 → 阻断抛错（强制阻断，因为缺失意味着无法追溯）
- 若 (now - price_snapshot_time) > 1 小时 → 自动 WARN（不阻断），建议重拉
- pool_meta.json 不存在 → 不阻断但 WARN（标记旧池"时点不可考"）
- 提供 check_csv_snapshot() / check_meta_snapshot() / check_last_bar_today() 三个工具函数
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

SHANGHAI_TZ = timezone(timedelta(hours=8))
WARN_THRESHOLD_HOURS = 1.0


def _now_shanghai() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def _parse_iso(ts: str) -> Optional[datetime]:
    """解析 ISO 8601 时间戳（兼容 +0800 / Z / 无时区三种格式）。"""
    if not ts:
        return None
    ts = ts.strip()
    for candidate in (ts, ts.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=SHANGHAI_TZ)
            return dt
        except ValueError:
            continue
    return None


def check_csv_snapshot(csv_path: Path, code: str = "") -> dict:
    """检查 CSV 文件的 price_snapshot_time 字段。

    返回:
      {
        "ok": bool,              # False 仅当 price_snapshot_time 缺失
        "warn": bool,            # True 当快照超过阈值
        "snapshot_time": str,    # ISO 8601
        "age_hours": float,
        "message": str,
        "block": bool,           # True 时调用方应中止
      }
    """
    import csv as _csv

    if not Path(csv_path).exists():
        return {
            "ok": False,
            "warn": True,
            "block": True,
            "snapshot_time": None,
            "age_hours": None,
            "message": f"CSV 不存在: {csv_path}",
        }

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = _csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if "price_snapshot_time" not in fieldnames:
        return {
            "ok": False,
            "warn": True,
            "block": True,
            "snapshot_time": None,
            "age_hours": None,
            "message": f"CSV 缺 price_snapshot_time 列（旧池或未生成 guard 列）: {csv_path}",
        }

    target_code = str(code).zfill(6) if code else None
    target_row = None
    if target_code:
        for r in rows:
            if str(r.get("代码", "")).zfill(6) == target_code:
                target_row = r
                break
    if target_row is None and rows:
        target_row = rows[0]

    ts_str = (target_row or {}).get("price_snapshot_time", "").strip()
    if not ts_str:
        return {
            "ok": False,
            "warn": True,
            "block": True,
            "snapshot_time": None,
            "age_hours": None,
            "message": f"行级 price_snapshot_time 为空（target={target_code or '默认首行'}）",
        }

    snap_dt = _parse_iso(ts_str)
    if snap_dt is None:
        return {
            "ok": False,
            "warn": True,
            "block": True,
            "snapshot_time": ts_str,
            "age_hours": None,
            "message": f"price_snapshot_time 解析失败: {ts_str}",
        }

    now = _now_shanghai()
    age_hours = (now - snap_dt).total_seconds() / 3600.0
    warn = age_hours > WARN_THRESHOLD_HOURS

    return {
        "ok": True,
        "warn": warn,
        "block": False,
        "snapshot_time": ts_str,
        "age_hours": round(age_hours, 3),
        "message": (
            f"snapshot={ts_str} 距今 {age_hours:.2f}h"
            + ("（>1h，建议重拉）" if warn else "")
        ),
    }


def check_meta_snapshot(meta_path: Path) -> dict:
    """检查 pool_meta.json。

    返回:
      {
        "exists": bool,
        "warn_untrustworthy": bool,  # meta 不存在 → 旧池"时点不可考"
        "snapshot_time": str,
        "message": str,
      }
    """
    if not Path(meta_path).exists():
        return {
            "exists": False,
            "warn_untrustworthy": True,
            "snapshot_time": None,
            "message": f"meta 文件不存在 ({meta_path}) → 旧池标记'时点不可考，禁止用于三价位计算'",
        }

    try:
        meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "exists": False,
            "warn_untrustworthy": True,
            "snapshot_time": None,
            "message": f"meta 文件解析失败: {e}",
        }

    ts_str = meta.get("snapshot_time_iso", "")
    snap_dt = _parse_iso(ts_str) if ts_str else None
    age_hours = None
    warn_age = False
    if snap_dt:
        now = _now_shanghai()
        age_hours = (now - snap_dt).total_seconds() / 3600.0
        warn_age = age_hours > WARN_THRESHOLD_HOURS

    # 兼容"标记不可考"的 meta：snapshot_time_iso=null 但有 status=DEPRECATED_*
    status = meta.get("status", "")
    if status.startswith("DEPRECATED"):
        return {
            "exists": True,
            "warn_untrustworthy": True,
            "snapshot_time": ts_str,
            "age_hours": round(age_hours, 3) if age_hours is not None else None,
            "message": (
                f"meta status={status} → 旧池标记'时点不可考，禁止用于三价位计算'"
                + (f"（reason={meta.get('deprecated_reason', '')[:50]}...）" if meta.get('deprecated_reason') else "")
            ),
        }

    if not ts_str:
        return {
            "exists": True,
            "warn_untrustworthy": True,
            "snapshot_time": None,
            "age_hours": None,
            "message": "meta 存在但 snapshot_time_iso 为空 → 时点不可考",
        }

    return {
        "exists": True,
        "warn_untrustworthy": warn_age,
        "snapshot_time": ts_str,
        "age_hours": round(age_hours, 3) if age_hours is not None else None,
        "message": (
            f"meta snapshot={ts_str} 距今 {age_hours:.2f}h"
            + ("（>1h 告警）" if warn_age else "")
        ),
    }


def check_last_bar_today(last_bar_date: str, today: Optional[str] = None) -> dict:
    """债 4 修法 ③：校验 K 线最后 bar 是否为当日。

    返回:
      {
        "ok": bool,            # True 当 last_bar_date == today
        "block": bool,         # True 当 last_bar_date < today（阻断）
        "last_bar": str,
        "today": str,
        "message": str,
      }

    若 last_bar_date > today：仅 WARN（A 股不会发生，常见于数据源返回异常日期）
    若 last_bar_date == today：OK
    若 last_bar_date < today：BLOCK（必须降级腾讯 / 腾讯仍失败即停止）
    """
    if today is None:
        today = _now_shanghai().strftime("%Y-%m-%d")

    if not last_bar_date:
        return {
            "ok": False,
            "block": True,
            "last_bar": None,
            "today": today,
            "message": "last_bar_date 为空",
        }

    if last_bar_date == today:
        return {
            "ok": True,
            "block": False,
            "last_bar": last_bar_date,
            "today": today,
            "message": f"last_bar={last_bar_date} == today={today} ✅",
        }

    if last_bar_date < today:
        return {
            "ok": False,
            "block": True,
            "last_bar": last_bar_date,
            "today": today,
            "message": (
                f"last_bar={last_bar_date} < today={today}（陈旧数据）"
                "→ 必须降级腾讯 / 腾讯仍非当日/空/错 → 立即停止，禁止用 screener_pool.csv 陈旧价兜底"
            ),
        }

    return {
        "ok": False,
        "block": False,
        "last_bar": last_bar_date,
        "today": today,
        "message": f"last_bar={last_bar_date} > today={today}（数据源返回异常日期，WARN）",
    }


def emit(result: dict, file=sys.stderr) -> None:
    """统一打印告警/阻断信息。"""
    if result.get("block"):
        print(f"[snapshot_guard][BLOCK] {result.get('message')}", file=file, flush=True)
    elif result.get("warn") or result.get("warn_untrustworthy"):
        print(f"[snapshot_guard][WARN]  {result.get('message')}", file=file, flush=True)
    else:
        print(f"[snapshot_guard][OK]    {result.get('message')}", file=file, flush=True)


if __name__ == "__main__":
    # 简单自检（演示三个工具的输出形态）
    import os
    here = Path(__file__).parent
    print("=== snapshot_guard 自检 ===\n")

    print("--- 1. check_csv_snapshot ---")
    r1 = check_csv_snapshot(here / "screener_pool.csv")
    emit(r1)
    print(json.dumps(r1, ensure_ascii=False, indent=2))

    print("\n--- 2. check_meta_snapshot ---")
    r2 = check_meta_snapshot(here / "pool_meta.json")
    emit(r2)
    print(json.dumps(r2, ensure_ascii=False, indent=2))

    print("\n--- 3. check_last_bar_today ---")
    r3 = check_last_bar_today("2026-09-03", today="2026-09-04")
    emit(r3)
    print(json.dumps(r3, ensure_ascii=False, indent=2))
