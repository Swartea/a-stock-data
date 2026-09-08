#!/usr/bin/env python3
"""一次性脚本：为 SKILL.md 54 端点章节加 emoji 标注（Task 3.3）。

数据来源：audit §4.2 完整 54 端点分类表 + brief label→emoji 字典交叉验证。

⚠️ 为什么不直接照 brief Step 1 的脚本？
brief 里的 `re.compile(rf"^(### .*?)\b{re.escape(label)}\b", re.MULTILINE)`
要求 label（如 `tencent_quote`）直接出现在 `### ` 标题里，但实际标题是
中文（`### 1.2 腾讯财经 API — PE/PB/市值...`），函数名不会出现在标题里。
正则字面跑下来只有 1 处匹配（且误中 FAQ 章节）。本脚本改用段号（`### 1.2`）
作为锚点——emoji 字典完全保留 brief 的 54 label→emoji 映射作为单一真源。

输出：1 个 `### Ticker 格式归一化` 标题 + 45 个 `### x.y` 标题 + 3 个备胎函数注释
= 49 个插入点（54 个端点 - 5 个子端点与主端点共享章节）。
"""
import re

WORKDIR = "/Users/swarteachou/Desktop/大A数据"
SKILL = f"{WORKDIR}/SKILL.md"

# === 单一真源：brief label→emoji 字典（54 项）===
# 保留为审计/未来扩展参考；实际操作通过下面 SECTION_EMOJI 段号映射。
LABEL_EMOJI = {
    "norm_ticker": "🔥",
    "tdx_client": "🔥",
    "tencent_quote": "🔥⚠️",
    "baidu_kline_with_ma": "🔥",
    "sina_adjust_factor": "🆕🔥",
    "eastmoney_reports": "⚠️🔴",
    "eastmoney_industry_reports": "⚠️",
    "ths_eps_forecast": "🔥",
    "iwencai_search": "⚠️",
    "ths_hot_reason": "🔥",
    "hsgt_realtime": "🔥",
    "eastmoney_concept_blocks": "⚠️",
    "eastmoney_fund_flow_minute": "⚠️",
    "dragon_tiger_board": "⚠️",
    "lockup_expiry": "⚠️",
    "industry_comparison": "⚠️",
    "board_fund_flow": "⚠️",
    "daily_dragon_tiger": "⚠️",
    "margin_trading": "⚠️",
    "block_trade": "⚠️",
    "holder_num_change": "⚠️",
    "dividend_history": "⚠️",
    "stock_fund_flow_120d": "⚠️",
    "chip_distribution": "🆕🔥",
    "eastmoney_stock_news": "⚠️",
    "cls_telegraph": "🔥",
    "eastmoney_global_news": "⚠️",
    "client.finance": "🔥",
    "client.F10": "🔥",
    "eastmoney_stock_info": "⚠️",
    "sina_financial_report": "🔥",
    "baostock_valuation_history": "🆕⚠️",
    "baostock_stock_basic": "🆕🔥",
    "sw_industry_history": "🆕⚠️",
    "cninfo_announcements": "⚠️",
    "client.F10_最新提示": "🔥",
    "em_zt_pool": "⚠️",
    "ths_limit_up_pool": "🔥",
    "limit_up_sentiment": "⚠️",
    "em_stock_monitor": "⚠️",
    "em_price_anomaly": "⚠️🔴",
    "sina_option_codes": "🔥",
    "cninfo_irm": "🔥",
    "ths_hot_list": "⚠️",
    "pboc_social_financing": "🆕⚠️",
    "nbs_pmi": "🆕⚠️",
    "dragon_tiger_backup": "💎⚠️",
    "fund_flow_backup": "💎🔥",
    "announcements_backup": "💎⚠️",
}
# 注：brief 字典原样是 49 项（少数子端点如 em_zb_pool/sina_tquote/em_hot_rank 未单列），
# 54 端点统计来自 audit §4.2（51 主 + 3 备胎）。本脚本 SECTION_EMOJI 实际覆盖
# 46 个主端点标题（45 个 `### x.y` + 1 个 `### Ticker 格式归一化`） + 3 个备胎 = 49 处。
assert len(LABEL_EMOJI) == 49, f"Brief dict has 49 labels, got {len(LABEL_EMOJI)}"

# === 实际操作：段号→emoji 映射（来自 audit §4.2）===
# 格式：(section_anchor, emoji, 描述)
#   section_anchor 要么是 "### 1.2 "（带尾空格）匹配 `### 1.2 腾讯财经 API...`
#   要么是 "### Ticker 格式归一化" 匹配前置章节
SECTION_EMOJI = [
    ("### Ticker 格式归一化", "🔥", "前置 norm_ticker"),
    ("### 1.1 ", "🔥", "tdx_client/bars"),
    ("### 1.2 ", "🔥⚠️", "tencent_quote（僵尸码）"),
    ("### 1.3 ", "🔥", "baidu_kline_with_ma"),
    ("### 1.4 ", "🆕🔥", "sina_adjust_factor"),
    ("### 2.1 ", "⚠️🔴", "eastmoney_reports（静默空）"),
    ("### 2.2 ", "🔥", "ths_eps_forecast"),
    ("### 2.3 ", "⚠️", "iwencai_search"),
    ("### 3.1 ", "🔥", "ths_hot_reason"),
    ("### 3.2 ", "🔥", "hsgt_realtime"),
    ("### 3.3 ", "⚠️", "eastmoney_concept_blocks"),
    ("### 3.4 ", "⚠️", "eastmoney_fund_flow_minute"),
    ("### 3.5 ", "⚠️", "dragon_tiger_board"),
    ("### 3.6 ", "⚠️", "lockup_expiry"),
    ("### 3.7 ", "⚠️", "industry_comparison"),
    ("### 3.8 ", "⚠️", "board_fund_flow"),
    ("### 3.9 ", "⚠️", "daily_dragon_tiger"),
    ("### 4.1 ", "⚠️", "margin_trading"),
    ("### 4.2 ", "⚠️", "block_trade"),
    ("### 4.3 ", "⚠️", "holder_num_change"),
    ("### 4.4 ", "⚠️", "dividend_history"),
    ("### 4.5 ", "⚠️", "stock_fund_flow_120d"),
    ("### 4.6 ", "🆕🔥", "chip_distribution"),
    ("### 5.1 ", "⚠️", "eastmoney_stock_news"),
    ("### 5.2 ", "🔥", "cls_telegraph"),
    ("### 5.3 ", "⚠️", "eastmoney_global_news"),
    ("### 6.1 ", "🔥", "client.finance"),
    ("### 6.2 ", "🔥", "client.F10"),
    ("### 6.3 ", "⚠️", "eastmoney_stock_info"),
    ("### 6.4 ", "🔥", "sina_financial_report"),
    ("### 6.5 ", "🆕⚠️", "baostock_valuation_history"),
    ("### 6.6 ", "🆕🔥", "baostock_stock_basic"),
    ("### 6.7 ", "🆕⚠️", "sw_industry_history"),
    ("### 7.1 ", "⚠️", "cninfo_announcements"),
    ("### 7.2 ", "🔥", "client.F10_最新提示"),
    ("### 8.1 ", "⚠️", "em_zt_pool"),
    ("### 8.2 ", "🔥", "ths_limit_up_pool"),
    ("### 8.3 ", "⚠️", "limit_up_sentiment"),
    ("### 8.4 ", "⚠️", "em_stock_monitor"),
    ("### 8.5 ", "⚠️🔴", "em_price_anomaly"),
    ("### 9.1 ", "🔥", "sina_option_codes"),
    ("### 10.1 ", "🔥", "cninfo_irm"),
    ("### 10.2 ", "⚠️", "ths_hot_list"),
    ("### 11.1 ", "🆕⚠️", "pboc_social_financing"),
    ("### 11.2 ", "🆕⚠️", "nbs_pmi"),
]

# === 备胎函数（无独立 `### ` 标题，在 `def ` 上方插入注释）===
# 备胎位于 `## 备用源速查` 章节内的代码块中
BACKUP_FUNCS = [
    ("def dragon_tiger_backup(", "💎⚠️", "龙虎榜官方备胎"),
    ("def fund_flow_backup(", "💎🔥", "资金流新浪备胎"),
    ("def announcements_backup(", "💎⚠️", "公告官方备胎"),
]


def main():
    with open(SKILL, "r", encoding="utf-8") as f:
        content = f.read()

    changes = 0
    misses = []

    # 1) 在 `### 段号 ` 标题末尾插入 emoji
    for anchor, emoji, desc in SECTION_EMOJI:
        # 用 count=1 防止多匹配；检查是否已经加过 emoji（幂等）
        # 匹配 `### 1.2 腾讯财经 API` 但不匹配 `### 1.2 🔥 腾讯财经 API`
        # 锚点必须以 "### " 开头（避免误中正文中的同名字符串）
        if anchor.startswith("### "):
            # 已经处理过：emoji 紧跟在 `### 1.2 ` 之后
            already_pat = re.compile(rf"^{re.escape(anchor)}{re.escape(emoji)} ", re.MULTILINE)
            if already_pat.search(content):
                continue
            pat = re.compile(rf"^{re.escape(anchor)}", re.MULTILINE)
            new_content, n = pat.subn(f"{anchor}{emoji} ", content, count=1)
            if n == 0:
                misses.append(f"未找到标题：{anchor!r}（{desc}）")
            else:
                content = new_content
                changes += 1
        else:
            # 如 "### Ticker 格式归一化" —— 锚点恰好是完整标题
            already_pat = re.compile(rf"^{re.escape(anchor)} {re.escape(emoji)}", re.MULTILINE)
            if already_pat.search(content):
                continue
            new_anchor = f"{anchor} {emoji}"
            pat = re.compile(rf"^{re.escape(anchor)}$", re.MULTILINE)
            new_content, n = pat.subn(new_anchor, content, count=1)
            if n == 0:
                misses.append(f"未找到标题：{anchor!r}（{desc}）")
            else:
                content = new_content
                changes += 1

    # 2) 在备胎 `def ` 上方插入 emoji 注释（保留原缩进/空行）
    # 备胎函数都在代码块内，前面是 ` ```python\n ` 开头的代码块
    # 备胎 `def ` 上面 1 行是空行或 ` ```python ` —— 在 `def ` 之前插入 `# {emoji} 备胎端点`
    for def_sig, emoji, desc in BACKUP_FUNCS:
        # 已经处理过：emoji 注释行在 `def ` 上方
        if f"# {emoji} 备胎端点（{desc}）" in content and def_sig in content:
            # 简单幂等：检查
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if def_sig in line:
                    # 上一行是否已是 emoji 注释
                    if i > 0 and f"# {emoji} 备胎端点" in lines[i - 1]:
                        break
            else:
                # 没找到 def_sig 或上方已有注释
                continue
            continue

        pat = re.compile(
            rf"^(?P<indent>[ \t]*)(?P<defline>{re.escape(def_sig)})",
            re.MULTILINE,
        )
        m = pat.search(content)
        if not m:
            misses.append(f"未找到 def 行：{def_sig!r}（{desc}）")
            continue
        indent = m.group("indent")
        comment_line = f"{indent}# {emoji} 备胎端点（{desc}）\n"
        # 在 m.start() 处插入（在 def 行前）
        content = content[: m.start()] + comment_line + content[m.start():]
        changes += 1

    with open(SKILL, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✅ 修改了 {changes} 处")
    print(f"   - 端点章节标题：{len(SECTION_EMOJI)} 个目标")
    print(f"   - 备胎函数注释：{len(BACKUP_FUNCS)} 个目标")
    print(f"   - 漏改：{len(misses)}")
    for miss in misses:
        print(f"   ⚠️ {miss}")


if __name__ == "__main__":
    main()
