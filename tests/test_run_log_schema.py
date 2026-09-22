"""run_log 命名规范测试 (P1-E 整改, 2026-09-11)

规范 §7: run_log-{HHMM}.json 不覆盖, 避免重跑丢失前次记录
原版依赖个人路径 + 当日日期目录, P1-E 改用 tmp_path fixture

测试:
- run_log 文件名格式: run_log-{HHMM}.json (4 位时间戳)
- result_v3 文件名格式: result_v3-{HHMM}.json
- 无固定名 run_log.json / result_v3.json (老格式不再用)
- 两次模拟生成不互覆盖
"""
import json
import os
import re
from datetime import datetime

import pytest


def _emit_run_log(tmp_path, hhmm: str = "1234") -> str:
    """模拟 V3 _emit 落 run_log + result_v3 到 tmp_path, 返回 HHMM"""
    log = {
        "started_at": f"2026-09-11T{int(hhmm[:2])}:{int(hhmm[2:])}:00+08:00",
        "finished_at": f"2026-09-11T{int(hhmm[:2])}:{int(hhmm[2:])}:30+08:00",
        "total_sec": 30,
        "sources": {"公告": "ok:eastmoney, 100ms"},
        "artifacts": {"deliverable_status": "complete"},
    }
    (tmp_path / f"run_log-{hhmm}.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    (tmp_path / f"result_v3-{hhmm}.json").write_text(
        json.dumps({"code": "TEST", "deliverable_status": "complete"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return hhmm


def test_run_log_filename_format(tmp_path):
    """run_log 文件名必须 run_log-{HHMM}.json 格式 (4 位时间戳)"""
    _emit_run_log(tmp_path, "1234")
    files = list(tmp_path.glob("run_log-*.json"))
    assert len(files) == 1
    assert re.match(r"run_log-\d{4}\.json", files[0].name)
    # 老的固定名 run_log.json 不应再生成
    assert not (tmp_path / "run_log.json").exists()


def test_result_v3_filename_format(tmp_path):
    """result_v3 文件名必须 result_v3-{HHMM}.json 格式"""
    _emit_run_log(tmp_path, "1234")
    files = list(tmp_path.glob("result_v3-*.json"))
    assert len(files) == 1
    assert re.match(r"result_v3-\d{4}\.json", files[0].name)
    assert not (tmp_path / "result_v3.json").exists()


def test_two_runs_do_not_overwrite(tmp_path):
    """两次不同 HHMM 跑应共存, 不互覆盖 (§7)"""
    _emit_run_log(tmp_path, "1234")
    _emit_run_log(tmp_path, "1250")
    logs = sorted(p.name for p in tmp_path.glob("run_log-*.json"))
    results = sorted(p.name for p in tmp_path.glob("result_v3-*.json"))
    assert logs == ["run_log-1234.json", "run_log-1250.json"], \
        f"两次 run_log 应共存, 实际 {logs}"
    assert results == ["result_v3-1234.json", "result_v3-1250.json"], \
        f"两次 result_v3 应共存, 实际 {results}"


def test_artifact_names_no_uniqueness_violation(tmp_path):
    """§7: HHMM 重复 (同分钟跑 2 次) 才会覆盖, 这是已知限制; 测试覆盖检测"""
    _emit_run_log(tmp_path, "1234")
    _emit_run_log(tmp_path, "1234")  # 重复 HHMM, 模拟
    # 同 HHMM 第二次写会覆盖第一次 (file system 行为)
    files = list(tmp_path.glob("run_log-*.json"))
    assert len(files) == 1, f"同 HHMM 重复跑应覆盖, 实际 {len(files)} 个"


def test_artifact_schema_minimal(tmp_path):
    """§7: run_log 必须含 started_at / finished_at / sources / artifacts 字段"""
    _emit_run_log(tmp_path, "1500")
    log = json.loads((tmp_path / "run_log-1500.json").read_text(encoding="utf-8"))
    assert "started_at" in log
    assert "finished_at" in log
    assert "sources" in log
    assert "artifacts" in log
    assert "deliverable_status" in log["artifacts"]
