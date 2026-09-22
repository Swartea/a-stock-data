## Layer 11: 宏观层（社融 + PMI，V3.7.0 新增）

> A股是流动性驱动市场，社融是**领先指标**、PMI 是**同步指标**。两者都由官方直接发布，零鉴权。
> ⚠️ 本层是**月频**数据，不要当日频信号用；发布日固定（社融次月中旬、PMI 月末），
> 未发布月份**不会**出现在返回里（见下方 fail-fast 说明）。
>
> **社融支持范围：2021 年起**（2026-08-19 实测 2021~2026 六年全部可解析，每年 12 行且不跨年）。
> 2020 及更早是旧版式——表头与项目名合并在一个单元格、且附表带「2017 年以来」的历史区，
> 传入这些年份会**抛错而不是返回可疑数据**。

### 11.1 🆕⚠️ 人民银行 — 社会融资规模增量

**核心价值：** 官方口径的全社会流动性投放，A股中期最重要的宏观变量。中英双语 12 列。

**链路是三级跳**（索引 → 年份页 → 专题页 → xls 附件），任何一级结构变更都会 fail-fast 抛错，不静默返回空。

```python
import io
import re
from typing import Optional

import pandas as pd
import requests

_UA = {"User-Agent": "Mozilla/5.0"}
PBC_BASE = "https://www.pbc.gov.cn"
PBC_INDEX = f"{PBC_BASE}/diaochatongjisi/116219/116319/index.html"


def _macro_get(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def _abs_pbc(href: str) -> str:
    return href if href.startswith("http") else PBC_BASE + href


def pboc_social_financing(year: Optional[int] = None) -> pd.DataFrame:
    """人民银行「社会融资规模增量统计表」— 月度，单位亿元；year=None 取最新年"""
    idx = _macro_get(PBC_INDEX)
    years = re.findall(r"""href=["']([^"']+)["'][^>]*>\s*(\d{4})年统计数据\s*</a>""", idx)
    if not years:
        raise RuntimeError("人民银行索引页未找到「XXXX年统计数据」链接，页面结构可能已变更")
    table = {int(y): href for href, y in years}
    target = max(table) if year is None else year
    if target not in table:
        raise ValueError(f"人民银行无 {target} 年数据，可选年份: {sorted(table, reverse=True)[:8]}")

    ypage = _macro_get(_abs_pbc(table[target]))
    topics = re.findall(r"""href=["']([^"']+)["'][^>]*>\s*(社会融资规模)\s*</a>""", ypage)
    if not topics:
        raise RuntimeError(f"{target} 年页未找到「社会融资规模」专题链接")

    tpage = _macro_get(_abs_pbc(topics[0][0]))
    books = re.findall(r"""href=["']([^"']+\.xlsx?)["']""", tpage)
    if not books:
        raise RuntimeError(f"{target} 年社融专题页未找到 xls/xlsx 附件")

    content = requests.get(_abs_pbc(books[0]), headers=_UA, timeout=60).content
    raw = pd.read_excel(io.BytesIO(content), header=None)

    start = None                      # 表头是中英双行 + 单位说明，用「月份」列定位数据起点
    for i in range(len(raw)):
        if str(raw.iloc[i, 0]).strip() == "月份":
            start = i
            break
    if start is None:
        raise RuntimeError(
            f"{target} 年社融表没有独立的「月份」表头单元格。"
            "**2020 及更早采用旧版式**（表头与项目名合并在同一单元格，且附表含 2017 年以来的历史区），"
            "本端点仅支持 **2021 年起**（2026-08-19 实测 2021~2026 全部可解析）。"
        )

    cols = ["month", "afre_total", "rmb_loans", "fx_loans", "entrusted_loans",
            "trust_loans", "undiscounted_bankers_acceptance", "corporate_bonds",
            "government_bonds", "equity_financing", "abs_by_depository", "loans_written_off"]
    df = raw.iloc[start + 3:].copy().iloc[:, :len(cols)]
    df.columns = cols
    df = df[df["month"].astype(str).str.match(r"^\d{4}\.\d{1,2}$", na=False)].copy()
    for c in cols[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    def _month_label(v):
        """`2026.01` → 2026-01；`2026.1` → 2026-10。

        Excel 把 `2026.10` 的尾零吃掉读成浮点 `2026.1`，与 1 月的 `2026.01` 撞车。
        1 月在表里始终写作两位 `.01`，因此**单个小数位必然是被吃了尾零的 x0 月**。
        按单元格逐行解析（而不是按行序编号），跨年工作簿也不会错位。
        """
        m = re.match(r"^(\d{4})\.(\d{1,2})$", str(v).strip())
        if not m:
            return None
        year_s, mon_s = m.group(1), m.group(2)
        if len(mon_s) == 1:
            mon_s += "0"
        return f"{year_s}-{int(mon_s):02d}"

    df["month"] = [_month_label(v) for v in df["month"]]
    df = df[df["month"].notna()]
    # 旧工作簿底部会附「表1：2017年以来各月…」的历史区，只保留目标年，防跨年污染
    df = df[df["month"].str.startswith(f"{target}-")].reset_index(drop=True)

    # 未发布月份整行为空 —— 必须丢掉，否则调用方会把 12 行当成 12 个月的真数据。
    df = df.dropna(subset=["afre_total"]).reset_index(drop=True)
    if df.empty:
        raise RuntimeError(f"社融表解析后无有效月份（{target} 年），格式可能已变更")
    return df


# 用法
df = pboc_social_financing()          # 最新年（只含已发布月份）
print(df[["month", "afre_total", "rmb_loans", "government_bonds"]].to_string(index=False))
# 实测 2026-08-19：返回 7 行（2026-01 ~ 2026-07），2026-01 社融增量 72,185 亿
# 全部 12 列：month / afre_total(社融增量) / rmb_loans(人民币贷款) / fx_loans(外币贷款) /
#   entrusted_loans(委托贷款) / trust_loans(信托贷款) /
#   undiscounted_bankers_acceptance(未贴现银行承兑汇票) / corporate_bonds(企业债券) /
#   government_bonds(政府债券) / equity_financing(非金融企业境内股票融资) /
#   abs_by_depository(存款类金融机构ABS) / loans_written_off(贷款核销)

hist = pboc_social_financing(2024)    # 指定年份
print(len(hist), "个月, 全年社融增量", f"{hist['afre_total'].sum():,.0f}", "亿元")
# 实测：12 个月, 322,588 亿元
```

---

### 11.2 🆕⚠️ 国家统计局 — 采购经理指数 PMI

**核心价值：** 制造业景气度同步指标，50 是荣枯线。月末发布，比上市公司财报早一个季度反映景气。

```python
import re

import requests

NBS_INDEX = "https://www.stats.gov.cn/sj/zxfb/"
_UA = {"User-Agent": "Mozilla/5.0"}


def _macro_get(url: str, timeout: int = 30) -> str:
    """与 §11.1 同名同实现 —— 本块按「端点路由速查」单独取用时也能独立跑，
    不必先执行 §11.1。两处同时执行时后定义覆盖前者，行为一致，无副作用。"""
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def nbs_pmi() -> dict:
    """国家统计局最新 PMI — 制造业 / 非制造业商务活动 / 综合产出 + 大中小型企业"""
    idx = _macro_get(NBS_INDEX)
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{6,80}?)\s*</a>', idx)
    hit = next(((u, t) for u, t in links if "采购经理指数" in t), None)
    if not hit:
        raise RuntimeError("国家统计局最新发布页未找到「采购经理指数」条目")
    href, title = hit
    url = href if href.startswith("http") else NBS_INDEX + href.lstrip("./")

    html = _macro_get(url)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    # 🔴 正文是全角括号且**括号内带空格**（`（ PMI ）为 49.2%`）。
    #    必须把空白**整个删掉**；只做「压成单个空格」会一条都匹配不到。
    text = re.sub(r"[\s\u3000\xa0]+", "", text)

    def grab(pat):
        m = re.search(pat, text)
        return float(m.group(1)) if m else None

    ym = re.search(r"(\d{4})年(\d{1,2})月", title)

    # 分档措辞统计局用过三种版式，逐层回退；解析不到留 None（属可选字段）。
    #   ① 全合并：大、中、小型企业PMI分别为 A%、B%和C%
    #   ② 半拆：  大型企业PMI为 A%…；中、小型企业PMI分别为 B%和C%
    #   ③ 全拆：  大型企业PMI为 A%…；中型企业PMI为 B%…；小型企业PMI为 C%
    # 注：③ 的单条正则要求「…企业PMI为」，不会误匹配 ①② 里的「…企业PMI分别为」。
    large = medium = small = None
    combined = re.search(r"大、中、小型企业PMI分别为([\d.]+)%、([\d.]+)%和([\d.]+)%", text)
    if combined:
        large, medium, small = (float(x) for x in combined.groups())
    else:
        m_ms = re.search(r"中、小型企业PMI分别为([\d.]+)%和([\d.]+)%", text)
        if m_ms:                            # ② 中小型合并一句
            medium, small = (float(x) for x in m_ms.groups())
        for _name, _pat in (("large", r"大型企业PMI为([\d.]+)%"),
                            ("medium", r"中型企业PMI为([\d.]+)%"),
                            ("small", r"小型企业PMI为([\d.]+)%")):
            _m = re.search(_pat, text)      # ③ 各自单独成句
            if _m:
                _v = float(_m.group(1))
                if _name == "large":
                    large = _v
                elif _name == "medium" and medium is None:
                    medium = _v
                elif _name == "small" and small is None:
                    small = _v

    result = {
        "title": title.strip(),
        "period": f"{ym.group(1)}-{int(ym.group(2)):02d}" if ym else None,
        "manufacturing_pmi": grab(r"(?<!非)制造业采购经理指数（PMI）为([\d.]+)%"),
        "non_manufacturing_pmi": grab(r"非制造业商务活动指数为([\d.]+)%"),
        "composite_pmi": grab(r"综合PMI产出指数为([\d.]+)%"),
        "pmi_large": large,
        "pmi_medium": medium,
        "pmi_small": small,
        "source_url": url,
    }
    # 三个主指标是本端点的承诺输出，解析不到必须 fail-fast ——
    # 统计局改一次措辞就静默返回一串 None，调用方会当成「本月没数据」。
    core = ("manufacturing_pmi", "non_manufacturing_pmi", "composite_pmi")
    absent = [k for k in core if result[k] is None]
    if absent:
        raise RuntimeError(
            f"PMI 正文措辞可能已变更，无法解析 {absent}；请核对页面：{url}"
        )
    return result


# 用法
p = nbs_pmi()
print(p["period"], "制造业", p["manufacturing_pmi"], "非制造业", p["non_manufacturing_pmi"])
# 实测 2026-08-19：2026-07 制造业 49.2 / 非制造业 49.0 / 综合 49.3
#                  大型 49.5 / 中型 49.7 / 小型 47.4（均在荣枯线下）
```

> **解读口径：** PMI > 50 扩张、< 50 收缩；连续两月同向才算趋势。
> 大/中/小型企业分档能看结构分化——小型企业长期低于大型是常态，看的是**差值变化**不是绝对值。

---
