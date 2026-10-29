# tests/sections/test_registry_gate.py
"""registry.yaml 灰度配置加载降级的诊断契约 (行为测试, 零网络)。

背景: _load_disabled() 过去把"文件不存在 / PyYAML 不可用 / YAML 非法 / 读不了 / 配置
schema 不合法"五类问题**全部静默**折叠成 [] , 调用方拿到 5 个 section, 却无法知道用户
写的灰度配置其实没有生效 —— 这正是灰度开关最容易出的事故。

本文件锁定的契约:
  - registry.yaml 不存在 (当前默认配置): 继续静默, enabled_sections() 仍是原 5 项,
    不给日常跑报告制造噪声;
  - 文件存在但加载失败: 各发一条**原因可区分**的 UserWarning, 且一律仍返回 [],
    绝不抛异常打断报告;
  - disabled_sections 必须是 list[str]: 标量 / 映射 / null / 列表里混非字符串, 各发
    一条可行动告警 (说清读到了什么 + 该怎么写), 一律按 [] 处理 —— **一个 section 都不
    禁用**, 与其余降级路径同等待遇;
  - 告警的 stacklevel 必须指向 enabled_sections() 的**外部**调用行 (filename 与 lineno
    都验), 而不是退到本模块内部某一固定行;
  - 任何降级都不改变 section 集合与顺序。

关于假 yaml 模块: 本仓库 venv 未安装 PyYAML, 第三方 YAML 解析器也不是本项目代码。
凡是需要"yaml 可用"的用例, 都往 sys.modules 塞一个假模块驱动 —— 被测的是本模块
的分支选择、降级返回值与告警文案, 而不是 yaml 库自身的行为。"PyYAML 真的缺失"
那条路径另有用例 (sys.modules["yaml"] = None) 单独覆盖。
"""
from __future__ import annotations

import inspect
import os
import sys
import types
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis"))

import sections  # noqa: E402  # 与 tests/sections/test_base.py 同样靠 sys.path 引导

# 5 个 section 的 label 与顺序 (sort_order 40/50/55/60/65) —— 不得被本轮改动影响
ALL_LABELS = ["irm", "holders", "dividend", "board", "dragon_market"]

# 一份合法的 registry.yaml 内容
VALID_YAML = "disabled_sections:\n  - board\n"


class StubYAMLError(Exception):
    """假 PyYAML 的解析错误类型, 仅用于驱动本模块的解析失败分支"""


def _labels() -> list:
    return [s.label for s in sections.enabled_sections()]


def _registry_diagnostics(recorded) -> list:
    """从捕获到的告警里, 挑出本模块发出的 registry.yaml 诊断文案"""
    return [str(item.message) for item in recorded if "registry.yaml" in str(item.message)]


def _capture(fn):
    """在 always 过滤器下跑 fn, 返回 (返回值, 本模块的 registry 诊断列表)"""
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        value = fn()
    return value, _registry_diagnostics(recorded)


def _assert_single_diagnostic(diagnostics, path: Path) -> str:
    """断言恰好一条诊断, 且文案能定位到具体文件; 返回该文案"""
    assert len(diagnostics) == 1, f"应恰好一条诊断, 实际: {diagnostics}"
    message = diagnostics[0]
    assert str(path) in message, f"诊断应带 registry 文件路径, 实际: {message}"
    return message


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch) -> Path:
    """把真实 _REGISTRY_PATH 重定向到 tmp_path, 测试绝不碰仓库真实配置"""
    path = tmp_path / "registry.yaml"
    monkeypatch.setattr(sections, "_REGISTRY_PATH", str(path))
    return path


@pytest.fixture
def no_pyyaml(monkeypatch) -> None:
    """让 `import yaml` 必然失败, 且不依赖运行环境是否真的装了 PyYAML。

    sys.modules 里显式放 None 时, import 会直接抛 ImportError。
    """
    monkeypatch.setitem(sys.modules, "yaml", None)


@pytest.fixture
def install_yaml_stub(monkeypatch):
    """装一个可控的假 yaml 模块, 让"yaml 可用"的用例不依赖环境。

    传 safe_load 可实现; 不传则用一个恒返回 {} 的桩。
    """
    def _install(safe_load=lambda _raw: {}):
        module = types.ModuleType("yaml")
        module.YAMLError = StubYAMLError
        module.safe_load = safe_load
        monkeypatch.setitem(sys.modules, "yaml", module)
        return module

    return _install


# ============================================================
# 默认路径: 文件不存在 = 静默
# ============================================================
def test_missing_registry_file_stays_silent_and_keeps_all_sections():
    """当前默认配置: 仓库尚未落 registry.yaml, 无任何告警, 且 5 个 section 全开"""
    real_path = Path(sections._REGISTRY_PATH)
    if real_path.exists():
        pytest.skip(
            f"仓库已落 registry.yaml ({real_path}), 默认配置已变, 需 owner 同步更新本契约"
        )

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        disabled = sections._load_disabled()
        labels = _labels()

    assert disabled == []
    assert _registry_diagnostics(recorded) == []
    assert labels == ALL_LABELS


def test_missing_registry_file_on_tmp_path_is_also_silent(isolated_registry):
    """指向不存在的路径时同样静默 —— 缺席不是错误, 没有诊断就没有噪声"""
    assert not isolated_registry.exists()

    disabled, diagnostics = _capture(sections._load_disabled)

    assert disabled == []
    assert diagnostics == []


# ============================================================
# 诊断路径 1: 文件存在但 PyYAML 不可用
# ============================================================
def test_missing_pyyaml_warns_distinctly_and_keeps_all_sections(isolated_registry, no_pyyaml):
    """registry.yaml 存在但 PyYAML 缺失 -> 报 PyYAML 原因, 仍返回 [] 且 5 项全开

    这正是本仓库 venv 的现状 (未装 PyYAML): 一旦 owner 落 registry.yaml, 报告每次
    加载都会看到这条诊断, 而不是无声地全开 5 个 section。
    """
    isolated_registry.write_text(VALID_YAML, encoding="utf-8")

    disabled, diagnostics = _capture(sections._load_disabled)
    labels, label_diagnostics = _capture(_labels)

    assert disabled == []
    message = _assert_single_diagnostic(diagnostics, isolated_registry)
    assert "PyYAML" in message
    # 原因必须可区分: 不能被误报成"读不了"或"解析不了"
    assert "不可读" not in message
    assert "解析失败" not in message
    # 消费者路径 (enabled_sections) 同样拿到可定位的诊断, 且原因一致
    labels_message = _assert_single_diagnostic(label_diagnostics, isolated_registry)
    assert "PyYAML" in labels_message
    assert labels == ALL_LABELS


# ============================================================
# 诊断路径 2: 文件存在但不可读
# ============================================================
def test_unreadable_registry_path_warns_distinctly_and_keeps_all_sections(
    isolated_registry, install_yaml_stub
):
    """registry.yaml 位置是个目录 -> open 抛 IsADirectoryError, 报"不可读"而非解析失败

    必须先装 yaml 桩: 本仓库 venv 没装 PyYAML, 否则会先命中"PyYAML 不可用"分支,
    永远到不了要验的读文件分支。yaml 是否可用与读文件是否成功正交。
    """
    isolated_registry.mkdir()
    assert isolated_registry.exists()
    install_yaml_stub()

    disabled, diagnostics = _capture(sections._load_disabled)
    labels, _ = _capture(_labels)

    assert disabled == []
    message = _assert_single_diagnostic(diagnostics, isolated_registry)
    assert "不可读" in message
    assert "PyYAML" not in message
    assert "解析失败" not in message
    assert labels == ALL_LABELS


def test_permission_denied_registry_file_warns_and_keeps_all_sections(
    isolated_registry, install_yaml_stub
):
    """真实存在的文件但权限被收走 -> 报"不可读", 降级后仍返回 []"""
    isolated_registry.write_text(VALID_YAML, encoding="utf-8")
    install_yaml_stub()
    isolated_registry.chmod(0o000)
    if os.access(isolated_registry, os.R_OK):
        isolated_registry.chmod(0o600)
        pytest.skip("当前进程仍可读该文件 (如 root), 权限位不是有效屏障")

    try:
        disabled, diagnostics = _capture(sections._load_disabled)

        assert disabled == []
        message = _assert_single_diagnostic(diagnostics, isolated_registry)
        assert "不可读" in message
        assert "PyYAML" not in message
        assert "解析失败" not in message
    finally:
        isolated_registry.chmod(0o600)  # 复原, 便于 tmp_path 清理


# ============================================================
# 诊断路径 3: 文件存在但 YAML 非法
# ============================================================
def test_invalid_yaml_warns_distinctly_and_keeps_all_sections(
    isolated_registry, install_yaml_stub
):
    """YAML 语法非法 -> 报"解析失败", 并把底层异常细节带出来, 降级后仍返回 []"""
    isolated_registry.write_text("disabled_sections: [board\n", encoding="utf-8")

    def _boom(_raw):
        raise StubYAMLError("mapping values are not allowed here")

    install_yaml_stub(_boom)

    disabled, diagnostics = _capture(sections._load_disabled)
    labels, _ = _capture(_labels)

    assert disabled == []
    message = _assert_single_diagnostic(diagnostics, isolated_registry)
    assert "解析失败" in message
    # 底层异常细节必须透出, 这才是可行动的部分
    assert "mapping values are not allowed here" in message
    assert "不可读" not in message
    assert "PyYAML" not in message
    assert labels == ALL_LABELS


# ============================================================
# 诊断路径 4: YAML 合法但顶层不是映射
# ============================================================
def test_non_mapping_yaml_warns_distinctly_and_keeps_all_sections(
    isolated_registry, install_yaml_stub
):
    """顶层是列表而非 key: value -> 报"不是映射", 既不崩也不静默"""
    isolated_registry.write_text("- irm\n- board\n", encoding="utf-8")
    install_yaml_stub(lambda _raw: ["irm", "board"])

    disabled, diagnostics = _capture(sections._load_disabled)
    labels, _ = _capture(_labels)

    assert disabled == []
    message = _assert_single_diagnostic(diagnostics, isolated_registry)
    assert "不是 key: value 映射" in message
    assert labels == ALL_LABELS


# ============================================================
# 正常路径: 有效配置不得告警, 且开关行为不变
# ============================================================
def test_valid_registry_config_filters_section_without_warning(
    isolated_registry, install_yaml_stub
):
    """有效配置 -> 无告警, board 被关掉, 其余 4 项顺序不变"""
    isolated_registry.write_text(VALID_YAML, encoding="utf-8")
    seen = {}

    def _safe_load(raw):
        seen["raw"] = raw
        return {"disabled_sections": ["board"]}

    install_yaml_stub(_safe_load)

    disabled, diagnostics = _capture(sections._load_disabled)
    labels, label_diagnostics = _capture(_labels)

    # 确实把我们读到的文件内容交给了 yaml 去解析
    assert seen["raw"] == VALID_YAML
    assert disabled == ["board"]
    assert diagnostics == []
    assert label_diagnostics == []
    assert labels == ["irm", "holders", "dividend", "dragon_market"]


def test_empty_registry_document_keeps_all_sections_without_warning(
    isolated_registry, install_yaml_stub
):
    """空文档 (safe_load 返回 None) -> 走 `or {}` 兜底, 不告警, 5 项全开"""
    isolated_registry.write_text("# 灰度配置占位\n", encoding="utf-8")
    install_yaml_stub(lambda _raw: None)

    disabled, diagnostics = _capture(sections._load_disabled)
    labels, label_diagnostics = _capture(_labels)

    assert disabled == []
    assert diagnostics == []
    assert label_diagnostics == []
    assert labels == ALL_LABELS


def test_registry_without_disabled_key_keeps_all_sections(isolated_registry, install_yaml_stub):
    """只有其它键的配置 -> disabled_sections 缺省为 [], 不告警, 开关行为不变"""
    isolated_registry.write_text("owner: pending\n", encoding="utf-8")
    install_yaml_stub(lambda _raw: {"owner": "pending"})

    disabled, diagnostics = _capture(sections._load_disabled)
    labels, _ = _capture(_labels)

    assert disabled == []
    assert diagnostics == []
    assert labels == ALL_LABELS


# ============================================================
# 诊断路径 5: YAML 合法, 但 disabled_sections 不符合 list[str] schema
# ============================================================
# 四种非法写法各自驱动一个用例: 标量 / 映射 / 显式 null / 列表里混非字符串。
# 共同后果 = 一条可行动告警 + 一个 section 都不禁用。
#
# 标量那条是本轮的核心回归点: 旧实现 set("board") 得到字符集合
# {'b','o','a','r','d'}, 不匹配任何 label, 于是既没告警也没关掉任何 section ——
# 用户以为灰度已生效, 报告里 5 项照旧全出。标量必须与"真正生效的列表"同等待遇。
BAD_SCHEMA_CASES = [
    pytest.param(
        "disabled_sections: board\n", "board", "str 标量", id="scalar-string"
    ),
    pytest.param(
        "disabled_sections:\n  board: true\n", {"board": True}, "dict 映射", id="mapping"
    ),
    pytest.param(
        "disabled_sections: null\n", None, "None", id="null"
    ),
    pytest.param(
        "disabled_sections:\n  - board\n  - 3\n", ["board", 3], "非字符串元素",
        id="list-with-non-string",
    ),
]


@pytest.mark.parametrize("raw_yaml, stub_value, detail_marker", BAD_SCHEMA_CASES)
def test_invalid_disabled_schema_warns_and_disables_nothing(
    isolated_registry, install_yaml_stub, raw_yaml, stub_value, detail_marker
):
    """disabled_sections 不是 list[str] -> 一条可行动告警, 且**一个 section 都不关**"""
    isolated_registry.write_text(raw_yaml, encoding="utf-8")
    install_yaml_stub(lambda _raw: {"disabled_sections": stub_value})

    disabled, diagnostics = _capture(sections._load_disabled)

    assert disabled == [], "非法 schema 必须按 [] 处理, 不得部分生效"
    message = _assert_single_diagnostic(diagnostics, isolated_registry)
    # 说清"哪错了"与"该怎么改", 两半同框出现才叫可行动
    assert "不是字符串列表" in message
    assert detail_marker in message
    assert "disabled_sections: [board, irm]" in message
    # 原因必须与既有四条降级路径可区分, 不能被误报成读/解析/PyYAML 问题
    assert "PyYAML" not in message
    assert "不可读" not in message
    assert "解析失败" not in message
    assert "不是 key: value 映射" not in message

    # 消费者路径同样拿到诊断, 且 5 项顺序不变
    labels, label_diagnostics = _capture(_labels)
    _assert_single_diagnostic(label_diagnostics, isolated_registry)
    assert labels == ALL_LABELS


def test_valid_list_with_unknown_label_disables_nothing_without_warning(
    isolated_registry, install_yaml_stub
):
    """合法但未知的 label: 维持旧行为 (不匹配任何 section, 也不告警), 本轮不加新行为

    本轮只补 list[str] schema 校验。未知 label 的去重/提示属**新增**行为, 明确不做。
    """
    isolated_registry.write_text("disabled_sections:\n  - not_a_section\n", encoding="utf-8")
    install_yaml_stub(lambda _raw: {"disabled_sections": ["not_a_section"]})

    disabled, diagnostics = _capture(sections._load_disabled)
    labels, label_diagnostics = _capture(_labels)

    assert disabled == ["not_a_section"]
    assert diagnostics == []
    assert label_diagnostics == []
    assert labels == ALL_LABELS


def test_empty_disabled_list_keeps_all_sections_without_warning(
    isolated_registry, install_yaml_stub
):
    """显式写空列表是合法配置 (等于不关任何 section) -> 静默, 不告警"""
    isolated_registry.write_text("disabled_sections: []\n", encoding="utf-8")
    install_yaml_stub(lambda _raw: {"disabled_sections": []})

    disabled, diagnostics = _capture(sections._load_disabled)
    labels, label_diagnostics = _capture(_labels)

    assert disabled == []
    assert diagnostics == []
    assert label_diagnostics == []
    assert labels == ALL_LABELS


# ============================================================
# 告警定位: stacklevel 必须指向 enabled_sections() 的外部调用行
# ============================================================
def test_registry_warning_is_attributed_to_the_enabled_sections_caller(
    isolated_registry, install_yaml_stub
):
    """告警要落在 enabled_sections() 的**外部**调用行, 而不是本模块内部某固定行

    栈底往上数: 1=_warn_registry_load, 2=_load_disabled, 3=enabled_sections,
    4=消费者。此前注释声称"指向 enabled_sections() 的调用点"而 stacklevel 写的是 3,
    实际只退到 enabled_sections() 内部, 任何消费方出错都指向同一行。

    因此这里必须在测试文件里**直接**调 enabled_sections() 并断言 filename + lineno;
    只测 helper 的话, 帧数对不上, stacklevel 写错也测不出来。
    """
    isolated_registry.write_text("disabled_sections: board\n", encoding="utf-8")
    install_yaml_stub(lambda _raw: {"disabled_sections": "board"})

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        call_line = inspect.currentframe().f_lineno + 1
        labels = [s.label for s in sections.enabled_sections()]

    _assert_single_diagnostic(_registry_diagnostics(recorded), isolated_registry)
    assert labels == ALL_LABELS

    item = next(w for w in recorded if "registry.yaml" in str(w.message))
    # 归到调用方所在文件, 而不是 analysis/sections/ 包内
    assert Path(item.filename).resolve() == Path(__file__).resolve()
    # 归到调用语句那一行, 不是 enabled_sections() 内部的某一行
    assert item.lineno == call_line
