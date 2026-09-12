"""A 股多因子量化分析器 V3 — analysis/ 包 (P2-B 8.11 配套, 2026-09-12)

模块:
  quant_analyzer_v3: V3 主分析器 (CLI 入口)
  quant_analyzer_v2: V2 底座 (10 数据类 + 评分 + 三价位)
  quant_analyzer:    V1 基础版 (deprecated, 沿用部分 fetcher)
  html_report_v3:    HTML 渲染器 (含 PDF 渲染)
  html_report:       V2 HTML (被 html_report_v3 复用 4 个 SVG)
  md_to_docx:        MD → DOCX 转换
  fetcher_contract:  fetcher 数据契约 (§4 规范)
  fetch_*:           4 个独立 fetcher (公告/财务/研报/新闻)

按规范 §2 模块边界:
  入口:    quant_analyzer_v3.main
  采集:    fetch_*.py + _fetch_*
  分析:    quant_analyzer_v2.compute_quant_score_v2 / _make_trading_plan
  报告:    write_markdown_report_v3
  渲染:    html_report_v3 / md_to_docx
  产物:    result_v3 / run_log (在 _emit 函数)
"""
__version__ = "0.16.0"
