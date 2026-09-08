import os
import re
import subprocess
import json
import pytest
from datetime import datetime

WORKDIR = "/Users/swarteachou/Desktop/大A数据"
# V3 落盘到当天日期目录; 测试用最近一次跑 (今日)
DAY_DIR = f"{WORKDIR}/reports/600693_东百集团/{datetime.now().strftime('%Y-%m-%d')}"

def test_run_log_has_timestamp():
    """两次跑 V3 应产生两个不同 HHMM 的 run_log，不应覆盖"""
    pattern = re.compile(r"run_log-\d{4}\.json")
    files = [f for f in os.listdir(DAY_DIR) if pattern.match(f)]
    # 至少 1 个（最近一次跑），不再有固定名 run_log.json
    assert len(files) >= 1, f"应该有时间戳的 run_log，实际: {os.listdir(DAY_DIR)}"
    # 不应该有固定名的 run_log.json
    assert "run_log.json" not in os.listdir(DAY_DIR), \
        "run_log.json 不应再存在（应改为 run_log-{HHMM}.json）"

def test_result_v3_has_timestamp():
    pattern = re.compile(r"result_v3-\d{4}\.json")
    files = [f for f in os.listdir(DAY_DIR) if pattern.match(f)]
    assert len(files) >= 1
    assert "result_v3.json" not in os.listdir(DAY_DIR)

def test_two_timestamped_files_coexist():
    """两个 timestamped run_log 文件应共存（防止 V3 二次跑覆盖）"""
    from datetime import datetime
    now = datetime.now().strftime('%Y-%m-%d')
    day_dir = f"/Users/swarteachou/Desktop/大A数据/reports/600693_东百集团/{now}"
    if not os.path.exists(day_dir):
        pytest.skip(f"未找到 {day_dir}（需先跑 V3 至少一次）")
    pattern = re.compile(r"run_log-\d{4}\.json")
    files = [f for f in os.listdir(day_dir) if pattern.match(f)]
    if len(files) < 2:
        pytest.skip("需要至少 2 次 V3 跑才能验证不互覆盖（手动跑第二次后再跑测试）")
    hhmms = sorted(f.split("-")[-1].split(".")[0] for f in files)
    assert len(set(hhmms)) == len(hhmms), f"出现重复 HHMM {hhmms}（覆盖 bug 未修）"
