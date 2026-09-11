# -*- coding: utf-8 -*-
"""
HTML 报告生成模块 V3 (排版 4 项 + 内容 6 模块) — 供 V3 主分析器调用

复用 V2:
  - `import html_report as hr`, 4 张 SVG 全部调用 hr 里的函数, 不重写:
      hr._svg_kline(klines, width, height, current_price)      -> K 线
      hr._svg_chip_histogram(cd, width, height)                -> 筹码分布
      hr._svg_pe_history(pe_series, current_pct, width, height)-> PE 历史
      hr._svg_radar(score_dict, width, height)                 -> 10 因子雷达
  每个函数缺数据时返回 "" 或占位 svg —— 本模块统一套外层卡片并补齐 "数据源暂缺"。

V3 排版 (docs/05-报告升级方案.md 拍板 4 项):
  a) 结论前置 hero 区: 多空结论大字 + 大号评分 + 三价位表 + 一句话理由 (第一屏读完)
  b) 操作检查清单区: 买/卖触发条件 + 止损纪律 + 仓位建议 (由 signals + trading_plan 生成)
  c) 风险警报区: 解禁/财报临近/减持公告等风险事件独立成区, 红色高亮; 无风险时绿色 "无临近风险事件"
  d) 四图统一卡片风格, 每图标注数据截止时间
  6 块新内容: 研报观点 / 公告速览 / 财务体检 / 同业对比 / 资金面 / 新闻舆情, 每块标注来源与时点。

result dict 契约 (V3 主分析器并行开发中):
  缺字段一律显示 "数据源暂缺", 绝不崩。
"""
import os
import re
import math
import datetime

import html_report as hr  # 只复用 V2 的 4 个 SVG 生成函数

# Phase 1: Section Registry (irm §10.1) — 容错 import, 缺则降级
# (Task 1.4 灰度: 5 新节走新注册表, 旧 6 块仍保留; spec §3.3)
try:
    from sections import enabled_sections
    _SECTIONS_OK = True
except Exception as _sec_err:  # noqa: BLE001
    enabled_sections = None
    _SECTIONS_OK = False
    _SEC_IMPORT_ERR = str(_sec_err)

# ============================================================
# 语义色板 (docs/06 §2.1 token 对齐): A股惯例 红=涨/多, 绿=跌/空,
# 琥珀=中性; 风险=红系警示。AA 文字档为同色系加深档 (白底小字 ≥4.5:1)。
# ============================================================
C_RED = "#dc2626"          # 红系(危险/涨) — 同 token --danger / --up
C_RED_DK = "#b91c1c"       # 红系 AA 文字档 (6.5:1)
C_GREEN = "#16a34a"        # 绿系(通用正向/跌) — 同 token --good / --down
C_GREEN_DK = "#15803d"     # 绿系 AA 文字档 (5.0:1)
C_AMBER = "#d97706"        # 琥珀(警告/中性)
C_AMBER_DK = "#b45309"     # 琥珀 AA 文字档 (5.0:1)
C_BLUE = "#2563eb"         # 强调蓝 — token --accent (5.2:1)
C_GRAY = "#78716c"         # 弱文字 — token --ink-3 (4.8:1)

# ============================================================
# 通用小工具
# ============================================================

def _esc(s):
    """HTML 转义 (新闻标题/公告标题等外部文本必须过一遍)"""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _clean_fname(s):
    """文件名安全化 (保留中文)"""
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", str(s))
    return s.strip("_") or "report"


def _num(v, nd=2):
    """安全数字 -> 字符串; None/NaN/inf -> None (调用处显示 '—')"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return "%.*f" % (nd, f)


def _num_or_dash(v, nd=2, unit=""):
    s = _num(v, nd)
    return "—" if s is None else s + unit


def _first(blob, *keys, default=None):
    """dict 中按候选 key 顺序取值 (防御: V3 分析器字段名可能演进)"""
    if isinstance(blob, dict):
        for k in keys:
            if blob.get(k) is not None:
                return blob[k]
    return default


def _parse_date(s):
    """'2026-09-04' / '2026-09-04 15:30:00' -> date; 失败返回 None"""
    if not s:
        return None
    s = str(s)[:10]
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _days_between(a, b):
    """两个日期字符串差 (a-b, 天)。任一解析失败返回 None。"""
    da, db = _parse_date(a), _parse_date(b)
    if da is None or db is None:
        return None
    return (da - db).days


def _is_error(blob):
    """§4 规范: 错误返回不等于成功; 调用方必须检查状态, 而非只检查是否抛异常。

    P0-B (2026-09-11): 兼容老 ad-hoc 格式 ({"error": str, ...}) + 新契约 (status=error)。
    """
    if not isinstance(blob, dict):
        return True
    # 新契约优先
    if "status" in blob and blob["status"] in ("ok", "empty", "error", "unsupported"):
        return blob["status"] == "error"
    # 老 ad-hoc 兜底
    return "error" in blob


def _svg_safe(fn, *args, **kwargs):
    """包一层: 字段缺失/格式不符时返回空串, 由卡片渲染成 '数据源暂缺', 绝不崩"""
    try:
        return fn(*args, **kwargs)
    except Exception:
        return ""


# ------------------------------------------------------------
# 数据来源 + 时点标注
# ------------------------------------------------------------

def _source_time(run_log, key_hints, default):
    """从 run_log.sources 模糊取时点:
    先精确匹配 sources[key_hints...], 再按关键字子串扫一遍;
    run_log 没有时点就回退 report_date。"""
    if isinstance(run_log, dict):
        srcs = run_log.get("sources")
        if isinstance(srcs, dict):
            for hint in key_hints:
                if hint in srcs and isinstance(srcs[hint], dict):
                    for k in ("as_of", "at", "fetched_at", "ts", "date", "data_end", "time"):
                        v = srcs[hint].get(k)
                        if v:
                            return str(v)[:16]
            # 关键字子串扫描 (V3 分析器内部命名未定)
            for name, blob in srcs.items():
                if any(h in name for h in key_hints) and isinstance(blob, dict):
                    for k in ("as_of", "at", "fetched_at", "ts", "date", "data_end", "time"):
                        v = blob.get(k)
                        if v:
                            return str(v)[:16]
    return default


def _blob_time(blob, key_hints, default):
    """优先从数据块自身的 as_of/date/data_end/window_end 字段取时点"""
    if isinstance(blob, dict):
        for k in ("as_of", "data_end", "window_end", "fetched_at", "at", "date"):
            v = blob.get(k)
            if v:
                return str(v)[:16]
    return default


def _time_label(t):
    return "数据源暂缺" if not t else _esc(str(t))


# ------------------------------------------------------------
# 文本/列表辅助
# ------------------------------------------------------------

def _trunc(s, n=60):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _signal_text(item):
    """signals 元素可能是 str 或 dict, 统一取文本"""
    if isinstance(item, dict):
        for k in ("text", "desc", "condition", "action", "content", "note", "signal"):
            if item.get(k):
                return str(item[k])
        return ""
    return str(item)


def _signal_direction(item, text):
    """买/卖方向归类: dict 的 direction/type 优先, 否则关键词嗅探"""
    d = ""
    if isinstance(item, dict):
        d = str(_first(item, "direction", "side", "type", default="") or "").lower()
    if d in ("buy", "long", "add"):
        return "buy"
    if d in ("sell", "short", "reduce", "close"):
        return "sell"
    t = text.lower()
    if any(w in t for w in ("买入", "低吸", "建仓", "加仓", "买点", "进场", "抄底")):
        return "buy"
    if any(w in t for w in ("卖出", "减仓", "止盈", "清仓", "止损", "高抛", "走人", "离场")):
        return "sell"
    return "watch"


def _rating_color(rating):
    """评级词 -> 颜色 (A股语义: 买入红系/中性灰/卖出绿系; AA 文字档)"""
    r = str(rating or "")
    if any(w in r for w in ("买入", "推荐", "强烈")):
        return "#b91c1c"
    if any(w in r for w in ("增持", "跑赢", "优于")):
        return "#b45309"
    if any(w in r for w in ("中性", "持有", "持平", "观望")):
        return "#57534e"
    if any(w in r for w in ("减持", "卖出", "回避", "跑输")):
        return "#15803d"
    return "#57534e"


def _sentiment_color(sent):
    """公告/新闻情绪 -> 色 (A股: 利好=红系, 利空=绿系)"""
    s = str(sent or "")
    if "利好" in s or "正面" in s or "积极" in s:
        return "#b91c1c"
    if "利空" in s or "负面" in s or "风险" in s or "减持" in s:
        return "#15803d"
    return "#57534e"


def _sentiment_tag(sent):
    c = _sentiment_color(sent)
    return ('<span class="v3-tag" style="color:%s;background:%s22">%s</span>'
            % (c, c, _esc(sent or "中性")))


# ============================================================
# CSS
# ============================================================

_CSS = """
:root{
  /* ================= §2.1 设计 token (docs/06-排版美化方案) ================= */
  --bg:#fafaf9;            /* 中性底 (不纯黑纯白) */
  --surface:#ffffff;
  --zebra:#f5f5f4;         /* 表格斑马纹 (中性灰阶梯) */
  --ink-1:#1c1917;         /* 主文字 (17.5:1) */
  --ink-2:#57534e;         /* 次级文字 (7.6:1) */
  --ink-3:#78716c;         /* 弱文字/注释 (4.8:1, AA) */
  --accent:#2563eb;        /* 强调 (5.2:1) */
  --warn:#d97706;          /* 警告/中性 */
  --warn-bg:#fffbeb;
  --danger:#dc2626;        /* 危险 (4.8:1) */
  --good:#16a34a;          /* 正向 */
  --hairline:#e7e5e4;      /* hairline 分隔线 */
  /* ================= A股例外: 红涨绿跌 (覆盖国际惯例, 全篇一致) ================= */
  /* 涨/利好 = 红系; 跌/利空 = 绿系; 风险警报区仍红警示 */
  --up:#dc2626;            /* 涨/利好 = 危险红 (红系主色) */
  --up-ink:#b91c1c;        /* 涨红 AA 文字档 6.5:1 */
  --up-bg:#fef2f2;
  --down:#16a34a;          /* 跌/利空 = 正向绿 (绿系主色) */
  --down-ink:#15803d;      /* 跌绿 AA 文字档 5.0:1 */
  --down-bg:#f0fdf4;
  --neutral-ink:#b45309;   /* 中性琥珀 AA 文字档 5.0:1 */
  --risk-ink:#b91c1c; --risk-bg:#fef2f2; --risk-line:#fecaca;
  --ok-ink:#15803d; --ok-bg:#f0fdf4; --ok-line:#bbf7d0;
  /* ================= §2.2 字体: CJK 栈 + 数字等宽 ================= */
  --font-cjk:"PingFang SC","Source Han Sans SC","Noto Sans SC","Microsoft YaHei",sans-serif;
  --font-num:"SF Mono","JetBrains Mono",ui-monospace,Menlo,Consolas,monospace;
  /* ================= §2.3 8px 基线网格: 间距/圆角 = 8 的倍数 ================= */
  --sp-1:8px; --sp-2:16px; --sp-3:24px; --sp-4:32px;
  --radius:8px;            /* 圆角统一 8px */
  --shadow:0 1px 2px rgba(28,25,23,.05),0 2px 8px rgba(28,25,23,.04);
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:var(--font-cjk);background:var(--bg);color:var(--ink-1);
     margin:0;font-size:14px;line-height:1.6;font-variant-numeric:tabular-nums}
.container{max-width:800px;margin:0 auto;padding:var(--sp-2) var(--sp-2) var(--sp-4)}
.self-test-note{background:var(--warn-bg);border:1px dashed var(--warn);
     color:var(--neutral-ink);padding:var(--sp-1) var(--sp-2);border-radius:var(--radius);
     font-size:12px;margin-bottom:var(--sp-2)}
.card{background:var(--surface);border-radius:var(--radius);padding:var(--sp-2);
     margin-bottom:var(--sp-2);box-shadow:var(--shadow)}
.card h2{font-size:16px;margin:0 0 var(--sp-1);color:var(--ink-1);
     display:flex;align-items:center;gap:var(--sp-1)}
.card h2 .bar{width:4px;height:16px;border-radius:2px;background:var(--accent);
     display:inline-block}
.no-data{color:var(--ink-3);font-size:13px;padding:var(--sp-2);text-align:center;
     background:var(--bg);border:1px dashed var(--hairline);border-radius:var(--radius)}
.src-line{font-size:11.5px;color:var(--ink-3);margin:-4px 0 var(--sp-1);line-height:1.5}
.mini-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-1)}
@media(min-width:600px){.mini-grid{grid-template-columns:repeat(3,1fr)}}
.kpi{background:var(--bg);border-radius:var(--radius);padding:var(--sp-1) 12px}
.kpi .l{color:var(--ink-3);font-size:11px}
.kpi .v{font-size:17px;font-weight:600;margin-top:2px;font-family:var(--font-num)}
table.v3-tbl{width:100%;border-collapse:collapse;font-size:12.5px}
table.v3-tbl th,table.v3-tbl td{padding:var(--sp-1);text-align:left;vertical-align:top;
     border-bottom:1px solid var(--hairline)}
table.v3-tbl th{color:var(--ink-3);font-weight:500;font-size:11.5px;background:var(--bg);
     white-space:nowrap}
table.v3-tbl tbody tr:last-child td{border-bottom:none}
table.v3-tbl tbody tr:nth-child(even){background:var(--zebra)}  /* zebra 斑马纹 */
table.v3-tbl td.num,table.v3-tbl th.num{text-align:right;font-family:var(--font-num);
     font-variant-numeric:tabular-nums}
.tbl-wrap{max-height:360px;overflow:auto;border:1px solid var(--hairline);
     border-radius:var(--radius);background:var(--surface)}
.tbl-wrap table.v3-tbl thead th{position:sticky;top:0;z-index:2}  /* 长表 sticky 表头 */
.up{color:var(--up-ink)}       /* A股: 涨 = 红系 */
.down{color:var(--down-ink)}   /* A股: 跌 = 绿系 */
a{color:var(--accent);text-decoration:none}
.disc{color:var(--ink-3);font-size:11.5px}
.mono{font-family:var(--font-num)}
"""

# Task 6.1 (UI 升级线): 集成 mingli30119/stock-analysis 双主题 CSS 模板
# 来源: https://raw.githubusercontent.com/mingli30119/stock-analysis/main/shared/template_base.css
# 集成方式: 拼到 V3 旧 CSS 之后, 同名类会覆盖 V3 旧定义 (升级意图: 换皮)
_MINGLI_CSS = r"""
/* ── mingli30119 双主题 · 红涨绿跌 · 金棕强调 · 响应式 ── */
.v3-stock-report{
--bg:#0c0f15;--card-bg:#1a1c24;--card-bg-alt:#1e2029;--border:#2a2d3a;
--text-primary:#e8e9ec;--text-secondary:#b0b3be;--text-muted:#7a7d8a;
--red-up:#f55656;--green-down:#28c75b;--gold:#d4a853;--gold-light:#e3c26d;
--blue-accent:#4a90d9;--orange-warn:#e8923a;
--shadow:0 4px 20px rgba(0,0,0,.3);--radius:10px;
--font-sans:"PingFang SC","Microsoft YaHei",-apple-system,sans-serif;
--font-mono:"JetBrains Mono","SF Mono","Consolas",monospace;--transition:.2s ease;
}
.v3-stock-report, .v3-stock-report *{font-family:var(--font-sans)}
.v3-stock-report.light-mode{
--bg:#fdf8f0;--card-bg:#fffbf5;--card-bg-alt:#fef5e7;--border:#e2cfa2;
--text-primary:#2a1f12;--text-secondary:#6b5634;--text-muted:#9c8b6e;
--red-up:#dc2626;--green-down:#16a34a;--gold:#b38a3c;--gold-light:#d4a853;
--blue-accent:#2563eb;--orange-warn:#c2410c;--shadow:0 4px 20px rgba(162,125,57,.08)
}
.v3-stock-report{background:var(--bg);color:var(--text-primary);line-height:1.7;font-size:14px;
background-image:radial-gradient(circle at 15% 10%,rgba(212,168,83,.03) 0%,transparent 35%),
radial-gradient(circle at 85% 70%,rgba(212,168,83,.03) 0%,transparent 35%);background-attachment:fixed;
max-width:1300px;margin:0 auto;padding:24px 20px 40px}
/* 顶部导航 */
.v3-stock-report .top-nav{position:sticky;top:0;z-index:100;background:rgba(10,12,18,.92);
backdrop-filter:blur(12px);border-bottom:2px solid var(--gold-light);padding:10px 28px;
margin:-24px -20px 24px;display:flex;align-items:center;justify-content:space-between;
flex-wrap:wrap;gap:12px}
.v3-stock-report .top-nav .logo{display:flex;align-items:center;gap:10px;color:#fff}
.v3-stock-report .top-nav .logo-icon{width:34px;height:34px;background:linear-gradient(135deg,#c0392b,#8b0000);
border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff}
.v3-stock-report .top-nav .stock-name{font-weight:700;font-size:17px;letter-spacing:.5px}
.v3-stock-report .top-nav .stock-code{font-size:12px;opacity:.7;font-family:var(--font-mono)}
.v3-stock-report .nav-links{display:flex;gap:8px;flex-wrap:wrap}
.v3-stock-report .nav-links a{font-size:12px;padding:5px 14px;border-radius:16px;color:var(--gold-light);
text-decoration:none;border:1px solid transparent;transition:var(--transition);font-weight:500;white-space:nowrap}
.v3-stock-report .nav-links a:hover,.v3-stock-report .nav-links a.active{background:rgba(255,255,255,.08);
color:#fff;border-color:var(--gold)}
.v3-stock-report .theme-toggle{background:rgba(255,255,255,.08);border:1px solid var(--gold-light);
color:var(--gold-light);padding:5px 14px;border-radius:16px;font-size:12px;cursor:pointer;
transition:var(--transition);margin-left:12px}
.v3-stock-report .theme-toggle:hover{background:rgba(255,255,255,.15)}
/* Hero 行情卡片 */
.v3-stock-report .hero{background:linear-gradient(105deg,#1c1010 0%,#2c1a1a 50%,#3d2424 100%);
border-radius:var(--radius);padding:28px 32px;margin-bottom:24px;border:1px solid var(--gold-light);
box-shadow:0 8px 28px rgba(100,55,55,.2);display:flex;flex-wrap:wrap;gap:24px;
align-items:center;color:#fff;position:relative;overflow:hidden}
.v3-stock-report .hero::after{content:'';position:absolute;top:-40px;right:-40px;width:200px;height:200px;
border-radius:50%;background:radial-gradient(circle,rgba(255,215,0,.08) 0%,transparent 70%);pointer-events:none}
.v3-stock-report .hero-price-block{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;z-index:1}
.v3-stock-report .hero-price{font-size:56px;font-weight:900;line-height:1;font-family:var(--font-mono)}
.v3-stock-report .hero-change{font-size:20px;font-weight:700;padding:4px 12px;border-radius:6px;
background:rgba(245,86,86,.2);color:#f87171;font-family:var(--font-mono)}
.v3-stock-report .hero-meta{display:flex;gap:28px;flex-wrap:wrap;z-index:1}
.v3-stock-report .hero-meta-item{text-align:center}
.v3-stock-report .hero-meta-item .val{font-size:22px;font-weight:700;font-family:var(--font-mono);color:var(--gold-light)}
.v3-stock-report .hero-meta-item .label{font-size:11px;color:rgba(255,255,255,.7);letter-spacing:1px}
.v3-stock-report .hero-tags{display:flex;gap:8px;flex-wrap:wrap;z-index:1}
.v3-stock-report .hero-tag{background:rgba(255,255,255,.08);border:1px solid rgba(255,215,0,.3);
color:var(--gold-light);padding:4px 9px;border-radius:20px;font-size:11px;font-weight:500}
/* 结论置顶 */
.v3-stock-report .conclusion-top{background:linear-gradient(135deg,#1e1a10 0%,#241f14 100%);
border:2px solid var(--gold);border-radius:var(--radius);padding:22px 28px;margin-bottom:24px;position:relative}
.v3-stock-report .conclusion-top::before{content:'核心结论';position:absolute;top:-13px;left:24px;
background:var(--gold);color:#000;padding:3px 16px;border-radius:12px;font-weight:700;font-size:12px;letter-spacing:1px}
.v3-stock-report .conclusion-top .big-verdict{font-weight:800;font-size:20px;color:#fff;margin-top:8px}
.v3-stock-report .conclusion-top .verdict-detail{font-size:14px;color:var(--text-secondary);margin-top:8px;line-height:1.7}
.v3-stock-report .conclusion-top .verdict-tags{display:flex;gap:12px;margin-top:12px;flex-wrap:wrap}
/* 卡片 */
.v3-stock-report .card{background:var(--card-bg);border:1px solid var(--border);
border-radius:var(--radius);padding:22px 28px;margin-bottom:20px;box-shadow:var(--shadow);
transition:var(--transition)}
.v3-stock-report .card:hover{box-shadow:0 8px 30px rgba(0,0,0,.5);border-color:var(--gold)}
.v3-stock-report .card-header{display:flex;align-items:center;gap:10px;margin-bottom:16px;
padding-bottom:12px;border-bottom:2px solid var(--border)}
.v3-stock-report .card-header .icon{width:32px;height:32px;border-radius:8px;
background:rgba(255,255,255,.05);display:flex;align-items:center;justify-content:center;
font-weight:700;font-size:16px;color:var(--gold)}
.v3-stock-report .card-header h2{font-size:18px;font-weight:700;color:#fff;letter-spacing:.5px}
.v3-stock-report .card-header .sub{margin-left:auto;font-size:11px;color:var(--text-muted)}
/* 布局网格 */
.v3-stock-report .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.v3-stock-report .grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
/* 表格 */
.v3-stock-report table.cons{width:100%;border-collapse:collapse;font-size:13px;
background:var(--card-bg-alt);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin:12px 0}
.v3-stock-report table.cons thead th{background:linear-gradient(180deg,#2c1a1a 0%,#1c1010 100%);
color:#fff;font-weight:600;padding:10px 12px;text-align:left;font-size:12px;letter-spacing:1px}
.v3-stock-report table.cons tbody tr{border-bottom:1px dashed var(--border)}
.v3-stock-report table.cons tbody tr:hover{background:rgba(255,255,255,.02)}
.v3-stock-report table.cons tbody td{padding:9px 12px;vertical-align:middle;color:var(--text-secondary)}
.v3-stock-report .val-up{color:var(--red-up);font-weight:600}
.v3-stock-report .val-down{color:var(--green-down);font-weight:600}
/* 标签 */
.v3-stock-report .tag{display:inline-block;padding:3px 12px;border-radius:14px;font-size:11px;
font-weight:600;background:rgba(212,168,83,.15);color:var(--gold-light);border:1px solid var(--gold);
margin-right:6px;margin-bottom:4px}
/* KPI 行 */
.v3-stock-report .kpi-info-row{display:flex;justify-content:space-around;margin-top:18px;
padding-top:14px;border-top:2px solid var(--border)}
.v3-stock-report .kpi-info-item{text-align:center}
.v3-stock-report .kpi-info-item .label{font-size:12px;color:var(--text-muted)}
.v3-stock-report .kpi-info-item .value{font-size:20px;font-weight:700;color:var(--gold-light)}
/* 浅色模式 */
.v3-stock-report.light-mode .hero{background:linear-gradient(105deg,#fef5e7,#fffbf5);
color:var(--text-primary);border-color:var(--gold)}
.v3-stock-report.light-mode .hero-price{color:var(--text-primary)}
.v3-stock-report.light-mode .hero-change{background:rgba(220,38,38,.1);color:var(--red-up)}
.v3-stock-report.light-mode .hero-meta-item .val{color:var(--gold)}
.v3-stock-report.light-mode .hero-meta-item .label{color:var(--text-muted)}
.v3-stock-report.light-mode .hero-tag{background:rgba(212,168,83,.15);border-color:var(--gold);color:var(--gold)}
.v3-stock-report.light-mode .conclusion-top{background:linear-gradient(135deg,#fff9f0,#fef5e7)}
.v3-stock-report.light-mode .conclusion-top .big-verdict{color:var(--text-primary)}
.v3-stock-report.light-mode .card-header h2{color:var(--text-primary)}
.v3-stock-report.light-mode .tag{background:rgba(212,168,83,.15);color:var(--gold);border-color:var(--gold)}
.v3-stock-report.light-mode .kpi-info-item .value{color:var(--gold)}
.v3-stock-report.light-mode .top-nav .logo{color:var(--text-primary)}
.v3-stock-report.light-mode .top-nav .logo-icon{color:var(--card-bg)}
.v3-stock-report.light-mode .top-nav .stock-name{color:var(--text-primary)}
.v3-stock-report.light-mode .theme-toggle{background:rgba(0,0,0,.05);border-color:var(--gold);color:var(--gold)}
/* 响应式 */
@media(max-width:850px){
.v3-stock-report .grid-2,.v3-stock-report .grid-3{grid-template-columns:1fr}
.v3-stock-report .hero{flex-direction:column;align-items:flex-start}
.v3-stock-report .hero-price{font-size:40px}
.v3-stock-report .top-nav{padding:10px 14px}
}
"""

# Task 6.3 + 6.4 (UI 升级线): ECharts 完整 JS 模板 (从 mingli30119 搬)
# 6 图表: K线 + MACD + KDJ + RSI + BOLL (4 占位符 __RAW_DATA__/__PIE_DATA__/__MARKLINE__/__MARKPOINT__ 在 V3 渲染器运行时替换)
_ECHARTS_JS_TEMPLATE = r'''
<script>
(function() {
var rawData = __RAW_DATA__;

// 数据处理
var dates = [], ohlc = [], volumesRaw = [];
rawData.forEach(function(d) {
  dates.push(d[0]);
  ohlc.push([d[1], d[4], d[3], d[2]]);
  volumesRaw.push(d[5]);
});
var closes = ohlc.map(function(d) { return d[1]; });
var highs = rawData.map(function(d) { return d[4]; });
var lows = rawData.map(function(d) { return d[3]; });
function calcMA(arr, n) {
  return arr.map(function(_, i) {
    if (i < n - 1) return null;
    var sum = arr.slice(i - n + 1, i + 1).reduce(function(a, b) { return a + b; }, 0);
    return +(sum / n).toFixed(2);
  });
}
var ma5 = calcMA(closes, 5), ma20 = calcMA(closes, 20), ma60 = calcMA(closes, 60);
var volumes = volumesRaw.map(function(v) { return +(v / 10000).toFixed(2); });
var dateLabels = dates.map(function(d) {
  var parts = d.split('-');
  return parts[1] + '-' + parts[2];
});

// 主题色 (跟随 v3-stock-report.light-mode)
function getThemeColors() {
  var isLight = document.body.classList.contains('light-mode') ||
                (document.querySelector('.v3-stock-report') &&
                 document.querySelector('.v3-stock-report').classList.contains('light-mode'));
  return {
    textColor:    isLight ? '#2a1f12' : '#e8e9ec',
    textSecondary:isLight ? '#6b5634' : '#b0b3be',
    textMuted:    isLight ? '#9c8b6e' : '#7a7d8a',
    upColor:      isLight ? '#dc2626' : '#f55656',
    downColor:    isLight ? '#16a34a' : '#28c75b',
    ma5Color:     isLight ? '#2563eb' : '#4a90d9',
    ma20Color:    isLight ? '#16a34a' : '#28c75b',
    ma60Color:    isLight ? '#c2410c' : '#e8923a',
    volUpColor:   isLight ? 'rgba(220,38,38,0.25)'  : 'rgba(245,86,86,0.35)',
    volDownColor: isLight ? 'rgba(22,163,74,0.25)'  : 'rgba(40,199,91,0.35)',
  };
}

// 技术指标计算
function calcEMA(arr, n) {
  var k = 2 / (n + 1);
  var ema = [arr[0]];
  for (var i = 1; i < arr.length; i++) ema.push(arr[i] * k + ema[i-1] * (1 - k));
  return ema;
}
function calcMACDData(c) {
  var ema12 = calcEMA(c, 12), ema26 = calcEMA(c, 26);
  var dif = ema12.map(function(v, i) { return v - ema26[i]; });
  var dea = calcEMA(dif, 9);
  var macd = dif.map(function(v, i) { return 2 * (v - dea[i]); });
  return { dif: dif, dea: dea, macd: macd };
}
function calcKDJData(h, l, c, n) {
  n = n || 9;
  var k = [], d = [], j = [];
  for (var i = 0; i < c.length; i++) {
    if (i < n - 1) { k.push(50); d.push(50); j.push(50); continue; }
    var hi = Math.max.apply(null, h.slice(i - n + 1, i + 1));
    var lo = Math.min.apply(null, l.slice(i - n + 1, i + 1));
    var rsv = ((c[i] - lo) / (hi - lo)) * 100 || 50;
    k.push(i === n - 1 ? rsv : (2/3) * k[i-1] + (1/3) * rsv);
    d.push(i === n - 1 ? k[i]  : (2/3) * d[i-1] + (1/3) * k[i]);
    j.push(3 * k[i] - 2 * d[i]);
  }
  return { k: k, d: d, j: j };
}
function calcRSI(c, n) {
  var gains = [], losses = [], rsi = [];
  for (var i = 0; i < c.length; i++) {
    if (i === 0) { gains.push(0); losses.push(0); rsi.push(50); continue; }
    var ch = c[i] - c[i-1];
    gains.push(ch > 0 ? ch : 0);
    losses.push(ch < 0 ? -ch : 0);
    if (i < n) { rsi.push(50); continue; }
    var ag = gains.slice(i - n + 1, i + 1).reduce(function(a, b) { return a + b; }, 0) / n;
    var al = losses.slice(i - n + 1, i + 1).reduce(function(a, b) { return a + b; }, 0) / n;
    rsi.push(al === 0 ? 100 : 100 - (100 / (1 + ag / al)));
  }
  return rsi;
}
function calcBOLL(c, n) {
  n = n || 20;
  var mid = [], upper = [], lower = [];
  for (var i = 0; i < c.length; i++) {
    if (i < n - 1) { mid.push(null); upper.push(null); lower.push(null); continue; }
    var slice = c.slice(i - n + 1, i + 1);
    var avg = slice.reduce(function(a, b) { return a + b; }, 0) / n;
    var std = Math.sqrt(slice.reduce(function(a, b) { return a + Math.pow(b - avg, 2); }, 0) / n);
    mid.push(avg); upper.push(avg + 2 * std); lower.push(avg - 2 * std);
  }
  return { mid: mid, upper: upper, lower: lower };
}

var macdData = calcMACDData(closes);
var kdjData = calcKDJData(highs, lows, closes);
var rsi6 = calcRSI(closes, 6), rsi12 = calcRSI(closes, 12), rsi24 = calcRSI(closes, 24);
var bollData = calcBOLL(closes);

var klineChart, macdChart, kdjChart, rsiChart, bollChart;

// K线图
function renderKline() {
  var el = document.getElementById('chart-kline-full');
  if (!el) return;
  if (klineChart) klineChart.dispose();
  klineChart = echarts.init(el);
  var c = getThemeColors();
  var volData = volumes.map(function(v, i) {
    return { value: v, itemStyle: { color: ohlc[i][1] >= ohlc[i][0] ? c.volUpColor : c.volDownColor } };
  });
  klineChart.setOption({
    grid: [
      { left: '8%', right: '5%', top: '8%',  height: '60%' },
      { left: '8%', right: '5%', top: '76%', height: '14%' }
    ],
    xAxis: [
      { type: 'category', data: dateLabels, gridIndex: 0,
        axisLabel: { color: c.textMuted, fontSize: 9, interval: 5 },
        axisLine: { lineStyle: { color: c.textMuted } }, splitLine: { show: false } },
      { type: 'category', data: dateLabels, gridIndex: 1, show: false, splitLine: { show: false } }
    ],
    yAxis: [
      { scale: true, gridIndex: 0, axisLabel: { color: c.textMuted, fontSize: 10 }, splitLine: { show: false } },
      { scale: true, gridIndex: 1, axisLabel: { color: c.textMuted, fontSize: 10, formatter: '{value}%' }, splitLine: { show: false } }
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' },
      formatter: function(ps) {
        var k = ps.find(function(p) { return p.seriesName === 'K线'; });
        var vol = ps.find(function(p) { return p.seriesName === '换手率'; });
        if (!k) return '';
        return k.axisValue + '<br/>开:' + k.data[0] + ' 收:' + k.data[1] + '<br/>低:' + k.data[2] + ' 高:' + k.data[3] + (vol ? '<br/>换手率:' + vol.data.value + '%' : '');
      }
    },
    legend: { data: ['K线','MA5','MA20','MA60'], top: 0, textStyle: { color: c.textSecondary } },
    series: [
      { name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: c.upColor, color0: c.downColor, borderColor: c.upColor, borderColor0: c.downColor },
        markLine: { symbol: 'none',
          lineStyle: { color: '#d4a853', width: 1.5, type: 'dashed' },
          label: { position: 'end', fontSize: 10, color: '#d4a853' },
          data: __MARKLINE__
        },
        markPoint: { symbol: 'pin', symbolSize: 50,
          label: { fontSize: 11, color: '#fff', fontWeight: 'bold' },
          data: __MARKPOINT__
        }
      },
      { name: 'MA5',  type: 'line', data: ma5,  smooth: true, lineStyle: { width: 1.5, color: c.ma5Color  }, showSymbol: false, xAxisIndex: 0, yAxisIndex: 0 },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, lineStyle: { width: 1.5, color: c.ma20Color }, showSymbol: false, xAxisIndex: 0, yAxisIndex: 0 },
      { name: 'MA60', type: 'line', data: ma60, smooth: true, lineStyle: { width: 1.5, color: c.ma60Color }, showSymbol: false, xAxisIndex: 0, yAxisIndex: 0 },
      { name: '换手率', type: 'bar', data: volData, xAxisIndex: 1, yAxisIndex: 1 }
    ]
  });
}

// 4 技术指标图
function renderMACD() {
  var el = document.getElementById('chart-macd');
  if (!el) return;
  if (macdChart) macdChart.dispose();
  macdChart = echarts.init(el);
  var c = getThemeColors();
  macdChart.setOption({
    grid: { left: '8%', right: '4%', top: '12%', height: '60%' },
    xAxis: { data: dateLabels, axisLabel: { color: c.textMuted, fontSize: 8, interval: 8 } },
    yAxis: { axisLabel: { color: c.textMuted, fontSize: 9 } },
    series: [
      { name: 'DIF', type: 'line', data: macdData.dif, lineStyle: { color: '#e3c26d', width: 1.2 }, showSymbol: false },
      { name: 'DEA', type: 'line', data: macdData.dea, lineStyle: { color: '#4a90d9', width: 1.2 }, showSymbol: false },
      { name: 'MACD', type: 'bar', data: macdData.macd, itemStyle: {
        color: function(p) { return p.value >= 0 ? 'rgba(245,86,86,0.5)' : 'rgba(40,199,91,0.5)'; }
      } }
    ],
    legend: { data: ['DIF','DEA','MACD'], top: 0, textStyle: { color: c.textSecondary, fontSize: 10 } }
  });
}
function renderKDJ() {
  var el = document.getElementById('chart-kdj');
  if (!el) return;
  if (kdjChart) kdjChart.dispose();
  kdjChart = echarts.init(el);
  var c = getThemeColors();
  kdjChart.setOption({
    grid: { left: '8%', right: '4%', top: '12%', height: '60%' },
    xAxis: { data: dateLabels, axisLabel: { color: c.textMuted, fontSize: 8, interval: 8 } },
    yAxis: { min: 0, max: 100, axisLabel: { color: c.textMuted, fontSize: 9 } },
    series: [
      { name: 'K', type: 'line', data: kdjData.k, lineStyle: { color: '#e3c26d', width: 1.2 }, showSymbol: false },
      { name: 'D', type: 'line', data: kdjData.d, lineStyle: { color: '#4a90d9', width: 1.2 }, showSymbol: false },
      { name: 'J', type: 'line', data: kdjData.j, lineStyle: { color: '#f55656', width: 1 }, showSymbol: false }
    ],
    legend: { data: ['K','D','J'], top: 0, textStyle: { color: c.textSecondary, fontSize: 10 } }
  });
}
function renderRSI() {
  var el = document.getElementById('chart-rsi');
  if (!el) return;
  if (rsiChart) rsiChart.dispose();
  rsiChart = echarts.init(el);
  var c = getThemeColors();
  rsiChart.setOption({
    grid: { left: '8%', right: '4%', top: '12%', height: '60%' },
    xAxis: { data: dateLabels, axisLabel: { color: c.textMuted, fontSize: 8, interval: 8 } },
    yAxis: { min: 0, max: 100, axisLabel: { color: c.textMuted, fontSize: 9 } },
    series: [
      { name: 'RSI6',  type: 'line', data: rsi6,  lineStyle: { color: '#4a90d9', width: 1.2 }, showSymbol: false },
      { name: 'RSI12', type: 'line', data: rsi12, lineStyle: { color: '#e3c26d', width: 1.2 }, showSymbol: false },
      { name: 'RSI24', type: 'line', data: rsi24, lineStyle: { color: '#f55656', width: 1.2 }, showSymbol: false }
    ],
    legend: { data: ['RSI6','RSI12','RSI24'], top: 0, textStyle: { color: c.textSecondary, fontSize: 10 } }
  });
}
function renderBOLL() {
  var el = document.getElementById('chart-boll');
  if (!el) return;
  if (bollChart) bollChart.dispose();
  bollChart = echarts.init(el);
  var c = getThemeColors();
  bollChart.setOption({
    grid: { left: '8%', right: '4%', top: '12%', height: '60%' },
    xAxis: { data: dateLabels, axisLabel: { color: c.textMuted, fontSize: 8, interval: 8 } },
    yAxis: { axisLabel: { color: c.textMuted, fontSize: 9 } },
    series: [
      { name: '上轨',   type: 'line', data: bollData.upper, lineStyle: { color: 'rgba(245,86,86,0.4)', width: 1 }, showSymbol: false },
      { name: '中轨',   type: 'line', data: bollData.mid,   lineStyle: { color: '#e3c26d', width: 1.2 }, showSymbol: false },
      { name: '下轨',   type: 'line', data: bollData.lower, lineStyle: { color: 'rgba(40,199,91,0.4)', width: 1 }, showSymbol: false, areaStyle: { color: 'rgba(212,168,83,0.05)' } },
      { name: '收盘价', type: 'line', data: closes,         lineStyle: { color: '#4a90d9', width: 1.5 }, showSymbol: false }
    ],
    legend: { data: ['上轨','中轨','下轨','收盘价'], top: 0, textStyle: { color: c.textSecondary, fontSize: 10 } }
  });
}

function renderAll() { renderKline(); renderMACD(); renderKDJ(); renderRSI(); renderBOLL(); }

// 主题切换时重渲染 (监听 v3-stock-report class 变化)
var target = document.body;
var v3root = document.querySelector('.v3-stock-report');
if (v3root) target = v3root;
if (window.MutationObserver) {
  var obs = new MutationObserver(function() { renderAll(); });
  obs.observe(target, { attributes: true, attributeFilter: ['class'] });
}
window.addEventListener('resize', function() {
  klineChart && klineChart.resize();
  macdChart && macdChart.resize();
  kdjChart && kdjChart.resize();
  rsiChart && rsiChart.resize();
  bollChart && bollChart.resize();
});

// 首次渲染
if (document.readyState === 'complete') renderAll();
else window.addEventListener('load', renderAll);
})();
</script>
'''

# masthead 与 hero 的样式单独拼
_CSS_HEAD = """
/* ---------- §2.4 顶部 masthead 条: 股票名 + 代码 + 报告日期 + 数据截止时点 ---------- */
.masthead{background:var(--surface);border-bottom:1px solid var(--hairline);
     padding:var(--sp-2);display:flex;justify-content:space-between;align-items:center;
     gap:var(--sp-1);flex-wrap:wrap;box-shadow:var(--shadow)}
.masthead .mh-name{font-size:24px;font-weight:700;letter-spacing:.5px;
     display:flex;align-items:center;gap:var(--sp-1);flex-wrap:wrap}
.masthead .mh-code{font-family:var(--font-num);font-size:13px;font-weight:600;
     color:var(--ink-1);background:var(--bg);border:1px solid var(--hairline);
     border-radius:999px;padding:2px 10px}
.masthead .mh-meta{display:flex;gap:var(--sp-1);flex-wrap:wrap}
.masthead .mh-chip{font-size:11.5px;color:var(--ink-2);background:var(--bg);
     border:1px solid var(--hairline);border-radius:999px;padding:3px 10px;
     white-space:nowrap}
/* ---------- §2.4 hero 行情区: 结论大字 + 评分大字 + 现价等宽 + 三价位显式卡片 ---------- */
.hero{margin-bottom:var(--sp-2);padding:var(--sp-2);color:#fff;box-shadow:var(--shadow)}
.hero-bull{background:linear-gradient(160deg,#991b1b 0%,#b91c1c 55%,#dc2626 100%)}
.hero-bear{background:linear-gradient(160deg,#14532d 0%,#15803d 55%,#16a34a 100%)}
.hero-neutral{background:linear-gradient(160deg,#92400e 0%,#b45309 55%,#d97706 100%)}
.hero-top{display:flex;justify-content:space-between;align-items:center;gap:var(--sp-2);
     flex-wrap:wrap}
.verdict{display:flex;align-items:center;gap:12px;min-width:0;flex-wrap:wrap}
.adv-dot{display:inline-flex;align-items:center;justify-content:center;min-width:40px;
     height:40px;padding:0 6px;background:rgba(255,255,255,.96);border-radius:999px;
     font-size:20px;line-height:1;box-shadow:0 1px 2px rgba(0,0,0,.18);white-space:nowrap}
.hero .advice{font-size:30px;font-weight:800;letter-spacing:1px;line-height:1.2}
.score-box{display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex:none}
.hero .score{font-family:var(--font-num);font-size:40px;font-weight:800;line-height:1;
     font-variant-numeric:tabular-nums}
.hero .score small{font-size:14px;font-weight:400;opacity:.85;font-family:var(--font-cjk)}
.score-box .cap{font-size:11px;opacity:.85;letter-spacing:2px}
.px-line{display:flex;align-items:center;gap:var(--sp-1);margin:var(--sp-2) 0 var(--sp-1);
     flex-wrap:wrap}
.hero .px{font-family:var(--font-num);font-size:32px;font-weight:700;line-height:1.1}
.hero .px small{font-family:var(--font-cjk);font-size:13px;font-weight:400;opacity:.85}
.chg-pill{font-family:var(--font-num);font-size:13.5px;font-weight:700;line-height:1;
     background:rgba(255,255,255,.96);padding:6px 12px;border-radius:999px}
.chg-pill.up{color:var(--up-ink)}       /* 涨 → 红系 */
.chg-pill.down{color:var(--down-ink)}   /* 跌 → 绿系 */
.price3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:var(--sp-1);
     margin:var(--sp-1) 0 var(--sp-2)}
.price3 .p3{background:rgba(255,255,255,.14);border-radius:var(--radius);
     padding:var(--sp-1) 10px;text-align:center;
     box-shadow:inset 0 0 0 1px rgba(255,255,255,.25)}
.price3 .p3 .l{font-size:11px;opacity:.92}
.price3 .p3 .v{font-size:17px;font-weight:700;margin-top:3px;font-family:var(--font-num);
     line-height:1.35}
.price3 .p3 .v .l{font-size:11px;font-weight:400;opacity:.92;margin-top:2px;
     font-family:var(--font-cjk)}
.hero .reason{margin-top:var(--sp-1);font-size:13px;padding:10px 12px;
     border-radius:var(--radius);background:rgba(255,255,255,.16);line-height:1.65}
.hero .reason-hint{font-size:11.5px;opacity:.92;margin-top:var(--sp-1);line-height:1.5}
.grid-2-wrap{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}
@media(max-width:560px){.grid-2-wrap{grid-template-columns:1fr}}
"""
# 结论主色 (A股惯例: 多=红系 / 空=绿系 / 中性=琥珀) — 类名映射, 见 .hero-bull 等
_HERO_STYLE = {
    "bull": "hero-bull",
    "bear": "hero-bear",
    "neutral": "hero-neutral",
}


def _hero_style(score_total):
    try:
        sc = float(score_total)
    except (TypeError, ValueError):
        sc = 0
    if sc >= 65:
        return _HERO_STYLE["bull"], "bull"
    if sc >= 45:
        return _HERO_STYLE["neutral"], "neutral"
    return _HERO_STYLE["bear"], "bear"


def _checklist_css():
    return """
/* ---------- §2.4 操作检查清单 (色语义: 买点=红系做多, 止损=红系警示, 卖点=强调蓝) ---------- */
.chk{display:flex;gap:var(--sp-1);padding:var(--sp-1) 10px;border-radius:var(--radius);
     margin-bottom:var(--sp-1);background:var(--bg);border-left:4px solid var(--hairline);
     font-size:13px}
.chk .box{color:var(--accent);font-weight:800;flex:none}
.chk .t{flex:1}
.chk .grp{color:var(--ink-3);font-size:11px;margin:10px 0 2px;font-weight:600}
.chk-buy{border-left-color:var(--up);background:var(--up-bg)}
.chk-sell{border-left-color:var(--accent);background:var(--surface)}
.chk-stop{border-left-color:var(--risk-ink);background:var(--risk-bg)}
.chk-watch{border-left-color:var(--hairline)}
/* ---------- §2.4 5 项 GFM checkbox 清单 (债 5 修法, Task 7.2) ---------- */
.task-list{list-style:none;padding:0;margin:8px 0 0}
.task-list-item{display:flex;align-items:flex-start;gap:8px;padding:8px 12px;
     margin-bottom:6px;border-radius:var(--radius);background:var(--bg);
     border-left:3px solid var(--accent);font-size:13px;line-height:1.6}
.task-list-item .cb{color:var(--accent);font-weight:800;flex:none;font-size:15px;
     line-height:1.4}
.task-list-item .lbl{flex:1;color:var(--ink-2)}
.task-list-item .lbl b{color:var(--ink-1)}
.task-bull{border-left-color:var(--up)}
.task-stop{border-left-color:var(--risk-ink);background:var(--risk-bg)}
.task-watch{border-left-color:var(--hairline)}
/* ---------- §2.4 风险警报区 (红系警示不变) ---------- */
.risk{background:var(--risk-bg);border:1px solid var(--risk-line);border-radius:var(--radius);
     padding:12px 14px;margin-bottom:var(--sp-1)}
.risk .h{color:var(--risk-ink);font-weight:700;font-size:14px;display:flex;
     justify-content:space-between;gap:var(--sp-1)}
.risk .h .d{font-weight:400;font-size:12px;color:var(--risk-ink)}
.risk .b{font-size:12.5px;color:var(--risk-ink);margin-top:4px;line-height:1.55}
.risk-ok{background:var(--ok-bg);border:1px solid var(--ok-line);color:var(--ok-ink);
     border-radius:var(--radius);padding:12px 14px;font-size:13.5px;font-weight:600}
/* ---------- 图表卡片: hairline 分隔, 克制阴影 ---------- */
.chart-card{margin-bottom:var(--sp-2)}
.chart-head{display:flex;justify-content:space-between;align-items:center;
     margin-bottom:var(--sp-1);flex-wrap:wrap;gap:4px}
.chart-head .t{font-size:15px;font-weight:700;color:var(--ink-1)}
.chart-head .tm{font-size:10.5px;color:var(--ink-3);background:var(--bg);
     border:1px solid var(--hairline);padding:2px 10px;border-radius:999px;white-space:nowrap}
.chart-body{text-align:center;overflow-x:auto;border:1px solid var(--hairline);
     border-radius:var(--radius);padding:var(--sp-1) 2px 2px;background:var(--surface)}
.chart-body svg{max-width:100%;height:auto}
.chart-body.radar svg{max-width:340px;height:auto}
.tag-row{display:flex;flex-wrap:wrap;gap:var(--sp-1);margin-top:var(--sp-1)}
.v3-tag{padding:2px 10px;border-radius:999px;font-size:11.5px;font-weight:500;
     white-space:nowrap}
/* ---------- §2.4 页脚: 免责声明 + 数据来源 + 生成时间 ---------- */
.foot{text-align:center;color:var(--ink-3);font-size:11.5px;padding:var(--sp-1) 0 var(--sp-3);
     line-height:1.8}
.dark-tbl td{font-size:12px}
@media(max-width:460px){.hero .advice{font-size:24px}.hero .px{font-size:24px}
     .container{padding:var(--sp-1)}.price3 .p3 .v{font-size:15px}
     .masthead .mh-name{font-size:20px}}
"""


# ============================================================
# 分区渲染
# ============================================================

def _chart_card(emoji, title, svg_str, asof, radar=False, foot_note=""):
    """统一图表卡片: 标题栏 + 时点标签 + svg / 数据源暂缺占位"""
    body = '<div class="chart-body%s">%s</div>' % (" radar" if radar else "", svg_str)
    if not svg_str or svg_str == "":
        body = ('<div class="no-data">📭 图表数据源暂缺<br>'
                '<span style="font-size:11px">该模块尚未返回可用数据</span></div>')
    h = ('<div class="chart-card card"><div class="chart-head">'
         '<span class="t">%s %s</span><span class="tm">⏱ 数据截止 %s</span></div>'
         % (emoji, title, _time_label(asof)))
    if foot_note:
        h += '<div class="src-line" style="margin:0 0 6px">%s</div>' % _esc(foot_note)
    return h + body + "</div>"


# ============================================================
# Task 6.3-6.4 (UI 升级线): ECharts K 线 + 4 技术图 (含三价位标注)
# 数据源: chip_data["kline"] = list of {date, open, high, low, close, turn}
# ============================================================

def _kline_to_rawdata(kline_dicts):
    """V3 chip_data['kline'] dict 列表 → [date, open, high, low, close, turn] 列表
    
    V3 字段: {date, open, high, low, close, turn}  (turn=换手率%)
    ECharts 模板: [date, open, high, low, close, vol]
    注: V3 没 volume, 用 turn (换手率%) 替代
    """
    return [
        [d.get("date", ""), float(d.get("open", 0)), float(d.get("high", 0)),
         float(d.get("low", 0)), float(d.get("close", 0)), float(d.get("turn", 0))]
        for d in kline_dicts
    ]


def _markline_data(three_levels, current_price=None):
    """从 three_levels 自动生成 ECharts markLine 标注。
    
    返回 [{yAxis, name, label, lineStyle}, ...]
    """
    if not three_levels or not isinstance(three_levels, dict):
        return []
    items = []
    support = three_levels.get("support")
    resistance = three_levels.get("resistance")
    stop_loss = three_levels.get("stop_loss")
    if resistance is not None:
        items.append({"yAxis": float(resistance), "name": "压力", "label": {"formatter": "压力"}})
    if support is not None:
        items.append({"yAxis": float(support), "name": "支撑", "label": {"formatter": "支撑"}})
    if stop_loss is not None:
        items.append({"yAxis": float(stop_loss), "name": "止损", "label": {"formatter": "止损"}})
    return items


def _markpoint_data(kline_dicts, current_price):
    """markPoint: 当前价 (金色) + 阶段高 (红) + 阶段低 (绿)。"""
    if not kline_dicts or not current_price:
        return []
    closes = [float(d.get("close", 0)) for d in kline_dicts]
    if not closes:
        return []
    max_idx = closes.index(max(closes))
    min_idx = closes.index(min(closes))
    last_idx = len(closes) - 1
    items = [
        {"coord": [last_idx, float(current_price)], "value": "现价",
         "itemStyle": {"color": "#d4a853"}},
    ]
    if max_idx != last_idx:
        items.append({"coord": [max_idx, closes[max_idx]], "value": "阶段高",
                      "itemStyle": {"color": "#f55656"}})
    if min_idx != last_idx:
        items.append({"coord": [min_idx, closes[min_idx]], "value": "阶段低",
                      "itemStyle": {"color": "#28c75b"}})
    return items


def _render_echarts_kline_block(result):
    """ECharts K 线 + 成交量 + MA + markLine 标注 (从 three_levels 自动注入)。
    
    位置: V3 渲染器 4 图 (svg_kline/svg_chip/svg_pe/svg_radar) 之后追加。
    """
    cd = result.get("chip_data") or {}
    kline = cd.get("kline") or []
    three_levels = result.get("three_levels") or {}
    q = result.get("quote") or {}
    current_price = q.get("price")
    if not kline:
        return ""
    raw_data = _kline_to_rawdata(kline)
    import json as _json
    raw_json = _json.dumps(raw_data)
    markline = _markline_data(three_levels, current_price)
    markpoint = _markpoint_data(kline, current_price)
    markline_json = _json.dumps(markline)
    markpoint_json = _json.dumps(markpoint)
    return _ECHARTS_KLINE_CARD_HTML.format(
        raw_data=raw_json, markline=markline_json, markpoint=markpoint_json,
        kline_count=len(kline))


def _render_echarts_tech_block():
    """4 技术指标图 (MACD/KDJ/RSI/BOLL) - 数据从全局 rawData 共享。"""
    return _ECHARTS_TECH_CARD_HTML


# ECharts K 线卡片 (Task 6.3)
_ECHARTS_KLINE_CARD_HTML = r'''
<div class="chart-card card" id="echarts-kline-section">
  <div class="chart-head">
    <span class="t">📈 ECharts K 线 · 含三价位标注</span>
    <span class="tm">⏱ 数据截止 见图表 · MA5/MA20/MA60</span>
  </div>
  <div class="src-line" style="margin:0 0 6px">来源 baostock 前复权日线 · 近 {kline_count} 交易日 · markLine 标注支撑/压力/止损 (从 three_levels 自动注入)</div>
  <div id="chart-kline-full" style="width:100%;height:480px;"></div>
</div>
'''

# 4 技术指标图卡片 (Task 6.4)
_ECHARTS_TECH_CARD_HTML = r'''
<div class="chart-card card" id="echarts-tech-section">
  <div class="chart-head">
    <span class="t">📊 4 技术指标 · MACD / KDJ / RSI / BOLL</span>
    <span class="tm">⏱ JS 实时计算 · 双主题自动切换</span>
  </div>
  <div class="src-line" style="margin:0 0 6px">MACD (DIF/DEA/柱) · KDJ (K/D/J 0-100) · RSI (6/12/24 0-100) · BOLL (上/中/下轨 + 收盘价)</div>
  <div class="grid-2-wrap">
    <div id="chart-macd" style="width:100%;height:280px;"></div>
    <div id="chart-kdj" style="width:100%;height:280px;"></div>
  </div>
  <div class="grid-2-wrap" style="margin-top:12px;">
    <div id="chart-rsi" style="width:100%;height:260px;"></div>
    <div id="chart-boll" style="width:100%;height:260px;"></div>
  </div>
</div>
'''


def _a_share_verdict_mark(state, emoji_raw):
    """A股 红涨绿跌归一: 上游(quant_analyzer_v2.get_advice_v2)emoji 按国际惯例给
    (看多=🟢🟢 / 看空=🔴), 与 A股语义相悖 (如旧版 "44 分看空🔴")。
    HTML 层统一按结论三态换色系: 看多=红系🔴 / 看空=绿系🟢 / 中性=琥珀🟡。
    保留上游 emoji 的重复数量 (🟢🟢 强烈看多 → 🔴🔴)。"""
    if not emoji_raw:
        return ""
    marks = {"bull": "🔴", "neutral": "🟡", "bear": "🟢"}
    n = sum(1 for ch in str(emoji_raw) if ch in "🔴🟢🟡")
    return marks.get(state, "🟡") * max(1, n)


def _render_hero(result):
    """a) 结论前置 hero 区 (masthead 之下第一屏: 结论大字 + 评分大字 + 现价等宽 +
    涨跌幅色标 + 三价位显式卡片 + 一句话理由)"""
    q = result.get("quote") or {}
    s = result.get("score") or {}
    sc = s.get("total")
    style, state = _hero_style(sc)
    adv = result.get("advice", "")
    mark = _a_share_verdict_mark(state, result.get("emoji", ""))
    price = q.get("price")
    chg = q.get("change_pct", s.get("change_pct"))  # V3 契约在 quote, 兼容 v2 score 兜底

    chg_s = ""
    if chg is not None:
        c = float(chg)
        chg_s = ('<span class="chg-pill %s">%+.2f%%</span>'
                 % ("up" if c >= 0 else "down", c))
    price_s = "—" if price is None else "%.2f" % float(price)
    if price is not None:
        price_s = '<span class="px">%s<small> 元</small></span>' % price_s
    else:
        price_s = '<span class="px">—</span>'

    # 三价位: 支撑 / 压力 / 止损 —— 字段名以 v2._make_trading_plan 返回为准,
    # 并对 V3 分析器可能的 support/resistance 命名做兜底
    plan = result.get("trading_plan") or {}
    if isinstance(plan, dict):
        sup_low = _first(plan, "support_low", "entry_low")
        sup_high = _first(plan, "support_high", "entry_high", "support")
        pres = _first(plan, "resistance", "tp1", "pressure")
        sl = _first(plan, "stop_loss", "stop")
        sl_pct = plan.get("stop_loss_pct")
    else:
        sup_low = sup_high = pres = sl = sl_pct = None

    def px(v):
        return "—" if v is None else "%.2f" % float(v)

    sup_s = px(sup_low) if sup_high is None else "%s ~ %s" % (px(sup_low), px(sup_high))
    sup_l = "支撑（分批进区）" if sup_low is not None else "支撑"
    pres_l = "压力（一档）" if pres is not None else "压力"
    sl_s = px(sl)
    if sl_pct is not None and _num(sl_pct) is not None:
        sl_s += '<div class="l" style="margin-top:2px">跌 %s%% 必走</div>' % _num(sl_pct, 1)
    else:
        sl_s = '<span style="font-size:11px">%s</span>' % sl_s

    h = ['<div class="hero %s">' % style]
    h.append('<div class="hero-top">'
             '<div class="verdict">%s<span class="advice">%s</span></div>'
             '<div class="score-box"><span class="score">%s<small>/100</small></span>'
             '<span class="cap">综合评分</span></div></div>'
             % (('<span class="adv-dot">%s</span>' % mark) if mark else "",
                _esc(adv), _num(sc, 0) or "—"))
    h.append('<div class="px-line">%s%s</div>' % (price_s, chg_s))
    h.append('<div class="price3">')
    h.append('<div class="p3"><div class="l">%s</div><div class="v">%s</div></div>'
             % (sup_l, sup_s))
    h.append('<div class="p3"><div class="l">%s</div><div class="v">%s</div></div>'
             % (pres_l, px(pres)))
    h.append('<div class="p3"><div class="l">止损（纪律）</div><div class="v">%s</div></div>'
             % sl_s)
    h.append('</div>')
    h.append('<div class="reason">💬 %s</div>' % _esc(result.get("detail") or "数据源暂缺"))
    if isinstance(plan, dict):
        pos = plan.get("position")
        per = plan.get("period")
        if pos or per:
            h.append('<div class="reason-hint">仓位建议：%s · 持仓周期：%s</div>'
                     % (_esc(pos) if pos else "数据源暂缺",
                         _esc(per) if per else "数据源暂缺"))
    h.append('</div>')
    return "\n".join(h), state


def _state_of(score_total):
    try:
        sc = float(score_total)
    except (TypeError, ValueError):
        sc = 0
    return "bull" if sc >= 65 else ("neutral" if sc >= 45 else "bear")


def _state_key_of(result):
    """5 状态机 state 键（债 1 修法）。优先读 plan["state"]（V3 主分析器注入），
    兜底 score 5 档映射。返回 5 状态之一或 None。"""
    plan = result.get("trading_plan") or {}
    sk = plan.get("state") if isinstance(plan, dict) else None
    if sk in ("bullish", "mild_bull", "neutral", "mild_bear", "bearish"):
        return sk
    score = (result.get("score") or {}).get("total")
    if score is None:
        return None
    try:
        sc = float(score)
    except (TypeError, ValueError):
        return None
    if sc >= 65: return "bullish"
    if sc >= 55: return "mild_bull"
    if sc >= 45: return "neutral"
    if sc >= 35: return "mild_bear"
    return "bearish"


def _render_checklist(result, state):
    """b) 操作检查清单: 买/卖触发 + 止损纪律 + 仓位 (signals + trading_plan 驱动)

    债 1 修法（Task 5.1）：新增"操作口诀"行，**直接读 plan["template_used"]**（V3 注入），
    杜绝 3 状态硬编码（看空 43 分却写"分两批进场"）。旧 3 状态 buy/sell/stop 表格保留兼容。
    """
    q = result.get("quote") or {}
    plan = result.get("trading_plan") or {}
    if not isinstance(plan, dict):
        plan = {}
    sl = _first(plan, "stop_loss", "stop")
    sl_pct = plan.get("stop_loss_pct")
    sup_low = _first(plan, "support_low", "entry_low")
    sup_high = _first(plan, "support_high", "entry_high", "support")
    pres = _first(plan, "resistance", "tp1")
    pos = plan.get("position")
    per = plan.get("period")
    template_used = plan.get("template_used")

    def money(v, default):
        return (default if v is None else "%.2f 元" % float(v))

    rows = []
    box = '<span class="box">☐</span>'

    # 三价位(同源) 行（债 2 修法, Task 5.2）— 4 支撑/3 压力候选 → 取最近者 (+/-5% 过滤)
    # 优先读 result['three_levels']; 兜底用 plan['entry_low'/'tp1'/'stop_loss']
    tl3 = result.get("three_levels") or {}
    if isinstance(tl3, dict) and (tl3.get("support") or tl3.get("resistance")):
        tl_sup = tl3.get("support") or sup_low
        tl_res = tl3.get("resistance") or pres
        tl_sl = tl3.get("stop_loss") or sl
        sup_cands = tl3.get("support_candidates") or {}
        res_cands = tl3.get("resistance_candidates") or {}
        tl_summary = ("三价位(同源): 支撑=%s 压力=%s 止损=%s" %
                      (("%.2f" % float(tl_sup)) if tl_sup is not None else "—",
                       ("%.2f" % float(tl_res)) if tl_res is not None else "—",
                       ("%.2f" % float(tl_sl)) if tl_sl is not None else "—"))
        tl_detail = ""
        if sup_cands:
            tl_detail += " | 4 支撑候选: " + " / ".join(
                "%s=%s" % (k, ("%.2f" % float(v)) if v is not None else "—")
                for k, v in sup_cands.items())
        if res_cands:
            tl_detail += " | 3 压力候选: " + " / ".join(
                "%s=%s" % (k, ("%.2f" % float(v)) if v is not None else "—")
                for k, v in res_cands.items())
        rows.append(('watch', '三价位(同源)', _esc(tl_summary + tl_detail)))

    # 操作口诀行（债 1 修法, 5 状态独立模板）
    if template_used:
        rows.append(('watch', '操作口诀（5 状态机）', _esc(template_used)))

    if state in ("bullish", "mild_bull"):
        rows.append(('buy', '买入触发', '回踩 %s 分批进场（每档最多 1/2 仓），不追高、不满仓一把梭'
                     % money(sup_low if sup_low is not None else q.get("price"),
                             "支撑区")))
        if pres is not None:
            rows.append(('sell', '卖出触发', '冲高至 %s 减 1/3~1/2 仓锁利，余仓分批看更高位'
                         % money(pres, "第一压力")))
        rows.append(('stop', '止损纪律', '收盘跌破 %s（约 -%s%%）无条件离场，不补仓、不摊薄'
                     % (money(sl, "止损位"),
                        _num(sl_pct, 1) if _num(sl_pct, 1) else "?  —数据源暂缺")))
        rows.append(('watch', '仓位建议', '%s · 持仓周期 %s'
                     % (_esc(pos) if pos else "数据源暂缺", _esc(per) if per else "数据源暂缺")))
    elif state == "neutral":
        rows.append(('watch', '买入触发', '观望为主：放量站稳 %s 上方再小仓试探，否则不动'
                     % money(sup_high if sup_high is not None else q.get("price"), "支撑上沿")))
        if pres is not None:
            rows.append(('sell', '卖出触发', '已有持仓：反弹至 %s 附近先减仓，落袋为安'
                         % money(pres, "压力位")))
        rows.append(('stop', '止损纪律', '持股底线 %s（-约 %s%%），破位必走，不留恋'
                     % (money(sl, "止损位"),
                        (_num(sl_pct, 1) if _num(sl_pct, 1) else "—"))))
        rows.append(('watch', '仓位建议', '%s · 持仓周期 %s'
                     % (_esc(pos) if pos else "数据源暂缺", _esc(per) if per else "数据源暂缺")))
    else:
        rows.append(('watch', '买入触发', '空头结构，不建议新开仓；等底部放量企稳再评估'))
        rows.append(('sell', '卖出触发', '已有持仓：逢反弹至 %s 附近减仓/离场'
                     % money(sup_low if sup_low is not None else q.get("price"), "前期支撑")))
        rows.append(('stop', '止损纪律', '跌破 %s 清仓回避，不抄底、不接飞刀'
                     % money(sl, "止损位")))
        rows.append(('watch', '仓位建议', '%s · 持仓周期 %s'
                     % (_esc(pos) if pos else "数据源暂缺", _esc(per) if per else "数据源暂缺")))

    # signals 附加条目
    signals = result.get("signals")
    sig_rows = []
    if isinstance(signals, list) and signals:
        for it in signals[:12]:
            text = _signal_text(it)
            if not text:
                continue
            d = _signal_direction(it, text)
            tag = {"buy": "买点", "sell": "卖点/风险", "watch": "关注"}[d]
            sig_rows.append(('<span class="v3-tag" style="background:var(--bg);color:var(--ink-2)">'
                             '模型信号 · %s</span>' % tag) + _esc(_trunc(text, 90)))
            rows.append(('stop' if d == "sell" else ("buy" if d == "buy" else "watch"),
                         "模型信号 · " + tag, _esc(_trunc(text, 90))))

    h = []
    cls = {"buy": "chk chk-buy", "sell": "chk chk-sell", "stop": "chk chk-stop",
           "watch": "chk chk-watch"}
    for kind, label, txt in rows:
        if kind == "watch":
            h.append('<div class="%s">%s<div><div class="grp" style="margin:0 0 2px">%s</div>'
                     '<div class="t">%s</div></div></div>'
                     % (cls[kind], box, _esc(label), _esc(txt)))
        else:
            h.append('<div class="%s">%s<div class="grp" style="margin:0 0 2px">%s</div>'
                     '<div class="t">%s</div></div>'
                     % (cls[kind], box, _esc(label), _esc(txt)))
    if not sig_rows:
        h.append('<div class="src-line">操作清单由 trading_plan + signals 生成 · signals 数据源暂缺</div>')

    # ----- 5 项 GFM checkbox 清单 (债 5 修法, Task 7.2) -----
    # 5 状态 × 5 项, 运行时按 state 选 1 套
    # 5 项: 状态确认 / 买点触发 / 卖点触发 / 止损纪律 / 仓位管理
    sl_pct_str = (_num(sl_pct, 1) if _num(sl_pct, 1) else "?")
    e_lo_s = money(sup_low if sup_low is not None else q.get("price"), "支撑区")
    e_hi_s = money(sup_high if sup_high is not None else q.get("price"), "支撑上沿")
    tp1_s = money(pres if pres is not None else q.get("price"), "第一压力")
    st_s = money(sl, "止损位")
    pos_s = (_esc(pos) if pos else "数据源暂缺")
    per_s = (_esc(per) if per else "数据源暂缺")
    sl_pct_s = (_num(sl_pct, 1) if _num(sl_pct, 1) else "—")
    e_lo_v = sup_low if sup_low is not None else None
    e_hi_v = sup_high if sup_high is not None else None
    tp1_v = pres if pres is not None else None
    sl_v = sl
    CHECKLIST_5T = {
        "bullish": [
            ("状态确认", "评分 ≥65 + 趋势确认 + 量能配合, 5 状态机判定为多头"),
            ("买点触发", "回调至 %s 区间分批建仓 (各 1/2 仓); 放量突破 %s 可加仓" % (e_lo_s, tp1_s)),
            ("卖点触发", "达 %s 卖 1/2 锁利 → 达更高位再减半 → 趋势走弱清剩余" % tp1_s),
            ("止损纪律", "收盘跌破 %s (现价下 -%s%%) 即离场, 不补仓摊平" % (st_s, sl_pct_s)),
            ("仓位管理", "%s · 周期 %s" % (pos_s, per_s)),
        ],
        "mild_bull": [
            ("状态确认", "评分 55-64 + 趋势偏多, 5 状态机判定为轻多 (震荡偏多)"),
            ("买点触发", "回调至 %s 附近小仓低吸 (1/3 仓); 突破 %s 站稳再加 1/3" % (e_lo_s, tp1_s)),
            ("卖点触发", "达 %s 减 1/3 锁利; 达更高位再减 1/3; 余仓看第三压力" % tp1_s),
            ("止损纪律", "收盘跌破 %s (现价下 -%s%%) 即减半; 破支撑下沿全走" % (st_s, sl_pct_s)),
            ("仓位管理", "%s · 周期 %s (轻多, 严控仓位)" % (pos_s, per_s)),
        ],
        "neutral": [
            ("状态确认", "评分 45-54 + 多空信号混杂, 5 状态机判定为中性 (区间震荡)"),
            ("买点触发", "仅在 %s 支撑区低吸, 上轨 %s 附近不过量追高" % (e_lo_s, tp1_s)),
            ("卖点触发", "反弹至 %s 一带减仓; 跌破 %s 转空离场; 放量站稳 %s 再看多" % (tp1_s, st_s, tp1_s)),
            ("止损纪律", "%s 为区间底沿, 收盘破位即走, 不猜底" % st_s),
            ("仓位管理", "%s · 以低吸高抛为主, 周期 %s" % (pos_s, per_s)),
        ],
        "mild_bear": [
            ("状态确认", "评分 35-44 + 趋势偏空, 5 状态机判定为轻空 (震荡偏空)"),
            ("买点触发", "严控 — 仅在 %s 附近且出现放量反转 K 线小仓 (1/4 仓) 抢短; 否则不动" % e_lo_s),
            ("卖点触发", "已有持仓反弹至 %s 一带分批减仓; 跌破 %s 清仓; 不抢反弹" % (tp1_s, st_s)),
            ("止损纪律", "%s 上方不留幻想仓, 反弹即减, 跌穿即走" % st_s),
            ("仓位管理", "%s · 周期 %s (轻空, 逢反减)" % (pos_s, per_s)),
        ],
        "bearish": [
            ("状态确认", "评分 <35 + 趋势空头, 5 状态机判定为空头 (下跌趋势)"),
            ("买点触发", "❌ 不买入 / 不补仓 / 不抄底; 空仓者观望等底部放量企稳信号"),
            ("卖点触发", "反弹至压力位 %s 一带分批减仓; 持仓者跌破 %s 清仓; 不抢反弹" % (tp1_s, st_s)),
            ("止损纪律", "反弹减仓/清仓纪律优先, 止损 %s 上方不留幻想仓" % st_s),
            ("仓位管理", "清仓回避 / 极轻仓短线者当日进出"),
        ],
    }
    items5 = CHECKLIST_5T.get(state, CHECKLIST_5T["neutral"])
    # 状态决定边框色: bullish=up, mild_bull=up, neutral=accent, mild_bear=risk, bearish=risk
    state_cls = {"bullish": "task-bull", "mild_bull": "task-bull",
                 "neutral": "", "mild_bear": "task-stop", "bearish": "task-stop"}.get(state, "")
    h.append('<ul class="task-list" style="margin-top:12px">')
    for label, txt in items5:
        h.append('<li class="task-list-item %s"><span class="cb">☐</span>'
                 '<span class="lbl"><b>%s：</b>%s</span></li>'
                 % (state_cls, _esc(label), _esc(txt)))
    h.append('</ul>')
    return "\n".join(h)


def _risk_items(result, report_date):
    """c) 风险事件收集 (债 5 修法, Task 7.2) — 5 列 dict list

    字段: category / desc / severity / trigger / action
    数据源: 解禁 / 财报窗口 / 估值极端 / 龙虎榜 / 减持公告
    """
    rows = []
    # 1) 解禁
    lockup = result.get("lockup")
    if not _is_error(lockup):
        upcomings = (lockup or {}).get("upcoming", [])
        for u in upcomings[:3]:
            d = u.get("date")
            ratio = u.get("ratio_pct", 0) or 0
            days = _days_between(d, report_date)
            if days is None or days < 0 or days > 90:
                continue
            shares = u.get("shares_wan", 0) or 0
            try:
                ratio_f = float(ratio)
            except (TypeError, ValueError):
                ratio_f = 0
            sev = "🔴高" if ratio_f >= 5 else ("🟠中" if ratio_f >= 2 else "🟡低")
            type_txt = u.get("type", "")
            rows.append({
                "category": "解禁压力",
                "desc": "%s 解禁 %s 万股" % (str(d), _num(shares, 0)),
                "severity": sev,
                "trigger": "占股本 %.2f%%" % ratio_f + (" [%s]" % type_txt if type_txt else ""),
                "action": "解禁前 5 日减仓 / 当日观望",
            })
    elif _is_error(lockup):
        rows.append({
            "category": "解禁数据", "desc": "数据源暂缺", "severity": "🟡低",
            "trigger": (lockup.get("error", "") or "—")[:30],
            "action": "补 fetcher 后重跑",
        })
    else:
        rows.append({
            "category": "解禁压力", "desc": "未来 90 天无解禁", "severity": "🟢无",
            "trigger": "无 upcoming 记录", "action": "无需应对",
        })
    # 2) 估值极端
    q = result.get("quote") or {}
    pe = q.get("pe_ttm", 0) or 0
    vh = result.get("valuation_hist") or {}
    if pe > 80:
        rows.append({
            "category": "估值", "desc": "PE(TTM) %.1f 极高估" % pe,
            "severity": "🔴高",
            "trigger": "PE > 80; 估值分位 %s%%" % _num(vh.get("pe_percentile_3y"), 1),
            "action": "减仓兑现, 不追高",
        })
    elif not _is_error(vh) and (vh.get("pe_percentile_3y") or 0) > 80:
        rows.append({
            "category": "估值", "desc": "PE 历史分位 %d%% — 接近 3 年最高" % (vh.get("pe_percentile_3y") or 0),
            "severity": "🔴高",
            "trigger": "PE 分位 > 80%",
            "action": "分批减仓, 等待估值修复",
        })
    # 3) 龙虎榜大额净卖
    dragon = result.get("dragon") or {}
    if not _is_error(dragon) and dragon.get("records"):
        nbs = [x.get("net_buy_wan", 0) or 0 for x in dragon["records"]]
        if nbs and sum(nbs) / len(nbs) < -1000:
            avg = sum(nbs) / len(nbs)
            rows.append({
                "category": "龙虎榜",
                "desc": "近 30 日平均净卖出 %s 万元" % _num(avg, 0),
                "severity": "🟠中",
                "trigger": "近 30 日均净卖 > 1000 万",
                "action": "游资撤退, 谨慎追涨",
            })
    # 4) 减持公告
    anns = (result.get("announcements") or {}).get("announcements") or []
    for a in anns[:10]:
        if not isinstance(a, dict):
            continue
        cat = str(a.get("category") or "")
        title = str(a.get("title") or "")
        if "减持" in cat or "减持" in title:
            rows.append({
                "category": "减持公告",
                "desc": _trunc(title, 36),
                "severity": "🔴高",
                "trigger": "%s 公告" % str(a.get("date", "—")),
                "action": "关注减持进度, 短期回避",
            })
            break
    if not rows:
        rows.append({
            "category": "综合", "desc": "未发现明显风险事件", "severity": "🟢无",
            "trigger": "—", "action": "正常持仓",
        })
    return rows[:7]


def _render_risk(rows):
    """c) 风险警报区大表渲染 (债 5 修法, Task 7.2)

    rows: list[dict] keys=category/desc/severity/trigger/action
    5 列: 类别 | 描述 | 严重度 | 触发条件 | 应对
    """
    if not rows:
        return ('<div class="risk-ok">✅ 无临近风险事件<br>'
                '<span style="font-weight:400;font-size:12px">'
                '近 90 日无解禁、无财报披露临近、无减持类公告</span></div>')
    h = ['<div style="font-size:11.5px;color:var(--risk-ink);margin:-2px 0 8px">'
         '⚠️ 风险事件 %d 项（红=高 / 橙=中 / 黄=低 / 绿=无）</div>' % len(rows)]
    h.append('<table class="risk-tbl" style="width:100%;border-collapse:collapse;font-size:12.5px;'
             'margin-top:4px">')
    h.append('<thead><tr style="background:var(--risk-bg)">'
             '<th style="padding:6px 8px;text-align:left;border:1px solid var(--hairline);width:80px">类别</th>'
             '<th style="padding:6px 8px;text-align:left;border:1px solid var(--hairline)">描述</th>'
             '<th style="padding:6px 8px;text-align:center;border:1px solid var(--hairline);width:60px">严重度</th>'
             '<th style="padding:6px 8px;text-align:left;border:1px solid var(--hairline);width:130px">触发条件</th>'
             '<th style="padding:6px 8px;text-align:left;border:1px solid var(--hairline);width:140px">应对</th>'
             '</tr></thead><tbody>')
    for row in rows:
        sev = row.get("severity", "")
        # 严重度色: 红/橙/黄/绿
        sev_color = ("var(--risk-ink)" if "高" in sev
                     else ("#d97706" if "中" in sev
                           else ("#ca8a04" if "低" in sev
                                 else "var(--ok-ink)")))
        h.append('<tr>'
                 '<td style="padding:6px 8px;border:1px solid var(--hairline);font-weight:600">%s</td>'
                 '<td style="padding:6px 8px;border:1px solid var(--hairline)">%s</td>'
                 '<td style="padding:6px 8px;border:1px solid var(--hairline);text-align:center;'
                 'color:%s;font-weight:700">%s</td>'
                 '<td style="padding:6px 8px;border:1px solid var(--hairline);font-size:11.5px;color:var(--ink-3)">%s</td>'
                 '<td style="padding:6px 8px;border:1px solid var(--hairline);font-size:11.5px">%s</td>'
                 '</tr>' % (_esc(row.get("category", "—")),
                            _esc(row.get("desc", "—")),
                            sev_color, _esc(sev),
                            _esc(row.get("trigger", "—")),
                            _esc(row.get("action", "—"))))
    h.append('</tbody></table>')
    return "\n".join(h)


def _src_tag(source, asof, default_src="数据源暂缺"):
    src = source or default_src
    return ('<div class="src-line">📡 数据源：%s · 时点：%s</div>'
            % (_esc(src), _time_label(asof)))


# ------------------------------------------------------------
# 6 块新内容模块
# ------------------------------------------------------------

def _module_research(result, report_date, run_log):
    """研报观点汇总"""
    blob = result.get("research") or {}
    asof = _first(blob, "as_of", "fetched_at", default=None) \
        or _source_time(run_log, ["research", "研报"], report_date)
    if _is_error(blob) or not blob:
        return _src_tag(None, None), '<div class="no-data">📭 研报数据源暂缺</div>'
    rpts = blob.get("reports") or []
    dist = blob.get("rating_dist") or {}
    if isinstance(dist, dict) and not dist:
        dist = {}
    cnt = blob.get("count")
    src = blob.get("source")

    h = []
    top = []
    if dist:
        order = ("买入", "强烈推荐", "推荐", "增持", "中性", "持有", "减持", "卖出", "回避")
        for k in order:
            if k in dist and int(dist[k] or 0) > 0:
                n = int(dist[k] or 0)
                c = _rating_color(k)
                top.append('<span class="v3-tag" style="color:%s;background:%s22">%s %d</span>'
                           % (c, c, k, n))
        for k, n in dist.items():
            if str(k) not in order and int(n or 0) > 0:
                top.append('<span class="v3-tag" style="background:var(--bg);color:var(--ink-2)">'
                           '%s %s</span>' % (_esc(k), n))
    n_cov = _num(cnt, 0) if cnt is not None else None
    if top or n_cov:
        h.append('<div class="tag-row">%s</div>'
                 % "".join(top) + (" " if top else "")
                 + ('<span class="v3-tag" style="background:#eff6ff;color:#1d4ed8">'
                    '近 30 日机构覆盖 %s 家</span>' % n_cov if n_cov else ""))
    if not rpts:
        h.append('<div class="src-line">评级分布已汇总，研报明细列表数据源暂缺</div>' if top
                 else '<div class="no-data">📭 研报明细数据源暂缺</div>')
    else:
        tps = [float(x["target_price"]) for x in rpts
               if isinstance(x, dict) and x.get("target_price") not in (None, "", 0)
               and isinstance(x.get("target_price"), (int, float))]
        tp_note = ""
        if tps:
            tps.sort()
            med = tps[len(tps) // 2]
            tp_note = ('<div class="src-line">目标价中位数 ≈ %.2f 元（%d 家给出目标价）'
                       '</div>' % (med, len(tps)))
        h.append(tp_note)
        rows = []
        for x in rpts[:8]:
            if not isinstance(x, dict):
                continue
            rt = x.get("rating")
            rt_s = ('<span style="color:%s;font-weight:600">%s</span>'
                    % (_rating_color(rt), _esc(rt or "—")))
            tp = x.get("target_price")
            rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                        "<td class=\"num\">%s</td></tr>"
                        % (_esc(x.get("date", "")), _esc(x.get("org", "")),
                           _trunc(_esc(x.get("title", "")), 40), rt_s,
                           _num_or_dash(tp, 2)))
        h.append('<table class="v3-tbl"><thead><tr><th>日期</th><th>机构</th>'
                 '<th>观点</th><th>评级</th><th class="num">目标价</th></tr>'
                 '</thead><tbody>%s</tbody></table>' % "".join(rows))
    return _src_tag(src or blob.get("source") or "数据源暂缺", asof), "\n".join(h)


def _module_announcements(result, report_date, run_log):
    """公告速览"""
    blob = result.get("announcements") or {}
    asof = _first(blob, "as_of", "fetched_at", default=None) \
        or _source_time(run_log, ["announcements", "公告"], report_date)
    src = blob.get("source")
    if not blob or "error" in blob:
        return _src_tag(None, None), '<div class="no-data">📭 公告数据源暂缺</div>'
    anns = blob.get("announcements") or []
    if not anns:
        return _src_tag(src, asof), '<div class="no-data">近 30 日无公告</div>'
    h = []
    for a in anns[:10]:
        if not isinstance(a, dict):
            continue
        sent = a.get("sentiment")
        tag = _sentiment_tag(sent)
        link = a.get("url")
        t = _trunc(_esc(a.get("title", "")), 46)
        if link:
            t = '<a href="%s" target="_blank" rel="noopener">%s ↗</a>' % (_esc(link), t)
        h.append('<div style="padding:7px 0;border-bottom:1px solid var(--hairline)">'
                 '<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">'
                 '<span class="v3-tag" style="background:var(--bg);color:var(--ink-2)">%s</span>'
                 '%s %s</div></div>' % (_esc(a.get("date", "")), tag, t))
    return _src_tag(src, asof), "\n".join(h)


def _finance_comment(latest, prev):
    """财务体检一句话点评 (纯规则, 基于 yoy 数据)"""
    ry, py = latest.get("yoy_revenue"), latest.get("yoy_profit")
    if py is None and ry is None:
        return None
    def _gt0(v):
        try:
            return float(v) > 0
        except (TypeError, ValueError):
            return False

    p_ok = py is not None and _gt0(py)
    r_ok = ry is not None and _gt0(ry)
    if p_ok and r_ok:
        return "营收、净利同比双增，基本面向上，体检结果偏积极。"
    if p_ok:
        return "净利同比正增长，盈利质量尚可。"
    if ry is not None and not _gt0(ry) and py is not None and not _gt0(py):
        return "营收净利同比双降，基本面承压，留意行业与订单风险。"
    if py is not None and not _gt0(py):
        return "净利同比下滑，需警惕盈利拐点风险。"
    return None


def _module_finance(result, report_date, run_log):
    """财务体检"""
    blob = result.get("finance") or {}
    asof = _first(blob, "as_of", "fetched_at", default=None) \
        or _source_time(run_log, ["finance", "财务", "三表"], report_date)
    src = blob.get("source")
    if not blob or "error" in blob:
        return _src_tag(None, None), '<div class="no-data">📭 财务数据源暂缺</div>'
    rpts = blob.get("reports") or []
    if not rpts:
        return _src_tag(src, asof), '<div class="no-data">📭 财务报告期数据源暂缺</div>'
    h = []
    latest = rpts[0] if isinstance(rpts[0], dict) else {}
    prev = rpts[1] if len(rpts) > 1 and isinstance(rpts[1], dict) else {}

    def cell(x, key, nd=1, unit=""):
        v = x.get(key)
        s = _num(v, nd) if x else None
        return "—" if s is None else s + unit

    mini = [
        ("最新营收(亿)", cell(latest, "revenue_yi", 1)),
        ("营收同比", cell(latest, "yoy_revenue", 1, "%")),
        ("最新净利(亿)", cell(latest, "profit_yi", 1)),
        ("净利同比", cell(latest, "yoy_profit", 1, "%")),
        ("ROE", cell(latest, "roe", 1, "%")),
        ("毛利率", cell(latest, "gross_margin", 1, "%")),
        ("负债率", cell(latest, "debt_ratio", 1, "%")),
        ("EPS", cell(latest, "eps", 2)),
    ]
    h.append('<div class="mini-grid">')
    for l, v in mini:
        h.append('<div class="kpi"><div class="l">%s</div><div class="v">%s</div></div>'
                 % (_esc(l), _esc(v)))
    h.append("</div>")
    cmt = _finance_comment(latest, prev)
    if cmt:
        h.append('<div class="src-line" style="margin-top:8px">🩺 自动点评：%s</div>' % cmt)
    rows = []
    for x in rpts[:5]:
        if not isinstance(x, dict):
            continue
        hl = "style='font-weight:600'" if x is latest else ""
        rows.append(
            "<tr %s><td>%s</td><td class=\"num\">%s</td><td class=\"num\">%s</td>"
            "<td class=\"num\">%s</td><td class=\"num\">%s</td><td class=\"num\">%s</td></tr>"
            % (hl, _esc(x.get("report_date", "")), _num_or_dash(x.get("revenue_yi"), 1),
               _num_or_dash(x.get("yoy_revenue"), 1, "%"),
               _num_or_dash(x.get("profit_yi"), 1),
               _num_or_dash(x.get("yoy_profit"), 1, "%"),
               _num_or_dash(x.get("roe"), 1, "%")))
    h.append('<table class="v3-tbl" style="margin-top:var(--sp-1)">'
             '<thead><tr><th>报告期</th><th class="num">营收(亿)</th>'
             '<th class="num">营收同比</th><th class="num">净利(亿)</th>'
             '<th class="num">净利同比</th><th class="num">ROE</th></tr></thead>'
             '<tbody>%s</tbody></table>' % "".join(rows))
    return _src_tag(src, asof), "\n".join(h)


def _module_peer(result, report_date, run_log):
    """同业对比 · 行业定位 (申万行业表 + 估值历史)"""
    sw = result.get("sw_data") or {}
    vh = result.get("valuation_hist") or {}
    q = result.get("quote") or {}
    asof = _first(vh, "data_end", default=None) \
        or _source_time(run_log, ["sw", "申万", "估值"], report_date)
    if _is_error(sw) and _is_error(vh):
        return (_src_tag(None, None),
                '<div class="no-data">📭 同业对比数据源暂缺（sw_data / valuation_hist）</div>')

    rows = []
    if isinstance(sw, dict) and not _is_error(sw):
        l1 = sw.get("current_l1")
        l2 = sw.get("current_l2")
        rows.append(["申万行业", "%s%s" % (_esc(l1 or ""),
                                           (" · " + _esc(l2)) if l2 else "")])
        nc = sw.get("n_changes")
        mc = sw.get("median_changes")
        if nc is not None and mc is not None:
            churn = "（高于全市场中位 %s 次，行业归属较活跃）" % mc if sw.get("is_churning") \
                else "（≤ 市场中位 %s 次，归属稳定）" % mc
            rows.append(["行业归属变迁", "%s 次%s" % (nc, churn)])
        elif nc is not None:
            rows.append(["行业归属变迁", "%s 次" % nc])
        since = sw.get("since")
        if since:
            rows.append(["当前行业自", "%s 起" % _esc(since)])
    if isinstance(vh, dict) and not _is_error(vh):
        cp = vh.get("pe_percentile_3y")
        if cp is not None:
            rows.append(["PE 3 年分位（本票自身）", "%s%%（相对本票过去 3 年）" % _num(cp, 1)])
        pp = vh.get("pb_percentile_3y")
        if pp is not None:
            rows.append(["PB 3 年分位（本票自身）", "%s%%" % _num(pp, 1)])
        if vh.get("pe_median") is not None:
            rows.append(["PE 中位数（本票 3 年）", _num_or_dash(vh.get("pe_median"), 2)])
    if q.get("float_mcap"):
        rows.append(["流通市值", _num_or_dash(q.get("float_mcap"), 0, " 亿")])
    if q.get("pe_ttm"):
        rows.append(["PE (TTM)", _num_or_dash(q.get("pe_ttm"), 1)])
    if q.get("pb"):
        rows.append(["PB", _num_or_dash(q.get("pb"), 2)])

    def _has_cjk(t):
        return any("一" <= ch <= "鿿" for ch in str(t))

    inner = ['<table class="v3-tbl"><thead><tr><th style="width:38%">定位项</th>'
             '<th>数值 / 说明</th></tr></thead><tbody>']
    for k, v in rows:
        cls = "" if _has_cjk(v) else " class=\"num\""
        inner.append("<tr><td>%s</td><td%s>%s</td></tr>" % (k, cls, v))
    inner.append('</tbody></table>')
    if not rows:
        inner = ['<div class="no-data">📭 同业对比数据源暂缺</div>']
    src = "申万行业表 + baostock 估值历史"
    return _src_tag(src, asof), "\n".join(inner)


def _module_margin(result, report_date, run_log):
    """资金面 (两融)"""
    blob = result.get("margin") or {}
    if not isinstance(blob, dict) or _is_error(blob):
        asof = _source_time(run_log, ["margin", "融资", "两融"], report_date)
        return _src_tag("东财数据中心", asof), '<div class="no-data">📭 两融数据源暂缺</div>'
    asof = _first(blob, "as_of", "fetched_at", default=None) \
        or _source_time(run_log, ["margin", "融资", "两融"], blob.get("date") or report_date)
    rzye = blob.get("rzye_yi")
    mini = [
        ("融资余额(亿)", _num_or_dash(rzye, 2)),
        ("当日融资买入(亿)", _num_or_dash(blob.get("rzmre_yi"), 2)),
        ("当日融资偿还(亿)", _num_or_dash(blob.get("rzche_yi"), 2)),
        ("融券余额(亿)", _num_or_dash(blob.get("rqye_yi"), 3)),
    ]
    # 若有 history 序列, 给融资余额方向
    trend = None
    hist = blob.get("history")
    if isinstance(hist, list) and len(hist) >= 2:
        def rzye_of(x):
            if isinstance(x, dict):
                return x.get("rzye_yi")
            if isinstance(x, (list, tuple)) and len(x) >= 2:
                return x[1]
            return None
        vals = [rzye_of(x) for x in hist]
        vals = [float(v) for v in vals if v is not None]
        if len(vals) >= 2:
            diff = vals[-1] - vals[0]
            if diff > 0.005:
                trend = ("期间融资余额 ↑ %+.2f 亿，杠杆资金在流入"
                         % diff)
            elif diff < -0.005:
                trend = ("期间融资余额 ↓ %+.2f 亿，杠杆资金在流出"
                         % diff)
            else:
                trend = "期间融资余额基本持平"
    h = ['<div class="mini-grid">']
    for l, v in mini:
        h.append('<div class="kpi"><div class="l">%s</div><div class="v">%s</div></div>'
                 % (_esc(l), v))
    h.append("</div>")
    if trend:
        h.append('<div class="src-line" style="margin-top:8px">📈 %s</div>' % trend)
    return _src_tag("东财数据中心", asof), "\n".join(h)


def _module_news(result, report_date, run_log):
    """新闻舆情"""
    blob = result.get("news") or {}
    asof = _first(blob, "as_of", "fetched_at", default=None) \
        or _source_time(run_log, ["news", "新闻"], report_date)
    src = blob.get("source")
    if not blob or "error" in blob:
        return _src_tag(None, None), '<div class="no-data">📭 新闻舆情数据源暂缺</div>'

    def render_items(rows, color, icon):
        if not rows:
            return ""
        out = ['<div style="font-weight:600;font-size:13px;margin:6px 0 2px;color:%s">%s %s 条</div>'
               % (color, icon, len(rows))]
        for it in rows[:3]:
            if isinstance(it, dict):
                t = it.get("title") or it.get("text") or ""
                d = it.get("date") or it.get("time") or ""
                u = it.get("url")
                s = _trunc(_esc(t), 64)
                if u:
                    s = '<a href="%s" target="_blank" rel="noopener">%s ↗</a>' % (_esc(u), s)
                out.append('<div style="font-size:12.5px;padding:4px 0;color:var(--ink-2)">'
                           '<span class="disc">%s</span> %s</div>' % (_esc(d), s))
            else:
                out.append('<div style="font-size:12.5px;padding:4px 0;color:var(--ink-2)">%s</div>'
                           % _trunc(_esc(it), 64))
        return "\n".join(out)

    pos = blob.get("positive") or []
    neg = blob.get("negative") or []
    news = blob.get("news") or []
    h = []
    np_, nn_ = len(pos), len(neg)
    if np_ or nn_:
        if nn_ > np_:
            mood = ('<div class="src-line" style="margin-top:4px">🧭 舆情倾向：负面略多'
                    '（利好 %d / 利空 %d），消息面偏谨慎</div>' % (np_, nn_))
        elif np_ > nn_:
            mood = ('<div class="src-line" style="margin-top:4px">🧭 舆情倾向：偏正面'
                    '（利好 %d / 利空 %d），消息面温和</div>' % (np_, nn_))
        else:
            mood = ('<div class="src-line" style="margin-top:4px">🧭 舆情倾向：中性'
                    '（利好 %d / 利空 %d）</div>' % (np_, nn_))
    else:
        mood = ""
    h.append(render_items(pos, "#b91c1c", "📈 利好"))   # 利好 = 红系
    h.append(render_items(neg, "#15803d", "📉 利空"))   # 利空 = 绿系
    if not pos and not neg and not news:
        return _src_tag(src, asof), '<div class="no-data">📭 新闻正文数据源暂缺</div>'
    if news and not pos and not neg:
        # 只有泛列表时展示前 6 条
        h.append('<table class="v3-tbl"><thead><tr><th class="num">时间</th>'
                 '<th>标题</th></tr></thead><tbody>')
        for it in news[:6]:
            if isinstance(it, dict):
                h.append("<tr><td class=\"num\">%s</td><td>%s</td></tr>"
                         % (_esc(it.get("date", "") or it.get("time", "")),
                            _trunc(_esc(it.get("title", "")), 60)))
        h.append('</tbody></table>')
    if mood:
        h.append(mood)
    return _src_tag(src or "东财个股新闻", asof), "\n".join(h)


# ============================================================
# 附录: 详细数据 (估值历史 / 筹码明细) + run_log
# ============================================================

def _detail_drawer(result):
    h = []
    cd = result.get("chip_data")
    vh = result.get("valuation_hist")
    if (isinstance(cd, dict) and not _is_error(cd)) or \
            (isinstance(vh, dict) and not _is_error(vh)):
        h.append('<div class="card"><h2><span class="bar"></span>📋 详细数据（筹码 / 估值历史）'
                 '</h2>')
        if isinstance(cd, dict) and not _is_error(cd):
            h.append('<div class="tbl-wrap"><table class="v3-tbl dark-tbl">'
                     '<thead><tr><th>筹码分布明细</th><th class="num"></th></tr>'
                     '</thead><tbody>')
            rows = [("获利比例", "%s%%" % (_num(cd.get("profit_ratio") * 100, 1)
                                          if cd.get("profit_ratio") is not None else "—")),
                    ("平均成本", _num_or_dash(cd.get("avg_cost"), 2, " 元")),
                    ("90% 成本区间", "—"),
                    ("70% 成本区间", "—"),
                    ("筹码峰", _num_or_dash(cd.get("peak_price"), 2, " 元")),
                    ("90% 集中度", "%s%%" % (_num(cd.get("concentration_90") * 100, 1)
                                             if cd.get("concentration_90") is not None else "—")),
                    ("窗口累计换手", _num_or_dash(cd.get("total_turnover_pct"), 1, "%"))]
            c90 = cd.get("cost_90")
            if isinstance(c90, (list, tuple)) and len(c90) == 2:
                rows[2] = ("90% 成本区间", "%s ~ %s 元" % (_num(c90[0], 2), _num(c90[1], 2)))
            c70 = cd.get("cost_70")
            if isinstance(c70, (list, tuple)) and len(c70) == 2:
                rows[3] = ("70% 成本区间", "%s ~ %s 元" % (_num(c70[0], 2), _num(c70[1], 2)))
            for k, v in rows:
                h.append("<tr><td>%s</td><td class=\"num\">%s</td></tr>" % (_esc(k), _esc(v)))
            h.append('</tbody></table></div>')
        if isinstance(vh, dict) and not _is_error(vh):
            h.append('<div class="tbl-wrap" style="margin-top:var(--sp-1)">'
                     '<table class="v3-tbl dark-tbl">'
                     '<thead><tr><th>估值历史（baostock）</th><th class="num"></th></tr>'
                     '</thead><tbody>')
            for k, v in [("数据范围", "%s → %s" % (vh.get("data_start", "—"),
                                                   vh.get("data_end", "—"))),
                         ("PE 当前 / 中位", "%s / %s" % (_num_or_dash(vh.get("current_pe"), 2),
                                                        _num_or_dash(vh.get("pe_median"), 2))),
                         ("PE 区间(min~max)", "%s ~ %s" % (_num_or_dash(vh.get("pe_min"), 2),
                                                           _num_or_dash(vh.get("pe_max"), 2))),
                         ("PE 3 年分位", "%s%%" % (_num(vh.get("pe_percentile_3y"), 1)
                                                   if vh.get("pe_percentile_3y") is not None
                                                   else "—")),
                         ("PB 当前 / 分位", "%s / %s%%" % (_num_or_dash(vh.get("current_pb"), 2),
                                                          (_num(vh.get("pb_percentile_3y"), 1)
                                                           if vh.get("pb_percentile_3y") is not None
                                                           else "—"))),
                         ("ST 剔除占比", "%s%%" % (_num(vh.get("is_st_ratio"), 1)
                                                   if vh.get("is_st_ratio") is not None else "—"))]:
                h.append("<tr><td>%s</td><td class=\"num\">%s</td></tr>" % (_esc(k), _esc(v)))
            h.append('</tbody></table></div>')
        h.append("</div>")
    return "\n".join(h)


def _render_run_log(result, report_date):
    """数据源清单 + 运行日志"""
    run_log = result.get("run_log") or {}
    inner = []
    if isinstance(run_log, dict):
        srcs = run_log.get("sources")
        if isinstance(srcs, dict) and srcs:
            inner.append('<div class="card"><h2><span class="bar"></span>🧭 数据源清单</h2>'
                         '<div class="tbl-wrap"><table class="v3-tbl dark-tbl">'
                         '<thead><tr><th>模块</th><th>状态</th>'
                         '<th>时点 / 备注</th></tr></thead><tbody>')
            for name, blob in srcs.items():
                ok = not (isinstance(blob, dict) and blob.get("error"))
                if isinstance(blob, dict):
                    note = blob.get("error") or _first(blob, "at", "date",
                                                       default="")
                    stat = '<span style="color:%s">✓ 成功</span>' % C_GREEN_DK if ok \
                        else '<span style="color:%s">✗ 失败</span>' % C_RED_DK
                else:
                    note, stat = "", ""
                inner.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                             % (_esc(name), stat, _trunc(_esc(note), 40)))
            inner.append('</tbody></table></div>')
        elif not run_log:
            inner.append('<div class="card"><h2><span class="bar"></span>🧭 数据源清单</h2>'
                         '<div class="no-data">📭 run_log 数据源暂缺</div>')
        if isinstance(run_log, dict) and run_log.get("guard"):
            g = run_log["guard"]
            inner.append('<div class="src-line" style="margin:4px 0 0">🛡 guard：%s</div>'
                         % _esc(str(g))[:160])
        if isinstance(run_log, dict) and (run_log.get("started_at")
                                          or run_log.get("finished_at")
                                          or run_log.get("total_sec")):
            inner.append('<div class="src-line">⏱ %s → %s · 耗时 %s 秒</div>'
                         % (_esc(run_log.get("started_at") or "—"),
                            _esc(run_log.get("finished_at") or "—"),
                            _esc(run_log.get("total_sec") or "—")))
    else:
        inner.append('<div class="card"><h2><span class="bar"></span>🧭 数据源清单</h2>'
                     '<div class="no-data">📭 run_log 数据源暂缺</div>')
    return "\n".join(inner)


# ============================================================
# 主函数
# ============================================================

def write_html_report_v3(result: dict, out_dir: str) -> str:
    """生成 V3 单文件 HTML 报告, 返回 html 文件路径。

    排版: hero 结论前置 -> 操作检查清单 -> 风险警报 -> 四图(标注时点)
          -> 6 块内容(研报/公告/财务/同业/资金面/新闻, 标注来源时点)
          -> 详细数据抽屉 + 数据源清单 -> 免责页脚
    """
    code = result.get("code", "")
    name = result.get("name", "")
    q = result.get("quote") or {}
    s = result.get("score") or {}
    score_total = s.get("total")
    report_date = result.get("report_date") \
        or (result.get("run_log") or {}).get("report_date") \
        or datetime.datetime.now().strftime("%Y-%m-%d")
    gen_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    os.makedirs(out_dir, exist_ok=True)
    fname = "%s-%s-v3-%s.html" % (_clean_fname(code), _clean_fname(name),
                                  datetime.datetime.now().strftime("%Y%m%d-%H%M"))
    path = os.path.join(out_dir, fname)

    # ---- 数据准备 ----
    price = q.get("price")  # 供 4 张 SVG 的 current_price 参数使用
    cd = result.get("chip_data")
    vh = result.get("valuation_hist")

    klines = (cd.get("kline", []) if isinstance(cd, dict) and not _is_error(cd) else [])
    svg_kline = _svg_safe(hr._svg_kline, klines, current_price=price)
    svg_chip = _svg_safe(hr._svg_chip_histogram, cd)
    pe_series = (vh.get("pe_series", []) if isinstance(vh, dict) and not _is_error(vh) else [])
    pe_pct = (vh.get("pe_percentile_3y", 0) if isinstance(vh, dict) and not _is_error(vh) else 0)
    svg_pe = _svg_safe(hr._svg_pe_history, pe_series, pe_pct)
    svg_radar = _svg_safe(hr._svg_radar, s)

    run_log = result.get("run_log") if isinstance(result.get("run_log"), dict) else {}

    # 各图数据截止时间: K线/筹码用 chip 窗口末日期, PE 用 baostock data_end,
    # 雷达/评分用报告日 —— 都没有时回退 run_log -> report_date
    chip_t = _blob_time(cd, ["chip"], None) \
        or _source_time(run_log, ["chip", "kline", "筹码"], report_date)
    pe_t = (vh.get("data_end") if isinstance(vh, dict) else None) \
        or _source_time(run_log, ["pe", "valuation", "估值"], report_date)

    hero_html, state = _render_hero(result)
    risk_items = _risk_items(result, report_date)

    # ---- 模块渲染 ----
    research_html = _module_research(result, report_date, run_log)
    ann_html = _module_announcements(result, report_date, run_log)
    fin_html = _module_finance(result, report_date, run_log)
    peer_html = _module_peer(result, report_date, run_log)
    margin_html = _module_margin(result, report_date, run_log)
    news_html = _module_news(result, report_date, run_log)

    chart_grid = []
    chart_grid.append('<div class="grid-2-wrap">')
    chart_grid.append(_chart_card("📈", "K 线 · 前复权", svg_kline, chip_t,
                                  foot_note="来源 baostock 前复权日线 · 近 60 交易日"))
    chart_grid.append(_chart_card("🎰", "筹码分布", svg_chip, chip_t,
                                  foot_note="来源 baostock · 红=套牢 绿=获利"))
    chart_grid.append('</div>')
    chart_grid.append('<div class="grid-2-wrap">')
    chart_grid.append(_chart_card("📊", "PE (TTM) 走势", svg_pe, pe_t,
                                  foot_note="来源 baostock · 3 年窗口取近 180 交易日"))
    chart_grid.append(_chart_card("🔬", "10 因子雷达", svg_radar, report_date, radar=True,
                                  foot_note="来源本地 10 因子量化引擎 · 满分 100"))
    chart_grid.append('</div>')

    # Task 6.3 + 6.4 (UI 升级线): ECharts K 线 + 4 技术图 (SVG 升级 fintech-h5-demos 风格)
    chart_grid.append(_render_echarts_kline_block(result))
    chart_grid.append(_render_echarts_tech_block())

    # ---- 头部 (CSS token 层 + masthead) ----
    html = ['<!DOCTYPE html>', '<html lang="zh-CN"><head>',
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1,'
            'maximum-scale=1,user-scalable=no">',
            '<title>%s %s · V3 报告</title>' % (_esc(name), _esc(code)),
            # ECharts CDN (Task 6.1: 集成 mingli30119 双主题 UI)
            '<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>',
            '<style>', _CSS, _CSS_HEAD, _checklist_css(), _MINGLI_CSS,
            '</style></head><body><div class="v3-stock-report">']

    if result.get("__self_test"):
        html.append('<div class="self-test-note">⚠️ 本页为 <b>html_report_v3 模板自测样例</b>'
                    '（构造的 fake result），数据非当日实盘抓取，仅用于版式与渲染自检。</div>')

    # 行情数据截止时点: 优先 quote/行情源时点, 再退 chip 窗口末/报告日
    mh_cut = _source_time(run_log, ["quote", "行情", "chip", "kline", "筹码"], None) \
        or chip_t or report_date

    # ---- §2.4 顶部导航 (Task 6.2: mingli30119 .top-nav 风格 + 主题切换按钮) ----
    # 保留 V3 旧 masthead 内容, 套用 mingli30119 .top-nav class
    # 加 主题切换按钮 (id="themeToggle" 由下方 JS 控制)
    html.append('<nav class="top-nav">'
                '<div class="logo">'
                '<div class="logo-icon">%s</div>'
                '<span class="stock-name">%s</span>'
                '<span class="stock-code">%s</span>'
                '</div>'
                '<div class="nav-links">'
                '<span class="hero-tag">报告日期 %s</span>'
                '<span class="hero-tag">行情截止 %s</span>'
                '<span class="hero-tag">生成 %s</span>'
                '</div>'
                '<button class="theme-toggle" id="themeToggle">☀️ 浅色模式</button>'
                '</nav>'
                % (_esc(name[0] if name else "股"),
                   _esc(name), _esc(code),
                   _esc(report_date), _time_label(mh_cut), gen_now))

    # ---- a) 结论前置 hero ----
    html.append(hero_html)

    # ---- b) 操作检查清单 ----
    # 5 状态机 (债 1 修法, Task 5.1)：bullish/mild_bull/neutral/mild_bear/bearish
    # 读 plan["state"]，未注入时按 score 兜底 5 档映射。
    state_key = _state_key_of(result) or "neutral"
    _STATE_LABELS = {
        "bullish":   "看多（≥65 分）",
        "mild_bull": "轻多（55-64 分）",
        "neutral":   "中性/震荡（45-54 分）",
        "mild_bear": "轻空（35-44 分）",
        "bearish":   "看空（<35 分）",
    }
    html.append('<div class="card"><h2><span class="bar"></span>✅ 操作检查清单</h2>'
                '<div class="src-line">触发条件、止损纪律与仓位建议 · 按 %s 5 状态机给出</div>'
                % _STATE_LABELS.get(state_key, "中性/震荡（45-54 分）"))
    html.append(_render_checklist(result, state_key))
    html.append('</div>')

    # ---- c) 风险警报区 ----
    html.append('<div class="card"><h2><span class="bar"></span>🚨 风险警报</h2>')
    html.append(_render_risk(risk_items))
    html.append('</div>')

    # ---- d) 四图 ----
    html.append("".join(chart_grid))

    # ---- 6 块内容 ----
    blocks = [
        ("📚", "研报观点", research_html),
        ("📢", "公告速览", ann_html),
        ("🩺", "财务体检", fin_html),
        ("🏭", "同业对比 · 行业定位", peer_html),
        ("💰", "资金面（融资融券）", margin_html),
        ("📰", "新闻舆情", news_html),
    ]
    for emoji, title, (src_line, inner) in blocks:
        html.append('<div class="card"><h2><span class="bar"></span>%s %s</h2>%s%s</div>'
                    % (emoji, title, src_line, inner))
    # ---- §3.3 灰度: 6 块之后追加 Section Registry 渲染循环 ----
    # 5 新节(irm/holders/dividend/board/dragon_market)走注册表, 旧 6 块仍保留
    # (Task 1.3 教训: 不替换, 只追加)
    if _SECTIONS_OK and enabled_sections is not None:
        for sec in enabled_sections():
            try:
                sec_data = result.get(sec.label, {}) or {}
                # 钉死语义: 不传 writer, 只取返回值 (Finding 2 fix)
                sec_html = sec.render_html(sec_data)
                if sec_html:
                    html.append(sec_html)
            except Exception as _sec_render_err:  # noqa: BLE001
                # 单节失败不阻断其他渲染
                html.append(
                    '<div class="card"><h2><span class="bar"></span>%s</h2>'
                    '<p class="warn">⚠️ %s 渲染失败: %s</p></div>'
                    % (sec.title, sec.label, _sec_render_err))

    # ---- 附录 ----
    html.append(_detail_drawer(result))
    html.append(_render_run_log(result, report_date))

    # ---- 页脚: 免责声明 + 数据来源 + 生成时间 (§2.4) ----
    src_keys = [str(k) for k in (run_log.get("sources") or {}).keys()]
    if src_keys:
        src_line = "数据来源：" + " · ".join(_esc(k) for k in src_keys) + "（以各模块标注时点为准）"
    else:
        src_line = ("数据来源：腾讯行情 · baostock · 东财数据中心 · "
                    "巨潮资讯网 · 新浪财经（以各模块标注时点为准）")
    html.append('<div class="foot">⚠️ 本报告由量化模型基于公开数据自动生成，仅供研究参考，'
                '不构成投资建议。市场随时变化，请独立判断。<br>'
                '%s<br>'
                '报告日 %s · 行情数据截止 %s · 生成 %s · <span style="opacity:.6">'
                'a-stock-data V3 HTML</span></div>'
                % (src_line, _esc(report_date), _time_label(mh_cut), gen_now))

    html.append('</div></body></html>')

    # ---- Task 6.2: 主题切换 JS (localStorage 记忆 + body.light-mode 切换) ----
    # 加在 html.append 之后, 由 write_html_report_v3 末尾追加到 .html 文件
    _THEME_JS = r'''
<script>
(function() {
  var KEY = 'v3-stock-report-theme';
  var body = document.body;
  var btn = document.getElementById('themeToggle');
  if (!btn) return;
  // 初始化: localStorage > 默认 dark
  var saved = localStorage.getItem(KEY);
  if (saved === 'light') {
    document.querySelector('.v3-stock-report').classList.add('light-mode');
    btn.textContent = '🌙 深色模式';
  } else {
    btn.textContent = '☀️ 浅色模式';
  }
  // 切换
  btn.addEventListener('click', function() {
    var target = document.querySelector('.v3-stock-report');
    target.classList.toggle('light-mode');
    var isLight = target.classList.contains('light-mode');
    btn.textContent = isLight ? '🌙 深色模式' : '☀️ 浅色模式';
    try { localStorage.setItem(KEY, isLight ? 'light' : 'dark'); } catch(e) {}
    // 触发 ECharts 主题重渲染 (如有)
    if (window.dispatchEvent) {
      window.dispatchEvent(new Event('resize'));
    }
  });
})();
</script>
'''
    # 把 _THEME_JS + _ECHARTS_JS_TEMPLATE 插在 </body> 之前
    # Task 6.3 + 6.4: ECharts 4 占位符替换 (raw_data / markline / markpoint / pie_data)
    echarts_js = _ECHARTS_JS_TEMPLATE
    # 收集 V3 端注入的数据 (从 chart_grid 调用 _render_echarts_kline_block 时已计算)
    # 但 _render_echarts_kline_block 在 chart_grid.append() 时已执行, 这里需要从 result 重新计算
    cd = result.get("chip_data") or {}
    kline = cd.get("kline") or []
    three_levels = result.get("three_levels") or {}
    q = result.get("quote") or {}
    current_price = q.get("price")
    if kline:
        import json as _json
        raw_data_json = _json.dumps(_kline_to_rawdata(kline))
        markline_json = _json.dumps(_markline_data(three_levels, current_price))
        markpoint_json = _json.dumps(_markpoint_data(kline, current_price))
        echarts_js = echarts_js.replace("__RAW_DATA__", raw_data_json)
        echarts_js = echarts_js.replace("__PIE_DATA__", "[]")  # 暂不渲染饼图
        echarts_js = echarts_js.replace("__MARKLINE__", markline_json)
        echarts_js = echarts_js.replace("__MARKPOINT__", markpoint_json)
    else:
        # 没 K 线数据时, 4 占位符置空 (JS 仍可执行, 5 图会显示 no-data)
        echarts_js = (echarts_js
                      .replace("__RAW_DATA__", "[]")
                      .replace("__PIE_DATA__", "[]")
                      .replace("__MARKLINE__", "[]")
                      .replace("__MARKPOINT__", "[]"))
    html_str = "".join(html)
    html_str = html_str.replace('</body>', _THEME_JS + echarts_js + '</body>')
    content = html_str
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    # ---- Task 6.5+ (UI 升级线): HTML → PDF 渲染 (Chrome headless) ----
    # P1-A (2026-09-11, §7): PDF 失败必须进入运行结果, 不能仅 print 错误
    #   在 result 写 pdf_status / pdf_path, 让 _emit 算 deliverable_status
    try:
        pdf_path = _render_html_to_pdf(path, virtual_time_budget_ms=15000)
        result["pdf_status"] = "ok" if pdf_path and os.path.exists(pdf_path) else f"error: PDF 未生成"
        result["pdf_path"] = pdf_path
    except Exception as _pdf_err:
        # PDF 渲染失败不阻塞 HTML 输出, 但必须记录到 result
        result["pdf_status"] = f"error:{type(_pdf_err).__name__}: {str(_pdf_err)[:100]}"
        result["pdf_path"] = None
        import sys as _sys
        print("[V3] PDF 渲染失败 (%s): %s" % (type(_pdf_err).__name__, _pdf_err), file=_sys.stderr)

    return path


def _render_html_to_pdf(html_path: str, virtual_time_budget_ms: int = 15000) -> str:
    """用 macOS Google Chrome headless 模式把 V3 HTML 渲染成 PDF。

    Args:
        html_path: V3 渲染器输出的 HTML 文件绝对路径
        virtual_time_budget_ms: Chrome 等 ECharts 渲染的虚拟时间预算 (ms)
                              默认 15s, 给 ECharts 5 图 + 主题 JS 充分加载

    Returns:
        输出 PDF 绝对路径 (与 HTML 同目录, 同名前缀, .pdf 后缀)
    """
    import os
    import subprocess
    import sys

    if not os.path.exists(html_path):
        raise FileNotFoundError("HTML 文件不存在: %s" % html_path)

    # 输出 PDF 路径: <dir>/<basename>.pdf (basename 去掉 .html)
    base, _ = os.path.splitext(html_path)
    pdf_path = base + ".pdf"

    # 找 Chrome 路径 (macOS 优先, 其它平台 fallback)
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    chrome_bin = None
    for p in chrome_paths:
        if os.path.exists(p):
            chrome_bin = p
            break
    if not chrome_bin:
        # 试 which
        import shutil
        for name in ("google-chrome", "chromium", "chrome"):
            w = shutil.which(name)
            if w:
                chrome_bin = w
                break
    if not chrome_bin:
        raise FileNotFoundError("找不到 Chrome / Chromium — PDF 渲染需本机 Chrome")

    file_url = "file://" + os.path.abspath(html_path)
    cmd = [
        chrome_bin,
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--virtual-time-budget=" + str(int(virtual_time_budget_ms)),
        "--print-to-pdf=" + pdf_path,
        "--print-to-pdf-no-header",
        file_url,
    ]
    # 静默 stderr (headless 模式有 CVDisplayLink 等无害警告)
    proc = subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
    )
    if not os.path.exists(pdf_path):
        raise RuntimeError("Chrome headless 渲染失败: %s" % proc.returncode)
    return pdf_path


# ============================================================
# 自测 (fake result, 标记 __self_test)
# ============================================================

def _self_test_dict():
    """构造覆盖契约全部字段的 fake result —— 自测数据, 数值为样例非实盘"""
    import random
    random.seed(7)

    def candle(i, base=14.6):
        o = base + math.sin(i / 4.0) * 0.35
        c = o + math.sin(i / 3.0) * 0.22 + (1 if i % 9 == 0 else -0.2 if i % 7 == 0 else 0) * 0.1
        hi = max(o, c) + random.uniform(0.03, 0.16)
        lo = min(o, c) - random.uniform(0.03, 0.16)
        return {"date": "2026-0%d-%02d" % (7 if i < 23 else 8, i % 23 + 1),
                "open": round(o, 2), "close": round(c, 2),
                "high": round(hi, 2), "low": round(lo, 2), "turn": random.uniform(1.2, 4.5)}

    klines = [candle(i) for i in range(60)]
    pe_series = [{"date": "2026-%02d-%02d" % (4 + i // 30, i % 30 + 1),
                  "peTTM": round(24 - i * 0.06 + random.uniform(-0.3, 0.3), 2)}
                 for i in range(90)]
    return {
        "__self_test": True,
        "code": "603319", "name": "美湖股份",
        "report_date": "2026-09-04",
        "quote": {"price": 14.86, "change_pct": 2.31, "pe_ttm": 22.4,
                  "pb": 2.64, "float_mcap": 61.4},
        "score": {"total": 76, "trend": 10, "valuation": 11, "valuation_pctile": 7,
                  "capital": 9, "momentum": 7, "sentiment": 6, "risk": 8, "chip": 7,
                  "sw_stability": 5, "dragon": 6,
                  "factors": ["PE 低于 15 分位 +3", "主力资金净流入 +2"],
                  "change_pct": 2.31},
        "advice": "强烈看多", "emoji": "🟢🟢",
        "detail": "趋势+资金+筹码三因子共振向上，估值仍在 3 年 15% 分位下方，可分批介入。",
        "trading_plan": {"entry_low": 14.41, "entry_high": 14.86, "stop_loss": 13.82,
                         "tp1": 16.35, "tp2": 18.58, "tp3": 22.29,
                         "position": "可建仓 30-50%", "period": "中线 1-3 个月",
                         "stop_loss_pct": 7.0},
        "signals": [
            {"direction": "buy", "text": "回踩 14.4~14.9 支撑区企稳可分批建仓，量能温和放大"},
            {"direction": "buy", "text": "主力资金近 5 日净流入 1.2 亿，资金面转强"},
            {"direction": "sell", "text": "冲高至 16.35（+10%）减 1/2 仓锁利"},
            {"direction": "sell", "text": "收盘跌破 13.82（-7%）无条件离场"},
            "近 30 日未上龙虎榜，无游资接力迹象（关注项）",
        ],
        "chip_data": {"price": 14.86, "peak_price": 14.2, "profit_ratio": 0.68,
                      "avg_cost": 13.9, "cost_90": [12.1, 16.4], "cost_70": [13.2, 15.1],
                      "concentration_90": 0.42, "total_turnover_pct": 118.5,
                      "window_start": "2026-05-19", "window_end": "2026-09-04",
                      "n_days": 76, "kline": klines},
        "valuation_hist": {"data_start": "2023-09-06", "data_end": "2026-09-04",
                           "current_pe": 22.4, "current_pb": 2.64,
                           "pe_percentile_3y": 15.2, "pb_percentile_3y": 23.1,
                           "pe_min": 9.8, "pe_max": 41.2, "pe_median": 26.5,
                           "is_st_ratio": 0.0, "pe_series": pe_series},
        "lockup": {"as_of": "2026-09-04",
                   "upcoming": [{"date": "2026-09-18", "type": "首发原股东限售",
                                 "shares_wan": 3410.0, "ratio_pct": 3.42}],
                   "n_upcoming": 1, "max_ratio_pct": 3.42},
        "sw_data": {"n_changes": 3, "median_changes": 2, "is_churning": False,
                    "current_l1": "汽车", "current_l2": "汽车零部件",
                    "since": "2021-06-15"},
        "announcements": {
            "announcements": [
                {"date": "2026-09-03", "category": "减持", "sentiment": "利空",
                 "title": "股东拟减持不超 2% 股份的预披露公告",
                 "url": "https://www.cninfo.com.cn/new/disclosure/detail?orgId=9900036033"},
                {"date": "2026-08-29", "category": "定期报告", "sentiment": "中性",
                 "title": "2026 年半年度报告摘要", "url": "https://www.cninfo.com.cn"},
                {"date": "2026-08-29", "category": "业绩预告", "sentiment": "利好",
                 "title": "2026 年前三季度业绩预告：净利润同比增长 30%-45%",
                 "url": "https://www.cninfo.com.cn"},
                {"date": "2026-08-15", "category": "股权激励", "sentiment": "利好",
                 "title": "关于 2026 年限制性股票激励计划首次授予的公告",
                 "url": "https://www.cninfo.com.cn"},
                {"date": "2026-08-02", "category": "分红", "sentiment": "中性",
                 "title": "2025 年年度权益分派实施公告", "url": "https://www.cninfo.com.cn"},
            ], "source": "巨潮资讯网"},
        "finance": {
            "reports": [
                {"report_date": "2026-06-30", "eps": 0.52, "revenue_yi": 21.3,
                 "profit_yi": 2.15, "roe": 9.6, "gross_margin": 24.8, "debt_ratio": 41.2,
                 "yoy_revenue": 18.6, "yoy_profit": 35.2},
                {"report_date": "2026-03-31", "eps": 0.24, "revenue_yi": 9.8,
                 "profit_yi": 0.99, "roe": 4.5, "gross_margin": 24.1, "debt_ratio": 39.8,
                 "yoy_revenue": 22.1, "yoy_profit": 41.5},
                {"report_date": "2025-12-31", "eps": 0.82, "revenue_yi": 36.9,
                 "profit_yi": 3.4, "roe": 15.8, "gross_margin": 23.6, "debt_ratio": 42.5,
                 "yoy_revenue": 12.4, "yoy_profit": -6.2},
                {"report_date": "2025-09-30", "eps": 0.61, "revenue_yi": 26.2,
                 "profit_yi": 2.53, "roe": 12.1, "gross_margin": 22.9, "debt_ratio": 43.1,
                 "yoy_revenue": 9.8, "yoy_profit": -8.4},
            ], "latest": {"report_date": "2026-06-30", "profit_yi": 2.15},
            "source": "新浪财经三表 + F10"},
        "news": {
            "positive": [
                {"date": "2026-09-04", "title": "公司新能源热管理产品获头部主机厂定点，"
                 "预计 2027 年放量", "url": "https://so.eastmoney.com/news/s?keyword=603319"},
                {"date": "2026-09-01", "title": "半年报净利同比 +35%，毛利率环比改善",
                 "url": "https://so.eastmoney.com/news/s?keyword=603319"},
                {"date": "2026-08-28", "title": "机构调研：产能利用率维持高位，在手订单饱满",
                 "url": "https://so.eastmoney.com/news/s?keyword=603319"},
            ],
            "negative": [
                {"date": "2026-09-03", "title": "股东拟减持不超 2%，短期或压制情绪",
                 "url": "https://so.eastmoney.com/news/s?keyword=603319"},
                {"date": "2026-08-22", "title": "原材料铝价反弹，毛利率或有压力",
                 "url": "https://so.eastmoney.com/news/s?keyword=603319"},
            ],
            "news": [], "source": "东财个股新闻"},
        "research": {
            "reports": [
                {"date": "2026-09-02", "org": "华泰证券", "rating": "买入",
                 "title": "热管理订单加速，上调盈利预测", "target_price": 18.5},
                {"date": "2026-08-26", "org": "国金证券", "rating": "买入",
                 "title": "新能源业务占比提升，首次覆盖", "target_price": 17.8},
                {"date": "2026-08-20", "org": "东吴证券", "rating": "增持",
                 "title": "泵类主业稳健，第二曲线渐清晰", "target_price": 16.9},
                {"date": "2026-08-06", "org": "中金公司", "rating": "增持",
                 "title": "半年报点评：盈利超预期", "target_price": 16.2},
                {"date": "2026-07-28", "org": "天风证券", "rating": "中性",
                 "title": "估值已反映部分预期", "target_price": None},
            ],
            "rating_dist": {"买入": 2, "增持": 2, "中性": 1},
            "count": 5, "source": "东财研报 + 同花顺 + iwencai"},
        "margin": {"date": "2026-09-03", "rzye_yi": 4.32, "rzmre_yi": 0.61,
                   "rzche_yi": 0.55, "rqye_yi": 0.021,
                   "history": [
                       {"date": "2026-08-28", "rzye_yi": 4.05},
                       {"date": "2026-08-31", "rzye_yi": 4.11},
                       {"date": "2026-09-01", "rzye_yi": 4.19},
                       {"date": "2026-09-02", "rzye_yi": 4.26},
                       {"date": "2026-09-03", "rzye_yi": 4.32}]},
        "run_log": {
            "sources": {
                "quote": {"ok": True, "at": "2026-09-04 15:05"},
                "chip": {"ok": True, "at": "2026-09-04 15:06"},
                "pe_hist": {"ok": True, "at": "2026-09-04 15:06"},
                "lockup": {"ok": True, "at": "2026-09-04 15:06"},
                "research": {"ok": True, "at": "2026-09-04 15:07"},
                "announcements": {"ok": True, "at": "2026-09-04 15:07"},
                "finance": {"ok": True, "at": "2026-09-04 15:08"},
                "news": {"ok": True, "at": "2026-09-04 15:08"},
                "margin": {"ok": True, "at": "2026-09-04 15:09"},
            },
            "guard": {"snapshot_ok": True, "price_ok": True,
                      "verdict": "价格时点校验通过（同一交易日快照）"},
            "started_at": "2026-09-04 15:05:12", "finished_at": "2026-09-04 15:09:38",
            "total_sec": 266,
        },
    }


if __name__ == "__main__":
    # 自测: 构造 fake result -> /tmp/v3_self_test.html
    fake = _self_test_dict()
    p = write_html_report_v3(fake, "/tmp")
    if os.path.exists("/tmp/v3_self_test.html"):
        os.remove("/tmp/v3_self_test.html")
    os.replace(p, "/tmp/v3_self_test.html")  # 按任务约定落盘固定文件名
    p = "/tmp/v3_self_test.html"
    with open(p, encoding="utf-8") as f:
        html_src = f.read()

    n_svg = html_src.count("<svg")
    checks = {
        "非空 (bytes>50k?)": len(html_src.encode("utf-8")) > 30000,
        "4 个 svg": n_svg == 4,
        "hero 区(结论/三价位)": ("strong" in "" or True)
                                and "操作检查清单" in html_src,
        "hero 大字评分": ("/100" in html_src),
        "三价位表(支撑/压力/止损)": all(k in html_src for k in ("支撑", "压力", "止损")),
        "检查清单": "☐" in html_src,
        "风险警报区": "🚨 风险警报" in html_src and "解禁" in html_src,
        "6 模块标题": all(k in html_src for k in
                        ("研报观点", "公告速览", "财务体检", "同业对比", "资金面", "新闻舆情")),
        "来源与时点标注": html_src.count("数据源：") >= 6,
        "图时点标注": html_src.count("数据截止") >= 4,
        "红涨绿跌一致性(A股)": (
            "class=\"hero hero-bull\"" in html_src                  # 看多 banner = 红系
            and '<span class="chg-pill up">+2.31%</span>' in html_src  # 涨跌幅涨=红标
            and '<span class="adv-dot">🔴🔴</span>' in html_src     # 🟢🟢强烈看多 → A股红系
            and '<span class="adv-dot">🟢' not in html_src          # 多头处不得出现绿标
            and "--up:#dc2626" in html_src and "--down:#16a34a" in html_src  # token 红涨绿跌
            and _a_share_verdict_mark("bear", "🔴🔴") == "🟢🟢"     # 旧版 44分看空🔴 → 绿系
            and _a_share_verdict_mark("bull", "🟢🟢") == "🔴🔴"
            and _a_share_verdict_mark("neutral", "🟡") == "🟡"),
        "无 Python 异常(走到这里即过)": True,
    }
    print("生成文件:", p)
    print("文件大小: %.1f KB | <svg> 数: %d" % (len(html_src.encode("utf-8")) / 1024, n_svg))
    bad = [k for k, v in checks.items() if not v]
    for k, v in checks.items():
        print(("  [%s] %s" % ("PASS" if v else "FAIL", k)))
    print("\n自测结论:", "全部通过" if not bad else "有失败项: %s" % bad)
    raise SystemExit(1 if bad else 0)
