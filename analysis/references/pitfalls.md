# 踩过的坑 & 调试记录（a-stock-data V2.1~V2.2 升级）

本文件是会话级调试记录，新会话遇到类似问题直接查这里。

---

## 🐛 P0: baostock `KeyError: 'close'`

**症状**：`pd.DataFrame(rows)` 后 `df['close']` 报 KeyError，但 `len(rows)` 显示有 600+ 条数据。

**原因**：`pd.DataFrame(rows)` 默认生成 `RangeIndex(0, 10)` 列名，**没有用 `rs.fields`**。

**修复**：
```python
df = pd.DataFrame(rows, columns=rs.fields)
```

**教训**：baostock 的 `rs.fields` 一定要用，不要自己手写字段名列表。

---

## 🐛 P1: baostock 不支持北交所

**症状**：`baostock` 报 `10004011 股票代码未标识sh或sz`。

**原因**：baostock 不支持 4/8/92/920 号段（即北交所）。

**修复**：在调用前加 `get_prefix(code)` 判断：
```python
def _bs_code(code):
    code = str(code).zfill(6)
    if code[:2] in ("60", "68", "90"): return f"sh.{code}"
    if code[:2] in ("00", "30", "20"): return f"sz.{code}"
    raise ValueError(f"baostock 不支持该代码: {code}")
```

---

## 🐛 P2: 申万 XLS SSL 证书失败

**症状**：`swsresearch.com` 下载 XLS 时 `SSL: CERTIFICATE_VERIFY_FAILED`。

**原因**：沙盒环境（conda-packaged Python）的 `certifi` 包版本过旧。

**修复**（用户本机）：
```bash
cd ~/.hermes/skills/finance/a-stock-data
./venv/bin/python -m pip install -U certifi
```

**脚本端**：已优雅降级，打印 `[WARN] sw_industry_history SSL 握手失败` + 修复提示，申万因子 fallback 到 mock（5 分基础）。

---

## 🐛 P3: 东财 push2 SSL 握手超时

**症状**：`push2.eastmoney.com` SSL 握手卡 10s+ 后超时。

**原因**：沙盒环境走代理 + VPN，SSL 握手不稳定。

**影响**：板块归属 / 资金流 / 解禁 / 龙虎榜这几个东财端点全部不可用。

**用户本机**：国内 IP 直连应该正常。如果不行：
- 换手机热点
- 调大 `EM_MIN_INTERVAL`（间隔时间）
- 复用 `EM_SESSION`（Keep-Alive）

---

## 🐛 P4: 百度 PAE selfselect 接口被风控

**症状**：`finance.pae.baidu.com/selfselect/symbol` 返回 `text/html` 空 body（status 200）。

**原因**：需要 PC UA + 自定义 stockid 校验，沙盒模拟不到位。

**修复**：V3.7.2 SKILL.md 推荐用 `baidu_kline_with_ma`，但实测在沙盒里跑不通。**fallback**：用 `mootdx` TCP 或 `eastmoney_fund_flow_minute` 取日 K 线。

---

## 🐛 P5: V1 时代的腾讯字段映射坑

**症状**：网上教程说腾讯字段 43 是 PB，实际拿到的可能是振幅%。

**实测 001696 宗申动力**：
- parts[43] = 振幅 5.19% (不是 PB!)
- parts[46] = PB 3.52 (正确)
- parts[39] = PE-TTM 33.7
- parts[45] = 流通市值 195 亿 (不是总市值！总市值用 mcap 单独算)
- parts[44] = 另一种市值口径

**教训**：永远按实测值来，不要照抄网上教程。`fetch_tencent_quote` 函数里加 assert 验证。

---

## 🐛 P6: 写入文件时 Unicode 引号导致 patch 失败

**症状**：用 `skill_manage(action='patch')` 或 `patch` 工具替换带 `'` `"` 的字符串时，反斜杠转义搞乱，最终 SyntaxError。

**原因**：`\\'` `\\"` `\\n` 在嵌套 string 里多次转义后破坏语义。

**修复**：
1. **复杂插入用 `execute_code` + `str.replace`**，不要用 patch 工具
2. **多行 Python 永远走 `execute_code`**（Hermes 安全层会拦截长 `python3 -c "..."`）
3. **`write_file` 写独立 .py 文件**，再 import 进主脚本

**教训**：编辑大型 Python 文件时，patch 工具能省事但容易踩 Unicode 雷。**复杂的插入/替换用 execute_code + str.replace 更稳**。

---

## 🐛 P7: f-string 嵌套 dict 坑

**症状**：`f-string: {code} {"param": value}` 报 `TypeError: unhashable type: 'dict'`。

**原因**：f-string 里嵌套 `{...}` 表达式时，**表达式不能是 dict literal**（花括号嵌套）。

**修复**：把内层 dict 提到 f-string 外面：
```python
params = {"market": "ab", "code": code}  # 先建好
url = f"https://example.com?{params}"    # f-string 不嵌套
```

---

## 🐛 P8: `htmlpreview.github.io` 已失效

**症状**：`https://htmlpreview.github.io/?<gist_url>` 返回 1269 字符占位页，**不渲染 HTML**。

**原因**：2024 年 GitHub 改 Gist API 后失效。

**实测 2026-09-03 不可用的渲染服务**：
- `htmlpreview.github.io` — 失效
- `rawcdn.githack.com` — 404
- `cdn.jsdelivr.net/gh/<gist_id>` — 404（只支持 repo，不支持 gist）
- `0x0.st` — 关闭（"AI botnet spam"）
- `transfer.sh` — 拒绝连接

**唯一稳定方案**：GitHub Pages + 临时 repo（详细流程见 `report-delivery.md`）。

---

## 🐛 P9: 沙盒里 `git push` 卡 60s

**症状**：`git push -u origin main` timeout。

**原因**：HTTPS GitHub 授权在沙盒环境走不通。

**修复**：用 `gh api PUT /repos/<user>/<repo>/contents/<file>` 上传文件：
```bash
content_b64=$(base64 -i report.html)
gh api --method PUT repos/Swartea/repo/contents/index.html \
  -f message="report" -f content="$content_b64"
```

---

## 🐛 P10: `runs/fetch_stock.py` 等子文件其实是 404

**症状**：V3.2.2 README 提到 `scripts/smoke_test.py`、`scripts/fetch_stock.py` 等文件，但 GitHub 上 404。

**原因**：V3.7.2 砍掉了这些子文件，README 是早期 V3.2 时代的设计。**V3.7 是真正的"单文件 SKILL.md 自包含"**。

**修复**：删除 14 字节的占位文件，不要让它们误导。

---

## 📋 调试流程速查

| 症状 | 优先查 |
|------|--------|
| 东财端点全部超时 | 沙盒 VPN/代理 → 切用户本机 |
| baostock 10004011 错误 | 北交所代码 → 换腾讯/东财快照 |
| pd.DataFrame KeyError | 检查 columns 参数是否指定 |
| GitHub Pages 404 | 等 1-2 分钟（首次部署） |
| HTML 当文本显示 | Content-Type 是 text/plain → 换 GitHub Pages |
| 写入文件 SyntaxError | 检查 Unicode 转义 → 改用 str.replace |
| f-string 报错 | 嵌套 dict → 提到外面 |