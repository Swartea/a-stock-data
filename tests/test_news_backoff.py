import time
import sys
sys.path.insert(0, "/Users/swarteachou/Desktop/大A数据/analysis")

def test_news_backoff_reduced():
    """新闻 fetcher 总退避应 < 10s（3 次失败）"""
    # 静态检查源码
    src = open("/Users/swarteachou/Desktop/大A数据/analysis/fetch_news_em.py").read()
    # 旧的 sleep 3 + 4*attempt = 3/7/11s（21s 总和）
    # 新的 sleep 0.8 + 1.2*attempt = 0.8/2.0/3.2s（6s 总和）
    assert "0.8 + 1.2 * attempt" in src or "0.8+1.2*attempt" in src, \
        "应改为 0.8+1.2*attempt"
    assert "3 + 4 * attempt" not in src, "旧的 3+4*attempt 不应保留"
