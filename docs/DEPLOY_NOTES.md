# A 股数据 skill — 本地部署说明

来源: github.com/simonlin1212/a-stock-data (同步到 **V3.7.2**)

---

## 📅 2026-09-03 深夜更新（V2.2：HTML 报告 + 4 张 SVG 图）

V2.2 解决了"Markdown 报告看不懂"的问题——把数据表翻译成人话 + **生成单文件 HTML 报告**，微信可直接发，手机离线可看。

### 新增文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `html_report.py` | 540 | HTML 报告生成器（4 个 SVG 图 + 完整 HTML 模板）|
| `quant_analyzer_v2.py` | 1530 → 1560 | 加 `from html_report import write_html_report` + 调用 |

### HTML 报告设计原则

1. **顶部 = 一句话结论**（评分 + 颜色 + emoji + 价/涨跌）
2. **第二屏 = 一分钟结论**（操作口诀、进场价、止损位、三档止盈）
3. **第三屏 = 6 个 KPI 卡片**（PE / PB / 前向PE / PE分位 / 获利盘 / 换手量比）
4. **第四屏 = 👍/👎 信号清单**（彩色 chip 形式）
5. **第五屏 = 4 个图表并排**（手机端上下排）：
   - 📈 近 60 日 K 线（SVG 蜡烛图，红涨绿跌）
   - 🎰 筹码分布（SVG 柱状图，红套牢/绿获利，筹码峰标蓝）
   - 📊 近 6 个月 PE 走势（SVG 折线，3 年分位标橙）
   - 🔬 10 因子雷达（SVG 雷达图，10 维度）
6. **第六屏 = 三种情景应对**（涨 / 横 / 跌）
7. **底部 = 折叠详情表**（实时行情 / 一致预期 / 估值历史 / 筹码明细）

### 关键技术决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 图表库 | **纯 SVG 手写** | 不依赖 CDN/JS，手机离线可看 |
| CSS | **内嵌** | 单文件 29 KB，微信可直接发 |
| 字体 | -apple-system / PingFang SC | iOS/Mac 原生无需下载 |
| 颜色 | 蓝(#2962ff) + 红涨绿跌(A股惯例) | 与同花顺/东财色系一致 |
| 评分→颜色 | 65+ 绿 / 55-65 橙 / 45-55 红橙 / <45 红 | 一眼定级 |

### 验证（001696 宗申动力）

- 文件大小：**29.1 KB**（单文件 < 50KB 目标达成）
- 18 项内容检查全过（header / 结论 / KPI / 信号 / 4 张 SVG / 三情景 / 响应式）
- 关键数据全部嵌入：止损 14.94 / 第一止盈 18.74 / 筹码峰 15.40 / 获利盘 81.89% / PE 33.7 / 分位 50.5%
- viewport 移动端适配 + safe-area-inset 刘海屏安全区

### 用法（不变）

```bash
./run_in_venv.sh quant_analyzer_v2.py 001696 宗申动力
```

输出两个文件：
- `~/Documents/a-stock-reports/YYYY-MM-DD/CODE-NAME-HHMM.md`（人话 Markdown）
- `~/Documents/a-stock-reports/YYYY-MM-DD/CODE-NAME-HHMM.html`（带图表 HTML）

HTML 直接双击打开 / 拖到微信 / 发邮件附件都行。

---

## 📅 2026-09-03 晚更新记录（V2 → V2.1：筹码分布 + 申万满血）

V2 把 10 因子里的"筹码因子 (8分)"和"申万稳定因子 (6分)"从占位升级为真实计算：

| 端点 | 来源 | V2.1 实测 |
|------|------|-----------|
| 筹码分布 CYQ | baostock 前复权 K 线 + §6.5 三角分布 + 换手衰减 | ✅ 跑通 001696：获利盘 81.9% / 均成本 16.38 / 90% 集中度 17.17% / 筹码峰 15.40 |
| 申万行业变迁 | swsresearch.com 官方 XLS（12,893 行，38 个一级行业） | ⚠️ SSL 证书问题（沙盒 certifi 过旧）→ 加了一行修复提示 |

**V2.1 vs V2 打分影响（同一只票）：**

| 票 | V2 (mock) 筹码分 | V2.1 (满血) 筹码分 | V2 总分 | V2.1 总分 |
|---|---|---|---|---|
| 001696 宗申动力 | 4 | **7** | 62 | **65** |
| 000858 五粮液 | 4 | **2** | 52 | **50** |

申万因子在 V2.1 因为 SSL 都 fallback 到 mock（5 分基础），但**脚本已优雅降级**，本机升级 certifi 后即恢复：

```bash
cd ~/.hermes/skills/finance/a-stock-data
./venv/bin/python -m pip install -U certifi
```

---

## 📅 2026-09-03 更新记录（quant_analyzer 升级 V2）

### V2 关键变化（vs 旧 V1）

| 维度 | V1 (V3.2.2 era) | V2 (V3.7.2) |
|------|----------------|-------------|
| 端点数量 | 9 个 | **22 个** |
| 因子数量 | 6 个（共 100 分） | **10 个**（共 100 分）|
| 一致预期 | ❌ 无 | ✅ 同花顺直接抓 + PE消化/PEG |
| 估值分位 | ❌ 无 | ✅ baostock 3 年历史 PE/PB 分位 |
| 输出格式 | 控制台纯文本 | **Markdown 报告** (~/Documents/a-stock-reports/YYYY-MM-DD/) |
| CLI 入口 | 仅批量 | `python quant_analyzer_v2.py 001696 [name]` 单票 / `python script.py` 批量 |

### V2 新增的 10 因子

1. 趋势 12分 — 涨跌 + 低开高走
2. 估值 15分 — PE-TTM/PB + **PE消化年数 + PEG**
3. **估值分位 8分**（V3.7 新）— baostock 历史 PE/PB 分位
4. 资金 15分 — 当日分钟级主力/大单
5. 动量 8分 — 换手/量比/振幅
6. 情绪 8分 — 板块热度 + 北向
7. 风险 10分 — 市值/PE/解禁
8. **筹码 8分**（V3.7 新，mock 中）— 留接口待接 K 线
9. **申万稳定 6分**（V3.7 新，mock 中）— 留接口待接 sw_industry_history
10. 龙虎榜 10分 — 近30日上榜次数 + 净买入

### V2 测试结果（2026-09-03 沙盒）

- **001696 宗申动力**: 综合 62 分 🟡 中性偏多 — PEG 0.74 / PE 分位 50.5%
- **600519 贵州茅台**: 综合 59 分 🟡 中性偏多 — 48 家覆盖 / PE 分位 17.8%(低位)
- **002463 沪电股份**: 综合 53 分 🟡 中性偏空 — PE 分位 84.6%(高位)
- **000858 五粮液**: 综合 52 分 🟡 中性偏空 — PE 分位 82%
- **688017 绿的谐波**: 综合 44 分 🔴 看空 — PE 377 / PEG 5.93 / PB 分位 87.1%

### V2 沙盒测试通过的端点

✅ 腾讯实时 (10/10) | ✅ 同花顺一致预期 (10/10) | ✅ baostock 估值历史 (5/5)
✅ 同花顺北向 | ✅ 同花顺强势股题材 | ⚠️ 东财系列（SSL 握手，沙盒问题，本机可通）

---

## 已就位的所有文件

| 文件 | 大小 | 说明 |
|------|------|------|
| `SKILL.md` | 208 KB | V3.7.2 技能定义（11 层 / 54 端点 / 19 数据源）|
| `README.md` | 26 KB | 项目主页 |
| `CHANGELOG.md` | 57 KB | 更新日志 |
| `LICENSE` | 11 KB | Apache 2.0 |
| `quant_analyzer.py` | 20 KB | **V1**（保留，不再更新）|
| **`quant_analyzer_v2.py`** | 45 KB | **V2**（当前推荐使用）|
| `env.example` | 440 B | iwencai Key + ASTOCK_DEBUG 开关 |
| `run_in_venv.sh` | 515 B | venv 启动小工具 |
| `venv/` | — | Python 3.12 虚拟环境 |

## V2 使用方式

### 单票分析（推荐）
```bash
cd ~/.hermes/skills/finance/a-stock-data
./run_in_venv.sh quant_analyzer_v2.py 001696 宗申动力
# 或： ./run_in_venv.sh quant_analyzer_v2.py 001696
```

输出：
- 控制台 10 因子打分 + 建议
- Markdown 报告写到 `~/Documents/a-stock-reports/YYYY-MM-DD/CODE-NAME-HHMM.md`

### 批量分析
```bash
./run_in_venv.sh quant_analyzer_v2.py
# 默认分析: 688017 绿的谐波 / 001696 宗申动力 / 600519 茅台 / 000858 五粮液 / 002463 沪电股份
```

修改批量标的：编辑脚本第 1100+ 行的 `analyze_batch([...])` 调用。

## 依赖（venv 内全部就位）

```
mootdx 0.11.7  requests 2.34.2  pandas 3.0.3  numpy 2.4.6
stockstats  baostock  lxml  xlrd  openpyxl
```

## iwencai Key 配置（可选）

```bash
cp env.example .env
# 编辑 .env，填入 IWENCAI_API_KEY=xxxx
# 不填也能用 V2 全部功能，只是不能跑 iwencai 语义搜索
```

## V2 与 V1 共存策略

- V1 `quant_analyzer.py` 保留不动（兼容旧调用）
- 新需求一律走 V2 `quant_analyzer_v2.py`
- 未来 V1 会加个 deprecation 警告，但暂时不动

## V3.7 已知限制（沙盒验证）

| 端点 | 限制 |
|------|------|
| baostock | 不支持北交所（4/8/92/920 号段），不支持 ETF |
| 东财 push2 | 部分大陆住宅 IP 被风控（HTTP 000），换网络/手机热点即可 |
| 百度 PAE | 2026 年起需 PC UA + 自定义 stockid，沙盒模拟不到位 |
| 财联社快讯 | 旧端点 404，已下线（用东财全球资讯替代）|

## 文件位置

```
~/.hermes/skills/finance/a-stock-data/
├── SKILL.md                       # V3.7.2 单文件技能定义
├── README.md                      # 项目主页
├── CHANGELOG.md                   # 完整更新日志
├── LICENSE                        # Apache 2.0
├── env.example                    # 环境变量模板
├── run_in_venv.sh                 # venv 启动器
├── quant_analyzer.py              # V1（保留）
├── quant_analyzer_v2.py           # V2（推荐）
├── DEPLOY_NOTES.md                # 本文件
└── venv/                          # Python 3.12 + 全部依赖

~/Documents/a-stock-reports/       # V2 报告输出目录（按日期分子目录）
└── YYYY-MM-DD/
    └── CODE-NAME-HHMM.md
```