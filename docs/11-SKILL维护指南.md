# SKILL 维护指南：分层源文件 + 构建脚本

> 面向维护者。使用者/分发形态不受影响——对外始终只有根目录那一个自包含的 `SKILL.md`。

## 背景

`SKILL.md` 约 218KB（54 个数据端点 + 降级策略 + FAQ），单文件维护时改任何一层都要在巨型文件里翻找，diff 不可读。产品决策已明确**不做目录化拆分分发**（见 README FAQ Q3、issue #21 / #22 / #29），因此本改造只动维护侧：

- **`skill-src/` 是人的编辑入口**：按 `SKILL.md` 现有章节结构一层一个小文件；
- **`SKILL.md` 是构建产物**：由脚本拼合生成，与源文件内容严格一致；
- **对外分发形态不变**：用户拷贝/下载的仍是单文件 `SKILL.md`。

## 目录结构

`skill-src/` 下 26 个文件，文件名前缀决定拼接顺序（`00` → `25`）：

| 文件 | 对应 SKILL.md 章节 |
|---|---|
| `00-头部.md` | frontmatter（name/description/version）+ H1 + 版本说明 |
| `01-5秒定位.md` ~ `07-prerequisites.md` | 定位区、快速命令、配套文档、端点路由速查、数据源优先级 & 东财防封、When to Activate、Prerequisites |
| `08-layer1-行情层.md` ~ `18-layer11-宏观层.md` | 十一层架构，一层一个文件 |
| `19-估值计算公式.md` ~ `22-备用源速查.md` | 估值公式、完整调研流程、数据源优先级、备用源速查 & 降级策略 |
| `23-faq.md` ~ `25-升级同步.md` | FAQ、安装说明、升级/同步 |

改某一层只需打开对应文件；内嵌 Python 代码块整体留在所属层文件内，不跨文件拆断。

## 怎么改

1. 编辑 `skill-src/` 里对应层的文件（内容改动纯在源文件进行）；
2. 重新构建：

   ```bash
   python scripts/build_skill.py
   ```

3. 提交时 `skill-src/` 的改动和重新生成的 `SKILL.md` 一起提交。

## 怎么验证

```bash
# 1. 构建产物与源文件同步（不写入，只校验；不同步则非零退出）
python scripts/build_skill.py --check

# 2. 测试（含同步守卫用例 test_repo_skill_md_in_sync）
python -m pytest tests/test_build_skill.py -q

# 3. 静态检查
ruff check scripts/build_skill.py tests/test_build_skill.py
```

CI 里有独立的 `skill-sync` job 跑 `--check`，直接改 `SKILL.md` 不更新源文件会被拦下；`tests/test_build_skill.py` 里的仓库级等价守卫是第二道保险。

## 构建规则（保证幂等）

- 源文件按文件名字典序拼接；
- 每个源文件末尾多余换行规范化为恰好一个；
- 文件之间恰好一个空行；
- 产物顶部附加一行 `<!-- 本文件由 skill-src/ 构建生成 … -->` 注释——这是产物与源文件之间**唯一**允许的差异点。

连续跑两次 `python scripts/build_skill.py` 输出逐字节一致。

## 常见误区

- **不要直接编辑根目录 `SKILL.md`**——改了会被 CI `--check` 拦下；正确入口是 `skill-src/`。
- **不要拆分/重排 `skill-src/` 文件名前缀**——拼接顺序就是文件名顺序。
- **新增端点/小节优先就地改对应层的文件**；确需新增源文件时，前缀序号要取对——拼接顺序就是文件名字典序，序号冲突或错位会导致章节顺序漂移。
