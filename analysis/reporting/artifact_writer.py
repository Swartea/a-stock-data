"""Artifact delivery boundary for the V3 pipeline.

This module preserves the existing report-output contract while separating
filesystem delivery from the main orchestration flow.  Required/optional
artifact semantics, fallback behavior, status wording, and result mutations
match the historical ``analysis.pipeline`` implementation.
"""

import json
import os
import sys
import time
from datetime import datetime

from analysis.report_md import write_markdown_report_v3
from analysis.utils import _json_default


_ANALYSIS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

REPORTS_ROOT = os.path.normpath(os.path.join(_ANALYSIS_DIR, "..", "reports"))


def _emit(code: str, name: str, result: dict) -> dict:
    """6 件套落盘 (out_dir 内, 同 HHMM 时间戳命名):
    ① {code}-{name}-{HHMM}.md            (必需, §7 必需产物)
    ② result_v3.json                     (必需, 完整 result dict)
    ③ run_log.json                       (必需, 链路记录)
    ④ {code}-{name}-{HHMM}.html          (允许降级, 写 run_log.html_status)
    ⑤ {code}-{name}-{HHMM}.docx          (允许降级, 写 run_log.docx_status)
    ⑥ {code}-{name}-{HHMM}.pdf           (允许降级, html_report_v3 写 result.pdf_status)

    P1-A (2026-09-11, §7): 输出 deliverable_status = complete / partial / failed
      - complete: 3 必需 + 3 允许降级全活
      - partial: 必需全活, 至少 1 个允许降级失败
      - failed:  至少 1 个必需失败
    """
    safe_name = name or code
    day_dir = os.path.join(
        REPORTS_ROOT,
        f"{code}_{safe_name}",
        datetime.now().strftime("%Y-%m-%d"),
    )
    os.makedirs(day_dir, exist_ok=True)
    hhmm = datetime.now().strftime("%H%M")
    base = f"{code}-{safe_name}-{hhmm}"
    md_path = os.path.join(day_dir, f"{base}.md")
    html_path = os.path.join(day_dir, f"{base}.html")
    docx_path = os.path.join(day_dir, f"{base}.docx")
    json_path = os.path.join(day_dir, f"result_v3-{hhmm}.json")
    log_path = os.path.join(day_dir, f"run_log-{hhmm}.json")

    # ① MD (必需)
    md_status = "ok"
    md_err = ""
    try:
        md_text = write_markdown_report_v3(result)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
    except Exception as e:  # noqa: BLE001
        md_status = f"error:{str(e)[:120]}"
        md_err = str(e)

    # ② result_v3.json (必需, P1-C 显式 JSONEncoder)
    json_status = "ok"
    json_err = ""
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=_json_default)
    except Exception as e:  # noqa: BLE001
        json_status = f"error:{str(e)[:120]}"
        json_err = str(e)

    # ③ HTML (允许降级)
    html_status = "error:未执行"
    html_err = ""
    t0 = time.time()
    try:
        try:
            import html_report_v3 as _hrv3
        except Exception:  # noqa: BLE001 — import 失败: 补 sys.path 后重试一次
            sys.path.insert(0, _ANALYSIS_DIR)
            import html_report_v3 as _hrv3

        html_path = _hrv3.write_html_report_v3(result, day_dir)
        # P1-A: html_report_v3 内部已写 result.pdf_status
        html_status = (
            "ok"
            if (html_path and os.path.exists(html_path))
            else "error: HTML 文件未生成"
        )
    except Exception as e:  # noqa: BLE001
        html_err = str(e)
        html_status = f"error:{str(e)[:120]}"
    html_ms = round((time.time() - t0) * 1000)

    # ④ DOCX (允许降级)
    docx_status = "error:未执行"
    docx_err = ""
    t0 = time.time()
    try:
        sys.path.insert(0, _ANALYSIS_DIR)
        from md_to_docx import md_to_docx as _md2docx

        _md2docx(md_path, docx_path)
        docx_status = "ok"
    except Exception as e1:  # noqa: BLE001
        try:
            import subprocess

            subprocess.run(
                [
                    sys.executable,
                    os.path.join(_ANALYSIS_DIR, "md_to_docx.py"),
                    md_path,
                    docx_path,
                ],
                check=True,
                timeout=180,
            )
            docx_status = "ok(import失败→subprocess)"
        except Exception as e2:  # noqa: BLE001
            docx_err = f"{e1} | subprocess: {e2}"
            docx_status = f"error:{docx_err[:120]}"
    docx_ms = round((time.time() - t0) * 1000)

    # ⑤ PDF (允许降级): Chrome 主路径失败后，DOCX → LibreOffice 作为第二渲染器
    pdf_status = result.get("pdf_status", "skipped:html_report_v3 未执行")
    pdf_path = result.get("pdf_path")
    pdf_renderer = result.get("pdf_renderer")
    pdf_fallback_status = "not-needed"

    pdf_ok = pdf_status == "ok" or (
        isinstance(pdf_status, str) and pdf_status.startswith("ok(")
    )
    docx_ok = docx_status == "ok" or (
        isinstance(docx_status, str) and docx_status.startswith("ok(")
    )
    if pdf_ok:
        pdf_renderer = pdf_renderer or "chrome"
        result["pdf_renderer"] = pdf_renderer
    elif docx_ok and os.path.exists(docx_path):
        try:
            import shutil
            import subprocess

            office_bin = shutil.which("soffice") or shutil.which("libreoffice")
            if not office_bin:
                raise FileNotFoundError("未找到 LibreOffice/soffice")

            fallback_pdf = os.path.splitext(docx_path)[0] + ".pdf"
            if os.path.exists(fallback_pdf):
                os.remove(fallback_pdf)
            subprocess.run(
                [
                    office_bin,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    day_dir,
                    docx_path,
                ],
                check=True,
                timeout=60,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if not os.path.exists(fallback_pdf) or os.path.getsize(fallback_pdf) <= 0:
                raise RuntimeError("LibreOffice 未生成有效 PDF")
            pdf_path = fallback_pdf
            pdf_status = "ok(fallback:libreoffice)"
            pdf_renderer = "libreoffice"
            pdf_fallback_status = "ok"
            result["pdf_path"] = pdf_path
            result["pdf_status"] = pdf_status
            result["pdf_renderer"] = pdf_renderer
        except Exception as e:  # noqa: BLE001
            pdf_fallback_status = f"error:{type(e).__name__}: {str(e)[:100]}"
    else:
        pdf_fallback_status = "skipped:DOCX 未就绪"

    # ================= P1-A deliverable_status 计算 (§7) =================
    optional_status = {"html": html_status, "docx": docx_status, "pdf": pdf_status}

    def _is_ok(s):
        return s == "ok" or (isinstance(s, str) and s.startswith("ok("))

    def _calc_deliverable(rl_status):
        req = {"md": md_status, "result_json": json_status, "run_log": rl_status}
        req_failed = [k for k, v in req.items() if not _is_ok(v)]
        opt_failed = [k for k, v in optional_status.items() if not _is_ok(v)]
        if req_failed:
            return (
                "failed",
                req_failed,
                [k for k, v in req.items() if _is_ok(v)],
                opt_failed,
            )
        if opt_failed:
            return "partial", [], [k for k, v in req.items() if _is_ok(v)], opt_failed
        return "complete", [], [k for k, v in req.items() if _is_ok(v)], []

    # run_log 第一次写 (含产物状态 + sizes)
    rl = result.get("run_log") or {}
    sizes = {}
    for label, p in [
        ("md", md_path),
        ("html", html_path),
        ("docx", docx_path),
        ("result_json", json_path),
        ("pdf", pdf_path),
    ]:
        try:
            sizes[label] = os.path.getsize(p) if p else None
        except OSError:
            sizes[label] = None
    rl["artifacts"] = {
        "md": os.path.basename(md_path),
        "html": os.path.basename(html_path),
        "docx": os.path.basename(docx_path),
        "pdf": os.path.basename(pdf_path) if pdf_path else None,
        "result_json": os.path.basename(json_path),
        "md_status": md_status,
        "html_status": html_status,
        "docx_status": docx_status,
        "pdf_status": pdf_status,
        "pdf_renderer": pdf_renderer,
        "pdf_fallback_status": pdf_fallback_status,
        "result_json_status": json_status,
        "html_ms": html_ms,
        "docx_ms": docx_ms,
        "sizes_bytes": sizes,
    }
    log_status = "ok"
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(rl, f, ensure_ascii=False, indent=2, default=_json_default)
    except Exception as e:  # noqa: BLE001
        log_status = f"error:{str(e)[:120]}"
    rl["artifacts"]["run_log_status"] = log_status
    sizes["run_log"] = os.path.getsize(log_path) if os.path.exists(log_path) else None
    rl["artifacts"]["sizes_bytes"] = sizes

    # 算最终 deliverable (含 run_log)
    deliverable_status, req_failed, req_ok, opt_failed = _calc_deliverable(log_status)
    rl["artifacts"]["deliverable_status"] = deliverable_status
    rl["artifacts"]["required_failed"] = req_failed
    rl["artifacts"]["optional_failed"] = opt_failed
    rl["artifacts"]["required_ok"] = req_ok
    rl["artifacts"]["optional_ok"] = [
        k for k, v in optional_status.items() if _is_ok(v)
    ]
    rl["artifacts"]["sizes_bytes"] = sizes

    # 第二次写 run_log (含 deliverable + sizes)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(rl, f, ensure_ascii=False, indent=2, default=_json_default)
    except Exception:
        pass

    files = {
        "md": md_path,
        "html": html_path,
        "docx": docx_path,
        "pdf": pdf_path,
        "json": json_path,
        "run_log": log_path,
        "day_dir": day_dir,
        "status": {
            "md": md_status,
            "html": html_status,
            "docx": docx_status,
            "pdf": pdf_status,
            "pdf_renderer": pdf_renderer,
            "pdf_fallback": pdf_fallback_status,
            "json": json_status,
            "log": log_status,
            "deliverable": deliverable_status,
            "required_failed": req_failed,
            "optional_failed": opt_failed,
            "html_err": html_err,
            "docx_err": docx_err,
            "json_err": json_err,
            "md_err": md_err,
        },
    }
    result["_files"] = files
    result["deliverable_status"] = deliverable_status

    # ②(终) 补 dump: result["run_log"] 与 rl 同对象, 此时已含 artifacts; _files 也一并入 json
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=_json_default)
    except Exception as e:  # noqa: BLE001
        print(f"  [WARN] result_v3.json 终 dump 失败: {e}")

    if html_status != "ok":
        print(f"  [WARN] HTML 生成失败: {html_status}")
    if docx_status != "ok":
        print(f"  [WARN] DOCX 生成失败: {docx_status}")
    if pdf_status != "ok":
        print(f"  [WARN] PDF 生成失败: {pdf_status}")
    return files


def _dump_run_log(code: str, name: str, run_log: dict):
    """失败中止时也落 run_log.json (便于排查)。"""
    safe_name = name or code
    day_dir = os.path.join(
        REPORTS_ROOT,
        f"{code}_{safe_name}",
        datetime.now().strftime("%Y-%m-%d"),
    )
    os.makedirs(day_dir, exist_ok=True)
    with open(
        os.path.join(day_dir, f"run_log-{datetime.now().strftime('%H%M')}.json"),
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(run_log, f, ensure_ascii=False, indent=2, default=_json_default)
