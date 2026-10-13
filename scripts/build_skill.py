#!/usr/bin/env python3
"""构建根目录 SKILL.md：按文件名顺序拼合 skill-src/ 下的分层源文件。

维护入口是 skill-src/（一层一个文件），SKILL.md 是构建产物，两者内容严格一致：

    python scripts/build_skill.py           # 重新生成 SKILL.md
    python scripts/build_skill.py --check   # CI 用：验证 SKILL.md 与 skill-src/ 同步

拼接规则（保证幂等，连续两次构建逐字节一致）：

- 源文件按文件名字典序排序；
- 每个源文件去掉末尾多余换行后保留恰好一个换行；
- 源文件之间用一个空行连接；
- 产物顶部附加一行「本文件由构建生成」的 HTML 注释（唯一的允许差异点）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

GENERATED_HEADER = (
    "<!-- 本文件由 skill-src/ 构建生成，请勿直接编辑；"
    "修改请编辑 skill-src/ 后运行 python scripts/build_skill.py -->"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC_DIR = REPO_ROOT / "skill-src"
DEFAULT_OUT_PATH = REPO_ROOT / "SKILL.md"


class BuildSkillError(Exception):
    """skill-src/ 缺失或为空等构建前置错误。"""


def load_parts(src_dir: Path) -> list[str]:
    """读取 src_dir 下全部 .md 源文件，返回按文件名排序的规范化内容列表。

    规范化 = 去掉文件末尾多余换行、保留恰好一个换行。
    """
    if not src_dir.is_dir():
        raise BuildSkillError(f"源目录不存在: {src_dir}")
    files = sorted(src_dir.glob("*.md"))
    if not files:
        raise BuildSkillError(f"源目录中没有 .md 文件: {src_dir}")
    return [path.read_text(encoding="utf-8").rstrip("\n") + "\n" for path in files]


def build(src_dir: Path) -> str:
    """拼合 src_dir 下全部源文件，返回 SKILL.md 完整内容。"""
    parts = load_parts(src_dir)
    return GENERATED_HEADER + "\n\n" + "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    """命令行入口：默认生成，--check 只做同步校验。返回进程退出码。"""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--src",
        type=Path,
        default=DEFAULT_SRC_DIR,
        help=f"源文件目录（默认: {DEFAULT_SRC_DIR}）",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_PATH,
        help=f"产物路径（默认: {DEFAULT_OUT_PATH}）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="不写入文件，只校验 --out 与构建结果一致；不同步则非零退出",
    )
    args = parser.parse_args(argv)

    try:
        content = build(args.src)
    except BuildSkillError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.check:
        if not args.out.is_file():
            print(f"error: 产物不存在: {args.out}", file=sys.stderr)
            return 1
        current = args.out.read_text(encoding="utf-8")
        if current != content:
            diff_line = next(
                (i for i, (a, b) in enumerate(zip(current, content, strict=False), 1) if a != b),
                min(len(current), len(content)) + 1,
            )
            print(
                f"error: {args.out} 与 {args.src} 不同步"
                f"（第 {diff_line} 个字符起出现差异）；"
                f"请编辑 skill-src/ 后运行 python scripts/build_skill.py",
                file=sys.stderr,
            )
            return 1
        print(f"ok: {args.out} 与 {args.src} 同步")
        return 0

    args.out.write_text(content, encoding="utf-8")
    print(f"written: {args.out}（{len(content)} 字节，来自 {args.src}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
