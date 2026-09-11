# 三价位 (支撑/压力/止损) 计算规则

> 范围: `analysis/quant_analyzer_v3.py:compute_three_levels`
> 规范: 《08-项目代码规范与验收要求》§6 计算与数据质量 + §12 P0 修法
> 版本: v1.0 (2026-09-11, P0-A 整改落地)
> 状态: ✅ 命名统一 + 边界测试已加

## 一、术语

| 术语 | 含义 | 单位 |
|---|---|---|
| 支撑 (support) | 现价下方候选价位, **用作**"看多时低吸参考价" | 元 |
| 压力 (resistance) | 现价上方候选价位, **用作**"看空时减仓参考价" | 元 |
| 止损 (stop_loss) | 收盘跌破即无条件离场的价位 | 元 |
| 支撑下沿 | 支撑候选 ±5% 区间内的最低 (允许跨现价 5%) | 元 |
| 压力上沿 | 压力候选 ±5% 区间内的最高 (允许跨现价 5%) | 元 |
| 候选价 | 4 类支撑/3 类压力候选的原始计算值 | 元 |

> §6 规范"最近支撑/压力"标准定义: 不高于现价的最大 / 不低于现价的最小。
> **本项目采用 "支撑下沿/压力上沿" 命名** (与 V3 报告已用的"区间下沿/上沿"一致)，
> 含义 = ±5% 区间内的最低/最高，**允许跨现价 5%**。
> §6 规范要求"若产品选择区间极值或允许跨越现价, 必须另行命名"——本节为命名规范文档。

## 二、支撑候选 (4 类)

支撑候选按以下顺序计算，任一缺失不影响其他候选：

| 候选键 | 计算口径 | 数据源 | 缺失场景 |
|---|---|---|---|
| `ma60` | K 线 close 序列 60 日简单移动平均 | baostock 前复权 | K 线 < 60 日 |
| `recent_low` | 60 日内 K 线 low 最小值 | baostock 前复权 | K 线 < 60 日 |
| `chip_peak` | 筹码分布峰位 (peak_price) | v2 筹码 fetcher | 筹码数据失败 (返回 `{"error":...}`) |
| `boll_lower` | 布林下轨 = MA20 - 2σ | K 线 close 序列 | K 线 < 20 日 |

**过滤与取最近**：

1. 过滤掉 `> price * 1.05` 的候选（允许候选略高于现价 5%）
2. 在剩余候选中取**最小值** → 即"支撑下沿"
3. 若无候选通过过滤 → `support = None`（报告中显示"无有效支撑"）

## 三、压力候选 (3 类)

| 候选键 | 计算口径 | 数据源 | 缺失场景 |
|---|---|---|---|
| `ma250_or_ma120` | K 线 close 250 日均线; K<250 时回退 120 日 | baostock 前复权 | K 线 < 120 日 |
| `recent_high` | 60 日内 K 线 high 最大值 | baostock 前复权 | K 线 < 60 日 |
| `boll_upper` | 布林上轨 = MA20 + 2σ | K 线 close 序列 | K 线 < 20 日 |

**过滤与取最近**：

1. 过滤掉 `< price * 0.95` 的候选（允许候选略低于现价 5%）
2. 在剩余候选中取**最大值** → 即"压力上沿"
3. 若无候选通过过滤 → `resistance = None`

## 四、止损

**不复算**，直接复用 `trading_plan.stop_loss`（V2 同源 1.5 步产出，Task 5.1 锁定字段）。
若 `trading_plan` 缺失或 `stop_loss` 字段为 `None` → `stop_loss = None`（报告注明"无止损参考"）。

## 五、返回契约

```python
@dataclass
class ThreeLevels:
    support: Optional[float]       # 支撑下沿 = 候选最小 (过滤 > 1.05×price)
    resistance: Optional[float]    # 压力上沿 = 候选最大 (过滤 < 0.95×price)
    stop_loss: Optional[float]     # 止损 = trading_plan.stop_loss (不复算)
    support_candidates: Dict[str, float]    # 全部支撑候选 (未过滤)
    resistance_candidates: Dict[str, float] # 全部压力候选 (未过滤)
    method: str                              # 算法描述, 含 N=K线数
```

## 六、例子

### 例子 1: 正常场景 (N=250, 600693 9-11 跑通实测)

```
price = 10.76
support_candidates = {ma60: 8.96, recent_low: 7.16, chip_peak: 11.30, boll_lower: 8.00}
  → 过滤 > 10.76×1.05=11.298: chip_peak 11.30 被过滤 (11.30 > 11.298)
  → 剩余 {ma60: 8.96, recent_low: 7.16, boll_lower: 8.00}
  → 最小 7.16 (recent_low) → support = 7.16

resistance_candidates = {ma250_or_ma120: 9.76, recent_high: 12.20, boll_upper: 11.78}
  → 过滤 < 10.76×0.95=10.222: ma250_or_ma120 9.76 被过滤
  → 剩余 {recent_high: 12.20, boll_upper: 11.78}
  → 最大 12.20 (recent_high) → resistance = 12.20

stop_loss = 9.33 (复用 trading_plan, 现价下 13.3%)
```

### 例子 2: 全部候选缺失 (N=0, K 线全空)

```
price = 10.00
support = None
resistance = None
stop_loss = None (trading_plan 也不可用)
method = "4 候选取最近者（支撑 ≤ 1.05×现价；压力 ≥ 0.95×现价；N=0）"
报告: "三价位无法生成 (行情/筹码数据缺失), 请勿据此操作。"
```

### 例子 3: 跨价过滤 (605162 K 线缺, 旧 report 9-10 跑过)

```
price = 11.20
sup_raw = {ma60: 10.5, recent_low: 9.0, chip_peak: 11.50, boll_lower: 9.5}
  → chip_peak 11.50 > 11.20×1.05=11.76? 11.50 < 11.76 保留
  → 全部 4 个候选都保留
  → 最小 9.0 (recent_low) → support = 9.00
```

### 例子 4: 候选全部跨价 (异常场景, 测试用)

```
price = 10.00
sup_raw = {ma60: 12.0, recent_low: 11.0, chip_peak: 12.5, boll_lower: 11.5}
  → 全部 > 10.00×1.05=10.50
  → 过滤后无候选
  → support = None
报告: "支撑候选全部高于现价 5%, 视为无有效支撑。"
```

## 七、报告层描述

V3 报告 §"三价位 (V2 同源实时模型 · 4 候选取最近)" 段描述必须含:

- "支撑下沿 (support) = 4 支撑候选最小值, 过滤 > 1.05×现价"
- "压力上沿 (resistance) = 3 压力候选最大值, 过滤 < 0.95×现价"
- "止损 (stop_loss) = 复用 V2 trading_plan, 不重算"
- "N = K 线根数, 0 表示无 K 线"
- 候选全部缺失时: "三价位无法生成 (行情/筹码数据缺失), 请勿据此操作。"
- 任一候选为空时: 报告"⚠️ {key} 候选缺失 (原因), 实际取最近 {n} 候选"。

## 八、与其他模块边界

- `trading_plan.stop_loss` 必须存在才能复用; v2.analyze_single 失败时该字段为 None, V3 仍按 None 处理
- 候选 chip_peak 来自 `chip_data.peak_price` 平铺字段 (v2 line 572), 不在 `cost_concentration` 子键
- K 线字段在 `chip_data["kline"]` (v2 平铺), 不在 `technical.*`
- boll = MA20 ± 2σ, σ = 20 日 close 标准差

## 九、回归测试

`tests/test_three_levels.py` 已覆盖:
- 正常场景
- 候选为空 (N<60)
- 跨价过滤
- 止损复用 / 缺失

P0-A 新增 (本轮):
- 全部候选缺失 (N=0) → support/resistance/stop_loss 全 None
- 候选全部 > 1.05×price → support = None, 边界说明
- 候选全部 < 0.95×price → resistance = None, 边界说明
- method 字段含 N=K线数
- 候选名 + 数值一致性
