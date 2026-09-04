# baostock + pandas 集成踩坑

baostock 是 A 股零 key 数据源里唯一一个能拿到 **估值历史 PE/PB 分位** + **换手率 + ST 标记**的（V3.7 用例）。但它的 Python API 跟 pandas 的对接有几个 silent-failure 模式。

## Pitfall 1: `pd.DataFrame(rows)` 没有列名

baostock 返回的是 **行数据列表 + 字段名列表**（两个分开的属性）：

```python
rs = bs.query_history_k_data_plus("sz.001696", "date,code,close,peTTM,...")
rows = []
while rs.error_code == "0" and rs.next():
    rows.append(rs.get_row_data())   # 只返回行数据
# 此时 rs.fields = ['date', 'code', 'close', ...]
df = pd.DataFrame(rows)               # ❌ 列名是 0..N，不是 'date'/'code'/'close'
df["close"]                           # KeyError: 'close'
```

正确写法：

```python
df = pd.DataFrame(rows, columns=rs.fields)   # ✅
```

**为什么这是 silent failure**：如果直接 `df.iloc[0]` 拿数字没事，但任何 `df["col_name"]` 都 KeyError，错误抛在远离 baostock 调用栈的地方，调试耗时长。a-stock-data 2026-09-03 一次实测中，这个 bug 让 `fetch_valuation_history` 在跑了 ~20s baostock login/query 之后才崩，前面的「拿到数据了」的日志让人误以为问题在更下游。

## Pitfall 2: `start_date` 太早导致中间出现 NaN

baostock 对某些股票（比如 ST、刚退市、刚上市）会在某些日期返回空字段，而不是跳过该日期。`pd.to_numeric(errors="coerce")` 把空字符串变成 NaN。

```python
for c in ("close", "peTTM", "pbMRQ", ...):
    df[c] = pd.to_numeric(df[c], errors="coerce")
# 然后 df.dropna(subset=["peTTM", "pbMRQ"])   ← 如果全 NaN，df 变空，下游 percentiles 计算报错
```

防御写法：

```python
df = df.dropna(subset=["peTTM", "pbMRQ"])
if df.empty:
    return {"error": "baostock 历史估值全为空（可能 ST/退市/新股）"}
```

## Pitfall 3: baostock 不支持北交所和 ETF

```python
code = "920982"  # 北交所
bs_code = f"sh.{code}" if code.startswith("9") else f"sz.{code}"
bs.query_history_k_data_plus(bs_code, ...)   # 返回 error_code 非 0，data 为空
```

V3.7 SKILL.md 明确说：`4 / 8 / 92 / 920` 号段 baostock 直接拒绝。
代码端要**先用 `get_prefix(code)` 判断**，对北交所直接返回 `{"error": "baostock 不支持北交所"}` 而不是傻调。

## Pitfall 4: `bs.login()` 必须每个进程调一次，且不能跨进程复用

baostock 走 TCP 长连接到本地 daemon（`localhost:9000`？具体看版本）。**不能跨进程** — 子进程或新 terminal 必须重新 `bs.login()`。一个常见模式：

```python
bs.login()
try:
    # do queries
    pass
finally:
    bs.logout()
```

或者用 `with bs_session() as bs:` 上下文管理器（V3.7.2 SKILL.md 提供了 `bs_session()` helper）。

## Pitfall 5: 估值分位 = (count of values < current) / total

实现 PE 历史分位的标准公式：

```python
pe_series = df["peTTM"].dropna()
cur_pe = pe_series.iloc[-1]
pe_pct = (pe_series < cur_pe).sum() / len(pe_series) * 100
```

含义：「当前 PE 在过去 N 天里排多少百分位」。**值越小越便宜**（PE 分位 20% = 比 80% 的历史日子便宜）。

⚠️ 不要用 `scipy.stats.percentileofscore` — 它默认是「有多少比例的值 ≤ 当前值」，跟 baostock/同花顺「严格小于」的口径差 1 个样本，A 股研报圈通用的是严格小于。

## Pitfall 6: `frequency` / `adjustflag` 参数名容易写错

```python
rs = bs.query_history_k_data_plus(
    bs_code,
    fields="...",
    start_date=..., end_date=...,
    frequency="d",          # ✅ 不是 "1d" 或 "day"
    adjustflag="3",         # ✅ 3=不复权, 1=后复权, 2=前复权
)
```

`adjustflag=3`（不复权）是 V3.7 默认（与通达信一致），不要因为看到 "adjust" 就想用 1/2。

## 测试 recipe

跑通后再写代码。最小验证：

```bash
~/.hermes/skills/finance/a-stock-data/venv/bin/python -c "
import baostock as bs
import pandas as pd
bs.login()
rs = bs.query_history_k_data_plus('sz.600519', 'date,close,peTTM,pbMRQ',
    start_date='2024-01-01', end_date='2024-12-31', frequency='d', adjustflag='3')
rows = []
while rs.error_code == '0' and rs.next():
    rows.append(rs.get_row_data())
bs.logout()
df = pd.DataFrame(rows, columns=rs.fields)   # ← 关键
print(len(df), df.iloc[0]['date'], '→', df.iloc[-1]['date'])
print('peTTM 范围:', float(df['peTTM'].min()), '~', float(df['peTTM'].max()))
"
```

期望输出：`244 2024-01-02 → 2024-12-31` + 一个 PE 范围（茅台 2024 大约 22~28）。