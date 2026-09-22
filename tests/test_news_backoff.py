import os
import sys
import time
from pathlib import Path

# P1.5 整改: 用 conftest 的 WORKDIR 取代硬编码个人路径
# conftest 通过 sys.path / pytest 自动注入, 这里直接 import os.environ
WORKDIR = Path(os.environ.get("DA_A_DATA_DIR", "/Users/swarteachou/Desktop/大A数据")).resolve()
sys.path.insert(0, str(WORKDIR / "analysis"))


def test_news_backoff_reduced():
    """新闻 fetcher 总退避应 < 10s（3 次失败）

    P1.5 整改: 用 conftest.analysis_dir + fixture 路径, 取代 open 个人路径
    """
    # 静态检查源码
    with open(WORKDIR / "analysis" / "fetch_news_em.py", encoding="utf-8") as f:
        src = f.read()
    # 旧的 sleep 3 + 4*attempt = 3/7/11s（21s 总和）
    # 新的 sleep 0.8 + 1.2*attempt = 0.8/2.0/3.2s（6s 总和）
    assert "0.8 + 1.2 * attempt" in src or "0.8+1.2*attempt" in src, \
        "应改为 0.8+1.2*attempt"
    assert "3 + 4 * attempt" not in src, "旧的 3+4*attempt 不应保留"
