# Swartee Market Research V1 RC 验收记录

日期：2026-10-15（Asia/Shanghai）

## Git 基线与卫生

- `main`: `d21a41179511055b8dddb2ce17a18a266e608ecb`
- 研究收口：`b4f94b2e988214f3ca26ecdd476343290af6bd77`
- 全球市场研究：`ed83aa908b61ed7987a544cd88db902b798281be`
- 终端 UI V1：`8d5e3e121603fe1d62706d0a05cbada47af68456`
- RC：`codex/market-research-v1-rc-20261015`，由 UI V1 head 建立。
- `git merge-base --is-ancestor` 三项核验均成功：main → UI、研究收口 → 全球研究、全球研究 → UI。
- 创建 RC 时工作树干净。原工作目录的未提交进度文档及 `audit/` 文件没有拷贝、覆盖或清理。
- 未 Push、未创建 PR、未 Merge；远端 CI：**CI_NOT_VERIFIED**。

## 产品功能与真实 Provider

Registry 中登记 9 个指数，且本轮每个指数各发起一次真实日线研究请求，日期窗口为最近 30 个日历日。现有服务无重试；A 股仅在 Tencent 失败时可能走一次 BaoStock fallback。本轮 9 次均成功，未触发 fallback。

| 市场 | 指数 | 注册 | 本轮真实请求 | 结果 | 来源 / 最新日线 |
|---|---|---:|---:|---|---|
| 中国内地 | 上证指数 | 是 | 是 | `ok / available`，16 根 | Tencent / 2026-10-14 |
| 中国内地 | 深证成指 | 是 | 是 | `ok / available`，16 根 | Tencent / 2026-10-14 |
| 中国内地 | 创业板指 | 是 | 是 | `ok / available`，16 根 | Tencent / 2026-10-14 |
| 中国内地 | 沪深 300 | 是 | 是 | `ok / available`，16 根 | Tencent / 2026-10-14 |
| 中国香港 | 恒生指数 | 是 | 是 | `ok / available`，21 根 | Tencent / 2026-10-14 |
| 中国香港 | 恒生科技指数 | 是 | 是 | `ok / available`，21 根 | Tencent / 2026-10-14 |
| 美国 | S&P 500 | 是 | 是 | `ok / available`，22 根 | Tencent / 2026-10-14 |
| 美国 | Nasdaq Composite | 是 | 是 | `ok / available`，22 根 | Tencent / 2026-10-14 |
| 美国 | Dow Jones Industrial Average | 是 | 是 | `ok / available`，22 根 | Tencent / 2026-10-14 |

交易日状态均为 `unknown`，界面展示“未知（无交易日历证据）”。页面用日线收盘而非实时行情；OHLC、币种、时区、来源和数据日期均可见。单日区间实测 1 根 K 线和完整 OHLC，涨跌幅明确显示暂不可计算；无虚构补齐。

## 浏览器 UI 与交互

- RC 本地服务在 `127.0.0.1:8766` 实际运行。Chrome 1920 像素视口截图/界面检查确认 9 张市场概览卡、桌面三栏、K 线、市场信息、历史表格正常，无可见水平溢出或截断。
- 另一个浏览器表面提供 1280 像素截图：页面切为导航 + 主图两栏，信息面板转到下一行；未见水平溢出。
- 实际交互：从中国内地切到美国、切换至 Nasdaq Composite、设置单日日期范围并查询、在图表上定位 OHLC，结果与选中指数一致；加载态可见。
- 未来日期窗口 `2026-10-16–2026-10-17` 返回 0 根时，页面展示“无数据 / 不可用 / 未知”、Provider 无数据原因和空图表提示；没有沿用先前 Nasdaq 数据，也没有生成 K 线。
- 1440、768、390 精确视口无法通过本轮可用浏览器控制接口设置；这些尺寸未验收。触摸设备交互未实测。没有把之前已检入的 PNG 当成本轮交互证据。
- 旧端口 `8765` 的标签连到另一份较早 UI 服务，不作为 RC 验收证据；RC 检查使用其独立端口。
- 本轮未获得浏览器控制台日志接口，故控制台“无错误”未验证。

## Review、安全与质量

- **Codex 第二轮代码复核**：查看 Canonical Identity、Global Index Registry / Provider Symbols、Daily-K 编排、Snapshot Service、Market Availability / State、UI 渲染和请求序列保护。确认数据身份绑定、状态未知显式表达、异常日期数据拒绝路径、老指数别名兼容及 UI 过期响应序号保护；未发现 P0/P1。HTML 注入面采用转义或 `textContent`；新增 UI 用例与 HTML 转义审计测试通过。
- **Kimi 独立 Review**：本轮未提交代码到 Kimi；不宣称 Kimi Review 通过。
- 原 A 股分析公式、三价位、评分权重和报告契约没有变更。
- 新增/修改 Python 文件 Ruff 检查：通过。全仓 Ruff：46 条历史告警，集中于未改动的旧文件；不在本轮机械清零范围。
- 全仓 JS 语法：`node --check` 通过。
- 提交内容没有加入行情生成文件或凭据；之前存在的 Playwright PNG 是既有版本追踪文件。

## 测试和构建

- 全仓 Pytest：**1691 passed, 2 deselected**（41.38 秒）。覆盖研究模块、旧 A 股分析、报告、CLI 兼容与完整项目测试。
- wheel：`da-a-data-0.17.0-py3-none-any.whl`，构建成功。
- 隔离环境安装 wheel 后导入研究模块、读取 9 个指数 Registry 并渲染页面：通过。
- `da-a-analyze --help` 不是项目支持的帮助入口；该调用进入默认股票分析并尝试行情请求 3 次后因 Provider 返回错误终止。没有重复该调用；CLI 兼容以全仓既有测试结果为证据。
- `python -m build --wheel --no-isolation` 首次因默认 Python 缺少 build 工具失败；隔离环境补齐声明依赖后构建成功。

## AO / 临时产物

Pytest、构建会在本 RC 工作树生成 Python 缓存、`.pytest_cache`、`build/` 和 `da_a_data.egg-info/`。这些只属于本轮 RC 工作树；最终卫生检查会清理这些本轮产物，保留已跟踪截图和原工作区历史文件。未修改 AO 框架，也未清理旧 Worktree。

## PR 准备与合并判断

建议 PR 标题：`发布候选：Swartee Market Research 全球研究终端 V1`。

说明要点：将研究模块统一身份与快照服务、9 指数日线和市场状态、全局终端 UI V1 收口到一个候选基线；兼容现有 A 股分析器和 CLI；全量测试 1691 passed / 2 deselected、RC Python Ruff 通过、wheel 与隔离安装通过、九个指数单次真实请求成功；交易日历状态仍未知；GitHub CI 未验证；精确 1440 / 768 / 390 浏览器视口及触摸交互未实测。

**当前不建议直接合并 main。** 下一步需先完成上述视口和触摸验收，再授权 Push/创建 PR，等待 GitHub CI 后复核主线合并条件。此建议不代表 RC 已有远端 PR 或 CI 结果。

## 后续三项

1. 增加有来源证据的多市场交易日历和状态刷新口径。
2. 补齐 1440 / 768 / 390 视口与触摸 K 线浏览验收，并按实际发现修复布局问题。
3. 在 V1 PR/CI 完成后规划自选市场比较，再推进新闻、公告与事件筛选。
