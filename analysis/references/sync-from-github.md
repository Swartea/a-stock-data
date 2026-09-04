# Sync an upstream GitHub skill repo → local Hermes skill directory

This recipe applies to **any** user request of the form "install / update / sync <github-url> into Hermes". a-stock-data is the worked example; the pattern is reusable for future skill installs (trading, monitoring, etc.).

## Reality check (do this first, before "installing")

Before you run any download command, **inspect what is already on disk**:

```python
import os
home = os.path.expanduser("~")
skill_dir = f"{home}/.hermes/skills/<category>/<skill-name>"
# List existing files; many skills already have a venv + DEPLOY_NOTES.md
# from previous deploy attempts. You're rarely installing from zero.
```

Why this matters: The a-stock-data install in 2026-09 was **V3.2.2 locally, V3.7.2 on GitHub** — 5 minor versions behind. The user's "install this" was actually "sync to latest +补 4 missing dependencies". Mistaking sync for fresh-install wastes 5+ tool calls.

## Step-by-step

### 1. Verify the repo actually exists and inspect it
- `mcp_github_get_file_contents(owner, repo, path="")` → list root files.
- `mcp_github_get_file_contents(owner, repo, path="README.md")` → confirm it's the right repo.
- Read SKILL.md on GitHub to understand the **current version + entry point**.

### 3. Diff local vs GitHub
- Local `SKILL.md` header: read `version:` field.
- Compare file sizes, mtimes, and presence of files GitHub lists.
- a-stock-data 2026-09-03 surprise: GitHub README mentioned `scripts/` and `references/` subdirectories that **didn't exist** on main (404). README was stale. Don't trust README, trust the GitHub API listing.

### 4. Sync the actual files (not the README's wishlist)
For each file that **actually exists** on GitHub (verified via API, not README):

```bash
cd ~/.hermes/skills/<category>/<skill-name>
curl -sSLo SKILL.md https://raw.githubusercontent.com/<owner>/<repo>/main/SKILL.md
curl -sSLo README.md https://raw.githubusercontent.com/<owner>/<repo>/main/README.md
# ... repeat per file
ls -la SKILL.md   # verify size > 0
head -3 SKILL.md  # verify version matches expectation
grep -m1 'version:' SKILL.md
```

### 5. Clean up placeholder / 404'd files
A common gotcha: README mentions subdirectories that don't exist. If you `curl` a 404 you get a 14-byte `"404: Not Found"` body, **not** an error exit code. **You must verify file size after download**:

```bash
for f in scripts/x.py references/y.md; do
  [ -f "$f" ] && [ $(stat -f%z "$f") -le 50 ] && rm "$f" && echo "删 404 placeholder $f"
done
```

Rule: **any downloaded file ≤ 100 bytes is suspect** — open it and check.

### 6. Update dependencies in the skill's venv
Don't `pip install` into system Python. The skill should ship its own venv:

```bash
cd ~/.hermes/skills/<category>/<skill-name>
./venv/bin/python -m pip install --quiet <new-deps>
./venv/bin/python -c "import <new-dep>; print('OK', <new-dep>)"
```

For a-stock-data V3.7 → V3.7.2 the new deps were: `baostock lxml xlrd openpyxl` (估值历史 + 申万变迁 XLSX 解析需要).

### 7. Smoke-test the HTTP endpoints that are sandbox-friendly
Don't try mootdx TCP — it requires mainland China IP. Test the HTTP endpoints that work from any network:

```bash
curl -s "https://qt.gtimg.cn/q=sh600519" | head -c 200   # 腾讯实时
# Should return non-empty GBK-encoded body, parseable as
# v_sh600519="~贵州茅台~1298.88~..."
```

### 8. Update DEPLOY_NOTES.md (this file's sibling in the skill dir)
Record: what version, when, what changed, what's verified, what's not. The skill dir is the source of truth for "what's deployed", not memory.

## Pitfalls

### `urllib.request.urlopen` silently fails in sandbox network
Switch to `requests.get`:
- V3.7.2 SKILL.md recommends `urllib.request.Request` for 腾讯行情 (because no dependency).
- In the Hermes sandbox VPN network, `urlopen` returns empty body / hangs without raising — making debugging impossible.
- Workaround for any local script: `import requests; requests.get(url, headers={"User-Agent": UA}, timeout=10).content.decode("gbk")`.

### 14-byte 404 bodies from curl
`curl -sSL` does **not** exit non-zero on 404 when `-L` follows and the final body is a 404 page. Always `stat -c %s` the result, or `grep -c 404` the body. Empty/short bodies ≠ no-op download.

### Branch drift
The repo's `main` branch may be ahead of what README describes. Always `mcp_github_get_file_contents(..., path="")` first; don't trust README's directory structure.

### `origin: custom` vs upstream tracking
If the local skill dir has a `.git/` folder pointing at the same repo, it's a fork. `git pull` will work. If it's just a copy (no .git), the next sync is a manual `curl` loop, not `git pull`. Check before assuming.

### User language
User speaks Chinese. All status messages and DEPLOY_NOTES.md updates in 中文. README/CHANGELOG from upstream keep their original language.