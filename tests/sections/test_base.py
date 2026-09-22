import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))
from sections._base import Section

def test_section_abstract_cannot_instantiate():
    """Section 是抽象类，不能直接实例化"""
    try:
        s = Section()
        assert False, "应抛 TypeError"
    except TypeError:
        pass

def test_section_subclass_must_implement_methods():
    """子类必须实现 fetch / render_html / render_md"""
    class IncompleteSection(Section):
        label = "test"
    try:
        s = IncompleteSection()
        assert False, "应抛 TypeError"
    except TypeError:
        pass

def test_section_full_subclass_works():
    """完整子类可实例化并调方法"""
    class TestSection(Section):
        label = "test"
        title = "测试章节"
        weight = 1
        sort_order = 50
        source_ref = "§x.x"
        data_sources = ["test_endpoint"]
        def fetch(self, code, ctx):
            return {"rows": [1, 2, 3]}
        def render_html(self, result, writer):
            writer.append(f"<h2>{self.title}</h2>")
            return f"<section>{self.title}: {result.get('rows')}</section>"
        def render_md(self, result, writer):
            writer.append(f"## {self.title}")
            return f"{self.title}: {result.get('rows')}"
    s = TestSection()
    assert s.label == "test"
    assert s.fetch("600693", {})["rows"] == [1, 2, 3]
    assert "测试章节" in s.render_html({"rows": []}, [])
