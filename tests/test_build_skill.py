"""构建脚本 scripts/build_skill.py 的单元测试 + 仓库级同步守卫。

覆盖：幂等性、拼接顺序与换行规范化、--check 正/负用例、缺失源文件报错，
以及「仓库内 SKILL.md 与 skill-src/ 严格同步」的等价守卫（CI 兜底）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load_build_skill():
    """按路径加载 scripts/build_skill.py（scripts/ 不是包，不走常规 import）。"""
    spec = importlib.util.spec_from_file_location("build_skill", _SCRIPTS_DIR / "build_skill.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_skill = _load_build_skill()


@pytest.fixture
def src_dir(tmp_path: Path) -> Path:
    """包含两个源文件的临时 skill-src/ 目录。"""
    d = tmp_path / "skill-src"
    d.mkdir()
    (d / "01-b.md").write_text("# B\n\nb 内容\n\n\n", encoding="utf-8")
    (d / "00-a.md").write_text("# A\n\na 内容\n", encoding="utf-8")
    return d


# ============================================================
# 拼合规则
# ============================================================


def test_build_orders_parts_by_filename(src_dir: Path) -> None:
    """源文件按文件名字典序拼接，与写入先后无关。"""
    content = build_skill.build(src_dir)
    assert content.index("# A") < content.index("# B")


def test_build_normalizes_trailing_newlines(src_dir: Path) -> None:
    """每个源文件末尾多余换行被规范化，文件之间恰好一个空行。"""
    content = build_skill.build(src_dir)
    assert "a 内容\n\n# B" in content
    assert "b 内容\n" in content
    assert "b 内容\n\n" not in content


def test_build_prepends_generated_header(src_dir: Path) -> None:
    """产物顶部有「请勿直接编辑」的生成注释，且注释后紧跟源内容。"""
    content = build_skill.build(src_dir)
    header, body = content.split("\n\n", 1)
    assert header.startswith("<!--") and "skill-src" in header
    assert body.startswith("# A")


def test_build_is_idempotent(src_dir: Path, tmp_path: Path) -> None:
    """连续构建两次输出逐字节一致。"""
    out = tmp_path / "SKILL.md"
    assert build_skill.main(["--src", str(src_dir), "--out", str(out)]) == 0
    first = out.read_bytes()
    assert build_skill.main(["--src", str(src_dir), "--out", str(out)]) == 0
    assert out.read_bytes() == first


# ============================================================
# --check 模式
# ============================================================


def test_check_passes_when_in_sync(src_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "SKILL.md"
    build_skill.main(["--src", str(src_dir), "--out", str(out)])
    assert build_skill.main(["--src", str(src_dir), "--out", str(out), "--check"]) == 0


def test_check_fails_on_drift(src_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "SKILL.md"
    build_skill.main(["--src", str(src_dir), "--out", str(out)])
    with out.open("a", encoding="utf-8") as fh:
        fh.write("人为漂移")
    assert build_skill.main(["--src", str(src_dir), "--out", str(out), "--check"]) == 1


def test_check_fails_when_output_missing(src_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "SKILL.md"
    assert build_skill.main(["--src", str(src_dir), "--out", str(out), "--check"]) == 1


# ============================================================
# 缺失源文件报错
# ============================================================


def test_missing_src_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(build_skill.BuildSkillError):
        build_skill.build(tmp_path / "不存在")


def test_empty_src_dir_raises(tmp_path: Path) -> None:
    d = tmp_path / "skill-src"
    d.mkdir()
    with pytest.raises(build_skill.BuildSkillError):
        build_skill.build(d)


def test_missing_src_dir_exit_code(tmp_path: Path) -> None:
    """CLI 下源目录缺失返回非零（2），不静默成功。"""
    assert (
        build_skill.main(["--src", str(tmp_path / "不存在"), "--out", str(tmp_path / "SKILL.md")])
        == 2
    )


# ============================================================
# 仓库级等价守卫：committed SKILL.md 必须与 skill-src/ 同步
# ============================================================


def test_repo_skill_md_in_sync(workdir) -> None:
    """仓库内 SKILL.md = 生成头 + skill-src/ 拼合结果，逐字节一致。

    防止有人绕过构建脚本直接改 SKILL.md（CI 上 pytest 与 --check 双保险）。
    """
    content = build_skill.build(workdir / "skill-src")
    header, body = content.split("\n\n", 1)
    current = (workdir / "SKILL.md").read_text(encoding="utf-8")
    assert current.startswith(header + "\n\n")
    assert current[len(header) + 2 :] == body
