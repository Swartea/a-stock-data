# Swartee Market Research V1 — Final RC Closeout

Date: 2026-10-15 (Asia/Shanghai)

## RC and branch comparison

- RC branch: `codex/market-research-v1-rc-20261015`.
- Starting RC: `7e5dfc51f4a4177ba5218935ade8dedd39a62101`.
- `origin/main` and freshly fetched `FETCH_HEAD`: `d21a41179511055b8dddb2ce17a18a266e608ecb`.
- The starting RC was 15 commits ahead of `origin/main`, with no commits only on main. This closeout adds a local commit; no remote branch was updated.
- The user's unrelated pending edits in the primary `main` checkout were left untouched.

## Actual change in this closeout

- `da-a-analyze --help` and `-h` now print usage and exit 0 before entering the stock-analysis pipeline. No code/name invocation or default stock-analysis behavior changed.
- Added regression coverage that help never invokes analysis and that code-only and code-plus-name arguments retain their prior calls.
- No market-research feature or provider behavior was changed.

## Browser acceptance

The RC page was opened in a real Playwright Chromium browser. Five full-page screenshots for a normal loaded state were saved under `output/playwright/closeout-{1920,1440,1280,768,390}-ok.png`. An explicit empty-data mobile capture is `output/playwright/closeout-empty-390.png`; service-error mobile state is `output/playwright/closeout-390.png`.

| Viewport | Document width | Horizontal overflow | Result |
|---:|---:|---:|---|
| 1920 | 1920 | 0 px | Pass |
| 1440 | 1440 | 0 px | Pass |
| 1280 | 1280 | 0 px | Pass |
| 768 | 768 | 0 px | Pass |
| 390 | 390 | 0 px | Pass |

Market and index selectors were exercised across CN, HK, and US; selected identity, currency, and timezone followed the selected index. Chart zoom to 20 bars and pan to bars 41–60 operated with a 200-bar test series. A touch event on the chart produced the corresponding date and OHLC probe. Empty response and service-error response both rendered explicit states without retaining old data. The page had no JavaScript runtime errors during the interaction run. The browser console did report one missing `/favicon.ico` 404 on initial load; no application JavaScript error was reported. Browser fixture responses were used for controlled interaction cases; the earlier initial page load used the existing local RC service and displayed its provider-sourced daily bars.

## Tests and build

- Research tests: **982 passed**.
- Full Pytest after all code/test changes: **1695 passed, 2 deselected**.
- Ruff changed-range check (`analysis/quant_analyzer_v3.py`, `tests/analytics/test_quant_analyzer_cli_help.py`): **passed**.
- Full-repository Ruff: **46 existing findings**, all outside this closeout's changed Python files; not mass-refactored.
- Embedded UI JavaScript extracted from the renderer and checked with `node --check`: **passed**.
- Wheel build: **`da_a_data-0.17.0-py3-none-any.whl` built successfully** after provisioning the build environment with `build`, `setuptools`, and `wheel`.
- Isolated wheel target install: **passed**; installed package imported, enumerated 9 indices, rendered the research page, and executed installed `da-a-analyze --help` with exit 0.
- CLI smoke: installed `da-a-analyze --help` exits 0; installed no-argument invocation preserves prior usage output and exit 1. Stock argument behavior is covered by mocked regression tests, so no real stock request was made for smoke testing.
- GitHub Actions CI: **not run / not verified**; no PR exists.

## Focused review and data integrity

No Kimi review tool/session is available in this environment, so no Kimi approval is claimed. The prior targeted Codex review recorded in `release-candidate-acceptance.md` covered identity, Registry/provider symbols, daily-K orchestration, Snapshot Service, market state, and request sequence protection; this closeout did not change those modules. The final focused pass found no new cross-module or data-integrity defect. The new CLI branch exits before any provider path and preserves the existing normal argument calls.

The earlier acceptance record documents the implementation review of Canonical Identity, Global Daily-K, Snapshot Service, Golden Snapshot, Static View, and Market Research UI, including freshness/identity boundaries, no fabricated rows, explicit unknown trading-calendar state, and stale-response protection. Those paths were unchanged by this final fix.

## PR preparation (local draft only)

**Title:** 发布候选：Swartee Market Research 全球研究终端 V1

**Change summary:** Integrates canonical index identity and provider mapping, validated global daily-K research, snapshot composition and golden fixture, static snapshot rendering, and the Market Research V1 UI. Adds offline CLI help while preserving existing `da-a-analyze <code> [name]` behavior.

**Validation:** 1695 passed / 2 deselected; 982 research tests passed; changed-range Ruff passed; full Ruff retains 46 pre-existing findings; embedded JavaScript syntax, wheel build, isolated wheel install, CLI smoke, and five responsive browser viewports passed. Browser screenshots are in `output/playwright/closeout-*.png`.

**Compatibility:** Existing stock-analysis arguments, omitted-name behavior, report generation, and non-help CLI business flow are unchanged. `-h` and `--help` are new conventional help aliases.

**Known limitations:** Trading-day status remains `unknown` without supported calendar evidence. Browser interaction mocks validate rendering and gestures; GitHub CI remains unverified. No independently produced Kimi review is available.

**Rollback:** Revert the PR or close it without merging. The closeout change has no database migration or persistent runtime-state change; the UI release can be reverted with the same code revert.

**Remote status:** Push and PR creation have not been authorized or performed. Do not merge `main` automatically.

## Merge decision

Local implementation and acceptance gates pass. The release does **not yet meet the complete merge-main gate** because GitHub CI has not run. After explicit push/PR authorization, merge readiness still requires the PR CI checks to pass and a final check for new review findings. No merge has occurred.

## 2026-10-16 GitHub CI follow-up

- PR #7: https://github.com/Swartea/a-stock-data/pull/7; open, base `main` at `d21a41179511055b8dddb2ce17a18a266e608ecb`, RC head `feb2b709d71fa429201997116b3fcdd2f2ecef1f`.
- Repository Actions permissions report `enabled: true` and `allowed_actions: all`; the `CI` workflow (`.github/workflows/ci.yml`) is active and includes `workflow_dispatch`.
- PR #7 has no check runs. A manual dispatch against the RC branch was attempted once and GitHub rejected it with HTTP 422: `Actions has been disabled for this repository`. No CI jobs or logs were produced. The reported permission/workflow state and dispatch rejection are inconsistent; execution remains blocked at GitHub.
- No source changes or repair commits were made in this follow-up. Existing local validation remains 1695 passed / 2 deselected; it does not substitute for GitHub CI.
- Current PR metadata reports `MERGEABLE` / `CLEAN`, but no branch protection is configured and no required checks are reported. Do not merge until Actions can actually run and the complete CI result is reviewed. No merge or deployment occurred.
