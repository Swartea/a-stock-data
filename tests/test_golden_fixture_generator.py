"""D1 回归: golden 生成器的"已存在基线不得被静默改写"约束

独立验收复现的缺陷: 旧 main() 只**打印** capture 源 DRIFT, 却照样把裁剪结果
写进已存在的 golden 并 return 0 —— 也就是说一份来路不明 / 与基线不符的产物
可以静默覆盖已版本化的 fixture。

本测试的硬约束: **绝不能改动仓库内的 fixture**。做法是把 `golden_fixtures.py`
复制到 tmp_path 下的同构目录里再 import 副本, 于是副本的
GOLDEN_DIR / WORKDIR / SOURCE_600693 全部指向临时区, 物理上够不到项目文件。
capture 源用最小 `{}` 占位 (只为让 sha 校验通过, 不含任何行情数据)。

退出码契约: 0 = 写盘成功/最新; 1 = capture 源漂移或缺失 (写盘前失败);
2 = 已存在基线漂移 (不写盘); --force 才允许覆盖。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict

import pytest

PROJECT_GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"
GENERATOR_SRC = PROJECT_GOLDEN_DIR / "golden_fixtures.py"
PROJECT_GOLDENS = ("result_v3-600693-20261003.json", "result_v3-002353-20260912.json")

# 模块导入时给项目内 fixture 拍快照, 每个测试结束前复核 —— 证明本文件
# 无论如何都不可能改到项目 fixture。
_PROJECT_SNAPSHOT: Dict[str, str] = {
    name: hashlib.sha256((PROJECT_GOLDEN_DIR / name).read_bytes()).hexdigest()
    for name in PROJECT_GOLDENS
    if (PROJECT_GOLDEN_DIR / name).exists()
}


def _assert_project_fixtures_untouched() -> None:
    for name, before in _PROJECT_SNAPSHOT.items():
        p = PROJECT_GOLDEN_DIR / name
        assert p.exists(), f"项目 fixture 被删除了: {p}"
        now = hashlib.sha256(p.read_bytes()).hexdigest()
        assert now == before, f"本测试改动了项目 fixture: {p}"


def _load_isolated_generator(root: Path) -> ModuleType:
    """把生成器复制到 root/analysis/tests/fixtures/golden/ 并 import 该副本。"""
    gen_dir = root / "analysis" / "tests" / "fixtures" / "golden"
    gen_dir.mkdir(parents=True, exist_ok=True)
    gen_path = gen_dir / "golden_fixtures.py"
    gen_path.write_text(GENERATOR_SRC.read_text(encoding="utf-8"), encoding="utf-8")

    # 最小 capture 源: 空 JSON, 不含任何行情数据, 只为让 sha 校验有对象可比。
    src = root / "reports" / "600693_东百集团" / "2026-10-03" / "result_v3-1618.json"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("{}\n", encoding="utf-8")

    spec = importlib.util.spec_from_file_location("golden_fixtures_isolated", gen_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    # 把副本的 capture 源指向临时区, 并把指纹对齐到那个最小占位文件。
    mod.SOURCE_600693 = src
    mod.SOURCE_600693_SHA256 = hashlib.sha256(src.read_bytes()).hexdigest()
    return mod


@pytest.fixture
def isolated(tmp_path: Path):
    """隔离副本: 目录布局与仓库同构, 因此 WORKDIR/golden_path 都能正确推导。"""
    mod = _load_isolated_generator(tmp_path)
    yield mod
    _assert_project_fixtures_untouched()


def _goldens(mod: ModuleType) -> Dict[str, Path]:
    return {name: mod.GOLDEN_DIR / name for name in PROJECT_GOLDENS}


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_initial_creation_is_allowed_and_exits_zero(isolated, capsys):
    """目标文件不存在 = 初始创建, 允许写盘并 return 0。"""
    assert not any(p.exists() for p in _goldens(isolated).values())

    assert isolated.main([]) == 0

    for p in _goldens(isolated).values():
        assert p.exists(), f"初始创建未落盘: {p}"
        json.loads(_read(p))  # 必须是合法 JSON
    capsys.readouterr()


def test_unchanged_regeneration_is_a_noop(isolated, capsys):
    """已存在基线且内容一致 = no-op, return 0 且字节不变。"""
    assert isolated.main([]) == 0
    before = {n: _read(p) for n, p in _goldens(isolated).items()}

    assert isolated.main([]) == 0
    capsys.readouterr()

    for n, p in _goldens(isolated).items():
        assert _read(p) == before[n], f"no-op 却被改写: {p}"


def test_existing_baseline_drift_fails_nonzero_without_writing(isolated, capsys):
    """D1 核心: 改掉已存在基线后重跑, 必须非零退出且**不写盘**。

    复现独立验收的原始缺陷: 旧实现会重新生成并覆盖, 然后 return 0。
    """
    assert isolated.main([]) == 0
    target = _goldens(isolated)["result_v3-600693-20261003.json"]
    baseline = _read(target)

    # 篡改已存在基线 (与验收复现一致: 动 quote.price / support)
    d = json.loads(baseline)
    d["quote"] = {"price": 999.99}
    d["three_levels"] = {"support": 888.88}
    target.write_text(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    tampered = _read(target)
    assert tampered != baseline

    rc = isolated.main([])
    err = capsys.readouterr().err

    assert rc != 0, "已存在基线漂移必须非零退出"
    assert rc == 2, f"漂移应返回 2 (与 capture 源漂移的 1 区分), 实际 {rc}"
    assert _read(target) == tampered, "基线漂移时不得改写文件"
    assert "拒绝覆盖" in err


def test_capture_source_drift_fails_nonzero_before_any_write(isolated, capsys):
    """capture 源漂移必须在任何写盘之前失败, return 1。"""
    isolated.SOURCE_600693.write_text('{"tampered": true}\n', encoding="utf-8")
    assert isolated.main([]) is not None

    rc = isolated.main([])
    err = capsys.readouterr().err

    assert rc == 1, f"capture 源漂移应返回 1, 实际 {rc}"
    assert "sha256 漂移" in err
    for p in _goldens(isolated).values():
        assert not p.exists(), f"capture 源漂移时不得创建文件: {p}"


def test_missing_capture_source_fails_nonzero(isolated, capsys):
    """capture 源缺失 = fail loud, 不静默造数据。"""
    isolated.SOURCE_600693.unlink()

    rc = isolated.main([])
    err = capsys.readouterr().err

    assert rc == 1, f"capture 源缺失应返回 1, 实际 {rc}"
    assert "capture 源不存在" in err
    for p in _goldens(isolated).values():
        assert not p.exists(), f"capture 源缺失时不得创建文件: {p}"


def test_force_is_the_explicit_escape_hatch(isolated, capsys):
    """--force 显式允许覆盖 —— 这是"更新基线"的唯一受支持路径。"""
    assert isolated.main([]) == 0
    target = _goldens(isolated)["result_v3-600693-20261003.json"]
    baseline = _read(target)

    d = json.loads(baseline)
    d["quote"] = {"price": 999.99}
    target.write_text(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    tampered = _read(target)

    assert isolated.main([]) == 2, "无 --force 仍应拒绝"
    assert _read(target) == tampered

    assert isolated.main(["--force"]) == 0
    capsys.readouterr()
    assert _read(target) == baseline, "--force 应把基线还原成生成结果"


def test_generator_output_is_byte_stable(isolated, capsys):
    """同输入两次生成必须字节一致 (可复现性的基础)。"""
    assert isolated.main(["--force"]) == 0
    first = {n: _read(p) for n, p in _goldens(isolated).items()}
    assert isolated.main(["--force"]) == 0
    capsys.readouterr()
    for n, p in _goldens(isolated).items():
        assert _read(p) == first[n], f"两次生成不一致: {p}"


def test_isolated_copy_cannot_reach_project_fixtures(isolated):
    """副本的写盘目标必须在临时区, 与项目 fixture 物理隔离。"""
    assert isolated.GOLDEN_DIR != PROJECT_GOLDEN_DIR
    assert not str(isolated.GOLDEN_DIR).startswith(str(PROJECT_GOLDEN_DIR))
    for p in _goldens(isolated).values():
        assert str(p).startswith(str(isolated.GOLDEN_DIR))
        assert str(p) != str(PROJECT_GOLDEN_DIR / p.name)
    _assert_project_fixtures_untouched()


def test_frozen_fetched_at_constant_is_gone():
    """D3: 未被引用的 FROZEN_FETCHED_AT 必须移除, 不留误导性注释。"""
    src = GENERATOR_SRC.read_text(encoding="utf-8")
    assert "FROZEN_FETCHED_AT" not in src
    # 诚实边界必须写清楚: 渲染出的 Markdown 仍含活墙钟页脚。
    assert "report_md.py:313" in src
    assert "report_md.py:346" in src


def test_002353_score_citation_points_at_current_lines():
    """D2: 002353 10 因子原值出处行号必须是当前的 117-119。"""
    target = Path(__file__).resolve().parent / "test_scoring_breakdown.py"
    lines = target.read_text(encoding="utf-8").splitlines()
    # 117-119 必须是 002353 那一段 (起始行 + 续行 + 带 "# 002353" 的结束行)
    assert '"trend": 8, "valuation": 10' in lines[116], lines[116]
    assert lines[118].rstrip().endswith("# 002353"), lines[118]

    for doc in (PROJECT_GOLDEN_DIR / "README.md", GENERATOR_SRC):
        text = doc.read_text(encoding="utf-8")
        assert "test_scoring_breakdown.py:117-119" in text, f"{doc} 未更新引用"
        assert "test_scoring_breakdown.py:106-108" not in text, f"{doc} 仍留旧引用"
        assert "test_scoring_breakdown.py:107-108" not in text, f"{doc} 仍留旧引用"


def test_generator_source_has_no_unused_frozen_symbols():
    """守卫: 生成器里不得再出现其它未引用的 FROZEN_* 常量。"""
    import re
    src = GENERATOR_SRC.read_text(encoding="utf-8")
    for name in set(re.findall(r"^FROZEN_[A-Z_]+", src, flags=re.MULTILINE)):
        uses = len(re.findall(rf"\b{name}\b", src))
        assert uses == 1, f"{name} 已定义但未被使用 (定义处 1 次, 实际 {uses} 次)"
