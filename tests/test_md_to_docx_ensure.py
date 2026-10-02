"""_ensure() OOXML 顺序插入的降级边界测试（Task p2-3）。

背景：_ensure 曾经 `except Exception: parent.append(el)`，把任何编程/运行时缺陷
一并吞掉。这里锁定三条路径：

  1. 正常插入      —— insert_element_before 生效，元素落在 succ 之前（顺序正确）
  2. 预期降级      —— 标签/命名空间与 python-docx 契约不兼容时退化为 append
  3. 意外异常      —— RuntimeError 必须向上抛，不能被 _ensure 静默吞掉

测试不读 reports/ 历史产物，全部基于内存构造的 OxmlElement，deterministic。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from docx.oxml import OxmlElement

# 直接按文件路径加载 analysis/md_to_docx.py，避免依赖 sys.path 注入顺序
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "md_to_docx_under_test", _REPO_ROOT / "analysis" / "md_to_docx.py"
)
md_to_docx = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(md_to_docx)
_ensure = md_to_docx._ensure


def _tags(parent) -> list[str]:
    """子元素本地名顺序（去掉 {ns} 前缀），用于断言实际排布"""
    return [child.tag.split("}")[-1] for child in parent]


# ============================================================
# 1. 正常插入路径：顺序正确，不走 fallback
# ============================================================
def test_ensure_inserts_before_first_matching_successor():
    """succ 命中时元素插到后继之前，且不动其他子元素"""
    pPr = OxmlElement("w:pPr")
    pPr.append(OxmlElement("w:spacing"))
    pPr.append(OxmlElement("w:jc"))

    el = _ensure(pPr, "w:ind", ("w:spacing", "w:jc", "w:rPr"))

    assert el.getparent() is pPr
    assert _tags(pPr) == ["ind", "spacing", "jc"]


def test_ensure_appends_when_no_successor_present():
    """无后继命中时 insert_element_before 自身即 append，不抛异常、不重复插"""
    pPr = OxmlElement("w:pPr")
    pPr.append(OxmlElement("w:spacing"))

    _ensure(pPr, "w:ind", ("w:jc", "w:rPr"))

    assert _tags(pPr) == ["spacing", "ind"]


def test_ensure_preserves_order_for_repeated_insertions():
    """连续多次插入各自落到正确位置，顺序不串"""
    pPr = OxmlElement("w:pPr")
    pPr.append(OxmlElement("w:spacing"))
    pPr.append(OxmlElement("w:jc"))

    _ensure(pPr, "w:ind", ("w:jc",))
    _ensure(pPr, "w:shd", ("w:tabs", "w:spacing", "w:ind"))
    _ensure(pPr, "w:keepNext", ("w:spacing",))

    assert _tags(pPr) == ["shd", "keepNext", "spacing", "ind", "jc"]


# ============================================================
# 2. 预期降级路径：仅契约不兼容才 append
# ============================================================
def test_ensure_falls_back_to_append_on_unknown_namespace_prefix():
    """qn() 遇到 nsmap 未登记前缀 -> KeyError（文档化的不兼容），退化为 append"""
    pPr = OxmlElement("w:pPr")
    pPr.append(OxmlElement("w:spacing"))

    el = _ensure(pPr, "w:ind", ("zz:spacing",))

    assert el.getparent() is pPr
    assert _tags(pPr) == ["spacing", "ind"]


def test_ensure_falls_back_to_append_on_malformed_successor_tag():
    """succ 缺少 "pfx:local" 形式 -> ValueError（文档化的不兼容），退化为 append"""
    pPr = OxmlElement("w:pPr")
    pPr.append(OxmlElement("w:spacing"))

    el = _ensure(pPr, "w:ind", ("spacing",))

    assert el.getparent() is pPr
    assert _tags(pPr) == ["spacing", "ind"]


# ============================================================
# 3. 意外异常路径：真实缺陷必须冒泡
# ============================================================
def test_ensure_propagates_unexpected_runtime_error():
    """insert_element_before 抛 RuntimeError 属编程/运行时缺陷，必须向上抛"""
    pPr = OxmlElement("w:pPr")
    pPr.append(OxmlElement("w:spacing"))

    def boom(_elm, *_tagnames):
        raise RuntimeError("insertion backend exploded")

    pPr.insert_element_before = boom

    with pytest.raises(RuntimeError, match="insertion backend exploded"):
        _ensure(pPr, "w:ind", ("w:spacing",))

    # 异常路径不得留下半插入的子元素
    assert _tags(pPr) == ["spacing"]


def test_ensure_does_not_swallow_attribute_error():
    """AttributeError 同样不属于契约不兼容，必须冒泡而非 append"""
    pPr = OxmlElement("w:pPr")
    pPr.append(OxmlElement("w:spacing"))

    def boom(_elm, *_tagnames):
        raise AttributeError("no such method")

    pPr.insert_element_before = boom

    with pytest.raises(AttributeError, match="no such method"):
        _ensure(pPr, "w:ind", ("w:spacing",))

    assert _tags(pPr) == ["spacing"]


# ============================================================
# 4. 白名单本身的契约：不得退化为 bare except Exception
# ============================================================
def test_insert_incompatible_allowlist_is_explicit():
    """降级白名单只含 KeyError/ValueError，不能悄悄扩成 Exception"""
    assert md_to_docx._INSERT_INCOMPATIBLE == (KeyError, ValueError)
    assert not issubclass(Exception, md_to_docx._INSERT_INCOMPATIBLE)
