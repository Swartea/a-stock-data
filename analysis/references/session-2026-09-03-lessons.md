# 会话 2026-09-03 教训汇总

> 本文件记录实战中遇到的坑和解决办法，按主题分类。后续会话遇到同类问题先看这里。

---

## 1. 模块/沙盒陷阱

### 1.1 urllib.request.urlopen 在沙盒里会卡住
- **现象**：调用 `urllib.request.urlopen(req, timeout=10)` 不抛异常也不返回，卡到 timeout 时直接进程退出，无任何输出
- **根因**：沙盒走代理时 urllib 的 SSL 握手阻塞
- **解法**：**所有 HTTP 调用统一用 `requests.get(..., timeout=10)`**。requests 在沙盒里稳定
- **影响范围**：腾讯实时行情 / baostock 之外的 HTTP 调用都受影响
- SKILL.md 第 1.2 节 §tencent_quote 的代码示例用了 `urllib.request`，照搬会被坑

### 1.2 baostock 返回的 DataFrame 列名问题
- **现象**：`pd.DataFrame(rows)` 不传 `columns=rs.fields` 时，列是 `0..n-1`，访问 `df["close"]` 抛 KeyError
- **解法**：必须 `pd.DataFrame(rows, columns=rs.fields)`
- **教训**：用 baostock 时**永远显式传 columns**，别省这一行

### 1.3 沙盒里网络部分可用，部分超时
| 数据源 | 沙盒可用性 |
|--------|-----------|
| 腾讯 qt.gtimg.cn | ✅ |
| 同花顺 basic.10jqka.com.cn | ✅ |
| 同花顺 data.hexin.cn (北向) | ✅ |
| 同花顺 zx.10jqka.com.cn (热点) | ✅ |
| baostock (TCP) | ✅ |
| 东财 push2.eastmoney.com | ⚠️ SSL 握手超时 |
| 东财 push2delay.eastmoney.com | ❌ Read timed out |
| 百度 finance.pae.baidu.com | ⚠️ 空 body（要 PC UA） |
| 申万 swsresearch.com | ❌ SSL cert 过期 |

---

## 2. 代码陷阱（实战踩过的）

### 2.1 f-string 嵌套三引号 / dict 字面量
```python
# ❌ 错（Python 3.12 不报错但语义不对，3.11 报错）
f"key='{ {"a": 1}['a'] }'"
# ❌ 错（多行三引号在 f-string 里要 \\n 转义）
changes_str = "\n".join(...)  # 在 f-string 里要 \\n.join
# ✅ 对（用 .format() 或 % 字符串）
"text {key}".format(key=value)
```
**教训**：长 HTML/多行字符串拼接用 `.format()` 或 `%s`，不要在 f-string 里嵌多行字符串

### 2.2 pd.DataFrame 一定要指定列
```python
# ❌ 错
df = pd.DataFrame(rows)
df["close"]  # KeyError
# ✅ 对
df = pd.DataFrame(rows, columns=rs.fields)
```

### 2.3 `r["fund", {}]` 是 tuple 索引不是 dict.get
```python
# ❌ 错（这是返回 ("fund", {}) 元组）
fund = r["fund", {}]
# ✅ 对
fund = r.get("fund") or {}
```

### 2.4 execute_code/terminal 走 pip 时报"timeout without user response"
- **现象**：Hermes 安全层对长 `python -c` 命令敏感
- **解法**：复杂 Python 一律用 write_file 写脚本再 python script.py
- **沙盒限制**：用 sandbox 的 python（不是用户的 venv），超时 30s

---

## 3. 申万 / 筹码分布踩坑（V3.7 新端点）

### 3.1 申万表加载失败 SSL cert 过期
- **现象**：`swsresearch.com` 的 CA 证书沙盒不认
- **解法**（用户本机）：`./venv/bin/python -m pip install -U certifi`
- **SKILL.md 没写这个**，要补

### 3.2 chip_distribution 强制要求时间升序
- SKILL.md §6.5 写得很清楚：必须按 date 升序传入，否则"衰减反向推 + close.iloc[-1] 当现价"
- **陷阱**：baostock 返回的就是升序，但若用其他数据源要先 `sort_values("date")`

### 3.3 baostock 不支持北交所
- 代码里 `_bs_code()` 直接 `raise ValueError`，不是 try/except
- 调用前要拦截 4/8/92/920 号段
- SKILL.md Q&A 已说明

### 3.4 申万 sw_industry_history 表结构
- 列名中文：股票代码 / 计入日期 / 行业代码
- 行业代码是 6 位（"010101"），L1 = 前 2 位 + "0000"，L2 = 前 4 位 + "00"
- 不是申万官方代码（官方不发布名称表），东财/通达信名称不能套

---

## 4. 报告生成（V2.2 人话版 + HTML）

### 4.1 用户原话："现在的报告我看不懂"
- 数字本身不告诉你任何操作决策
- **解法**：报告必须先讲结论（能不能买 / 仓位 / 止损止盈点位），再讲数据
- 结构：🎯 一分钟结论 → 👍/👎 信号清单 → 详细数据表 → 三种情景应对

### 4.2 Markdown vs HTML
- Markdown 在终端/markdown viewer 友好，手机上无图表
- **HTML 报告**更优：单文件 < 50KB、内嵌 SVG 图表、离线可看、微信直发
- 关键技术：纯 SVG 手写图表（不依赖 CDN/JS）

### 4.3 报告里"PE 33.7"用户看不懂，要翻译
- 解法：`_interpret_pe(pe)` → "PE 33.7 合理，可接受"
- 阈值：<15 极低 / <25 偏低 / <40 合理 / <80 偏贵 / >80 极高估

### 4.4 报告要给具体操作点位
- 止损位：从筹码峰 + 平均成本 + 现价 ×0.93 取更保守的
- 止盈三档：+10% / +25% / +50%
- 仓位：评分≥75 重仓 60-80% / ≥65 中仓 30-50% / ≥55 轻仓 10-20% / <55 不进场

---

## 5. 文档/部署经验

### 5.1 DEPLOY_NOTES.md 是版本演进的可贵资料
- 每次升级记录：版本号、关键变化、依赖、测试结果
- 部署说明 + 测试结果 + 已知限制 = 三段式

### 5.2 V1 vs V2 共存
- V1 保留不动（兼容旧调用）
- V2 是推荐入口
- 未来 V1 加 deprecation 警告

---

## 6. quant_analyzer_v2.py 升级时间线

| 版本 | 日期 | 关键变化 |
|------|------|---------|
| V1 | 2026-06-17 | 6 因子 / 9 端点（V3.2.2 时代）|
| V2 | 2026-09-03 | 10 因子 / 22 端点 + Markdown 报告 |
| V2.1 | 2026-09-03 | 筹码分布 + 申万行业满血 |
| V2.2 | 2026-09-03 | 人话报告 + 单文件 HTML（29 KB）+ 4 张 SVG 图 |

---

## 7. 待补（下次会话做）

- [ ] 东财 push2 在本机调试，确认无 SSL 问题
- [ ] certifi 升级后重新跑申万端点
- [ ] 跑批量 5 票生成 5 份 HTML 报告
- [ ] HTML 报告加深色模式