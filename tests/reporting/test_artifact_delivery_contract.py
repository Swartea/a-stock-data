import builtins
import json
import subprocess
import sys
from datetime import datetime as RealDateTime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import analysis.pipeline as pipeline
from analysis.reporting import artifact_writer

FIXED_NOW = RealDateTime(2026, 9, 15, 22, 53, 0)


class FixedDateTime:
    @classmethod
    def now(cls):
        return FIXED_NOW


@pytest.fixture
def writer():
    return artifact_writer


def test_pipeline_reexports_artifact_writer_boundary():
    assert pipeline._emit is artifact_writer._emit
    assert pipeline._dump_run_log is artifact_writer._dump_run_log


def _result():
    return {
        "code": "600693",
        "name": "东百集团",
        "run_log": {
            "started_at": "2026-09-15T22:52:00+08:00",
            "finished_at": "2026-09-15T22:53:00+08:00",
            "total_sec": 60.0,
            "sources": {},
            "source_meta": {},
            "fallback_chain": [],
            "guard": {},
            "fatal": None,
        },
    }


def _prepare_base(writer, monkeypatch, tmp_path):
    monkeypatch.setattr(writer, "REPORTS_ROOT", str(tmp_path))
    monkeypatch.setattr(writer, "datetime", FixedDateTime)
    monkeypatch.setattr(
        writer,
        "write_markdown_report_v3",
        lambda _result: "# artifact contract\n",
    )


def _install_optional_success(monkeypatch):
    html_module = ModuleType("html_report_v3")

    def write_html_report_v3(result, day_dir):
        html_path = Path(day_dir) / "600693-东百集团-v3-20260915-2253.html"
        pdf_path = Path(day_dir) / "600693-东百集团-v3-20260915-2253.pdf"
        html_path.write_text("<html>ok</html>", encoding="utf-8")
        pdf_path.write_bytes(b"%PDF-1.4 contract")
        result["pdf_status"] = "ok"
        result["pdf_path"] = str(pdf_path)
        return str(html_path)

    html_module.write_html_report_v3 = write_html_report_v3
    monkeypatch.setitem(sys.modules, "html_report_v3", html_module)

    docx_module = ModuleType("md_to_docx")

    def md_to_docx(_md_path, docx_path):
        Path(docx_path).write_bytes(b"docx contract")

    docx_module.md_to_docx = md_to_docx
    monkeypatch.setitem(sys.modules, "md_to_docx", docx_module)


def _install_optional_failures(monkeypatch):
    html_module = ModuleType("html_report_v3")

    def write_html_report_v3(_result, _day_dir):
        raise RuntimeError("html boom")

    html_module.write_html_report_v3 = write_html_report_v3
    monkeypatch.setitem(sys.modules, "html_report_v3", html_module)

    docx_module = ModuleType("md_to_docx")

    def md_to_docx(_md_path, _docx_path):
        raise RuntimeError("docx boom")

    docx_module.md_to_docx = md_to_docx
    monkeypatch.setitem(sys.modules, "md_to_docx", docx_module)

    def fail_subprocess(*_args, **_kwargs):
        raise RuntimeError("subprocess boom")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)


def test_emit_complete_delivery_writes_timestamped_required_artifacts_and_final_state(
    writer,
    monkeypatch,
    tmp_path,
):
    _prepare_base(writer, monkeypatch, tmp_path)
    _install_optional_success(monkeypatch)
    result = _result()

    files = writer._emit("600693", "东百集团", result)

    day_dir = tmp_path / "600693_东百集团" / "2026-09-15"
    assert Path(files["day_dir"]) == day_dir
    assert Path(files["md"]).name == "600693-东百集团-v3-20260915-2253.md"
    assert Path(files["json"]).name == "result_v3-2253.json"
    assert Path(files["run_log"]).name == "run_log-2253.json"
    assert Path(files["html"]).name == "600693-东百集团-v3-20260915-2253.html"
    assert Path(files["docx"]).name == "600693-东百集团-v3-20260915-2253.docx"
    assert Path(files["pdf"]).name == "600693-东百集团-v3-20260915-2253.pdf"

    # 命名统一契约 (2026-09-22): MD/HTML/DOCX/PDF 词干均为
    # {code}-{name}-v3-{YYYYMMDD}-{HHMM}; run_log/result_v3 保持 {HHMM} 不变
    import re

    for key in ("md", "html", "docx", "pdf"):
        assert re.match(
            r"600693-东百集团-v3-\d{8}-\d{4}\." + key, Path(files[key]).name
        ), f"{key} 命名应为 {{code}}-{{name}}-v3-{{YYYYMMDD}}-{{HHMM}}"
    assert re.match(r"run_log-\d{4}\.json", Path(files["run_log"]).name)
    assert re.match(r"result_v3-\d{4}\.json", Path(files["json"]).name)

    status = files["status"]
    assert status["md"] == "ok"
    assert status["json"] == "ok"
    assert status["log"] == "ok"
    assert status["html"] == "ok"
    assert status["docx"] == "ok"
    assert status["pdf"] == "ok"
    assert status["deliverable"] == "complete"
    assert status["required_failed"] == []
    assert status["optional_failed"] == []

    assert result["_files"] is files
    assert result["deliverable_status"] == "complete"

    run_log_disk = json.loads(Path(files["run_log"]).read_text(encoding="utf-8"))
    artifacts = run_log_disk["artifacts"]
    assert artifacts["deliverable_status"] == "complete"
    assert artifacts["run_log_status"] == "ok"
    assert artifacts["required_ok"] == ["md", "result_json", "run_log"]
    assert artifacts["optional_ok"] == ["html", "docx", "pdf"]
    assert artifacts["required_failed"] == []
    assert artifacts["optional_failed"] == []
    assert artifacts["sizes_bytes"]["md"] > 0
    assert artifacts["sizes_bytes"]["result_json"] > 0
    assert artifacts["sizes_bytes"]["run_log"] > 0

    result_disk = json.loads(Path(files["json"]).read_text(encoding="utf-8"))
    assert result_disk["deliverable_status"] == "complete"
    assert result_disk["_files"]["status"]["deliverable"] == "complete"
    assert result_disk["run_log"]["artifacts"]["deliverable_status"] == "complete"


def test_emit_docx_subprocess_fallback_is_still_counted_as_complete(
    writer,
    monkeypatch,
    tmp_path,
):
    _prepare_base(writer, monkeypatch, tmp_path)
    _install_optional_success(monkeypatch)

    docx_module = ModuleType("md_to_docx")

    def fail_import_path(_md_path, _docx_path):
        raise RuntimeError("docx primary boom")

    docx_module.md_to_docx = fail_import_path
    monkeypatch.setitem(sys.modules, "md_to_docx", docx_module)

    def fake_run(cmd, check, timeout):
        assert check is True
        assert timeout == 180
        Path(cmd[-1]).write_bytes(b"docx subprocess")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = _result()

    files = writer._emit("600693", "东百集团", result)

    assert files["status"]["docx"] == "ok(import失败→subprocess)"
    assert files["status"]["deliverable"] == "complete"
    assert files["status"]["optional_failed"] == []
    assert Path(files["docx"]).read_bytes() == b"docx subprocess"

    run_log_disk = json.loads(Path(files["run_log"]).read_text(encoding="utf-8"))
    assert "docx" in run_log_disk["artifacts"]["optional_ok"]
    assert run_log_disk["artifacts"]["deliverable_status"] == "complete"


def test_emit_optional_failures_degrade_to_partial_without_failing_required_artifacts(
    writer,
    monkeypatch,
    tmp_path,
):
    _prepare_base(writer, monkeypatch, tmp_path)
    _install_optional_failures(monkeypatch)
    result = _result()

    files = writer._emit("600693", "东百集团", result)

    status = files["status"]
    assert status["md"] == "ok"
    assert status["json"] == "ok"
    assert status["log"] == "ok"
    assert status["html"] == "error:html boom"
    assert status["docx"].startswith(
        "error:docx boom | subprocess: subprocess boom"
    )
    assert status["pdf"] == "skipped:html_report_v3 未执行"
    assert status["deliverable"] == "partial"
    assert status["required_failed"] == []
    assert status["optional_failed"] == ["html", "docx", "pdf"]
    assert result["deliverable_status"] == "partial"

    run_log_disk = json.loads(Path(files["run_log"]).read_text(encoding="utf-8"))
    assert run_log_disk["artifacts"]["required_ok"] == [
        "md",
        "result_json",
        "run_log",
    ]
    assert run_log_disk["artifacts"]["optional_failed"] == [
        "html",
        "docx",
        "pdf",
    ]


def test_emit_required_markdown_failure_makes_delivery_failed_even_if_optional_succeeds(
    writer,
    monkeypatch,
    tmp_path,
):
    _prepare_base(writer, monkeypatch, tmp_path)
    _install_optional_success(monkeypatch)

    def fail_markdown(_result):
        raise RuntimeError("markdown boom")

    monkeypatch.setattr(writer, "write_markdown_report_v3", fail_markdown)
    result = _result()

    files = writer._emit("600693", "东百集团", result)

    status = files["status"]
    assert status["md"] == "error:markdown boom"
    assert status["json"] == "ok"
    assert status["log"] == "ok"
    assert status["html"] == "ok"
    assert status["docx"] == "ok"
    assert status["pdf"] == "ok"
    assert status["deliverable"] == "failed"
    assert status["required_failed"] == ["md"]
    assert status["optional_failed"] == []
    assert result["deliverable_status"] == "failed"
    assert not Path(files["md"]).exists()


def test_emit_run_log_write_failure_is_a_required_artifact_failure(
    writer,
    monkeypatch,
    tmp_path,
):
    _prepare_base(writer, monkeypatch, tmp_path)
    _install_optional_success(monkeypatch)
    result = _result()

    real_open = builtins.open

    def selective_open(file, *args, **kwargs):
        if Path(str(file)).name == "run_log-2253.json":
            raise OSError("log boom")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", selective_open)

    files = writer._emit("600693", "东百集团", result)

    status = files["status"]
    assert status["log"] == "error:log boom"
    assert status["deliverable"] == "failed"
    assert status["required_failed"] == ["run_log"]
    assert status["optional_failed"] == []
    assert result["deliverable_status"] == "failed"
    assert not Path(files["run_log"]).exists()
    assert result["run_log"]["artifacts"]["sizes_bytes"]["run_log"] is None

    result_disk = json.loads(Path(files["json"]).read_text(encoding="utf-8"))
    assert result_disk["run_log"]["artifacts"]["run_log_status"] == "error:log boom"
    assert result_disk["run_log"]["artifacts"]["deliverable_status"] == "failed"


def test_dump_run_log_uses_code_as_safe_name_when_name_is_empty(
    writer,
    monkeypatch,
    tmp_path,
):
    _prepare_base(writer, monkeypatch, tmp_path)
    run_log = {"fatal": "boom", "sources": {}}

    writer._dump_run_log("600693", "", run_log)

    log_path = (
        tmp_path
        / "600693_600693"
        / "2026-09-15"
        / "run_log-2253.json"
    )
    assert log_path.exists()
    assert json.loads(log_path.read_text(encoding="utf-8")) == run_log


def test_emit_pdf_libreoffice_fallback_can_reach_complete(
    writer,
    monkeypatch,
    tmp_path,
):
    _prepare_base(writer, monkeypatch, tmp_path)

    html_module = ModuleType("html_report_v3")

    def write_html_report_v3(result, day_dir):
        html_path = Path(day_dir) / "600693-东百集团-v3-20260915-2253.html"
        html_path.write_text("<html>ok</html>", encoding="utf-8")
        result["pdf_status"] = "error:TimeoutExpired: chrome timeout"
        result["pdf_path"] = None
        return str(html_path)

    html_module.write_html_report_v3 = write_html_report_v3
    monkeypatch.setitem(sys.modules, "html_report_v3", html_module)

    docx_module = ModuleType("md_to_docx")

    def md_to_docx(_md_path, docx_path):
        Path(docx_path).write_bytes(b"docx contract")

    docx_module.md_to_docx = md_to_docx
    monkeypatch.setitem(sys.modules, "md_to_docx", docx_module)

    import shutil

    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/usr/local/bin/soffice" if name == "soffice" else None,
    )

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "/usr/local/bin/soffice"
        assert "--headless" in cmd
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 60
        out_dir = Path(cmd[cmd.index("--outdir") + 1])
        docx_path = Path(cmd[-1])
        (out_dir / f"{docx_path.stem}.pdf").write_bytes(b"%PDF fallback")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = _result()

    files = writer._emit("600693", "东百集团", result)

    assert files["status"]["pdf"] == "ok(fallback:libreoffice)"
    assert files["status"]["pdf_renderer"] == "libreoffice"
    assert files["status"]["pdf_fallback"] == "ok"
    assert files["status"]["deliverable"] == "complete"
    assert Path(files["pdf"]).read_bytes() == b"%PDF fallback"
    assert result["pdf_renderer"] == "libreoffice"

    run_log_disk = json.loads(Path(files["run_log"]).read_text(encoding="utf-8"))
    artifacts = run_log_disk["artifacts"]
    assert artifacts["pdf_renderer"] == "libreoffice"
    assert artifacts["pdf_fallback_status"] == "ok"
    assert artifacts["deliverable_status"] == "complete"
def test_emit_chrome_pdf_success_does_not_probe_libreoffice(
    writer,
    monkeypatch,
    tmp_path,
):
    _prepare_base(writer, monkeypatch, tmp_path)
    _install_optional_success(monkeypatch)

    import shutil

    def unexpected_probe(_name):
        pytest.fail("Chrome PDF 已成功时不应探测 LibreOffice")

    monkeypatch.setattr(shutil, "which", unexpected_probe)
    result = _result()

    files = writer._emit("600693", "东百集团", result)

    assert files["status"]["pdf"] == "ok"
    assert files["status"]["pdf_renderer"] == "chrome"
    assert files["status"]["pdf_fallback"] == "not-needed"
    assert files["status"]["deliverable"] == "complete"


def test_emit_missing_libreoffice_records_capability_gap_and_stays_partial(
    writer,
    monkeypatch,
    tmp_path,
):
    _prepare_base(writer, monkeypatch, tmp_path)

    html_module = ModuleType("html_report_v3")

    def write_html_report_v3(result, day_dir):
        html_path = Path(day_dir) / "600693-东百集团-v3-20260915-2253.html"
        html_path.write_text("<html>ok</html>", encoding="utf-8")
        result["pdf_status"] = "error:TimeoutExpired: chrome timeout"
        result["pdf_path"] = None
        return str(html_path)

    html_module.write_html_report_v3 = write_html_report_v3
    monkeypatch.setitem(sys.modules, "html_report_v3", html_module)

    docx_module = ModuleType("md_to_docx")

    def md_to_docx(_md_path, docx_path):
        Path(docx_path).write_bytes(b"docx contract")

    docx_module.md_to_docx = md_to_docx
    monkeypatch.setitem(sys.modules, "md_to_docx", docx_module)

    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    result = _result()

    files = writer._emit("600693", "东百集团", result)

    assert files["status"]["pdf"] == "error:TimeoutExpired: chrome timeout"
    assert files["status"]["pdf_fallback"].startswith(
        "error:FileNotFoundError: 未找到 LibreOffice/soffice"
    )
    assert files["status"]["deliverable"] == "partial"
    assert files["status"]["required_failed"] == []
    assert files["status"]["optional_failed"] == ["pdf"]

    run_log_disk = json.loads(Path(files["run_log"]).read_text(encoding="utf-8"))
    artifacts = run_log_disk["artifacts"]
    assert artifacts["pdf_fallback_status"].startswith(
        "error:FileNotFoundError: 未找到 LibreOffice/soffice"
    )
    assert artifacts["deliverable_status"] == "partial"


@pytest.mark.integration
def test_real_libreoffice_converts_minimal_docx_to_nonempty_pdf(tmp_path):
    import shutil

    office_bin = shutil.which("soffice") or shutil.which("libreoffice")
    if not office_bin:
        pytest.skip("LibreOffice/soffice not installed")

    from docx import Document

    docx_path = tmp_path / "libreoffice-fallback-contract.docx"
    pdf_path = tmp_path / "libreoffice-fallback-contract.pdf"
    profile_dir = tmp_path / "libreoffice-profile"
    profile_dir.mkdir()

    document = Document()
    document.add_paragraph("Phase 0 PDF fallback integration contract")
    document.save(docx_path)

    subprocess.run(
        [
            office_bin,
            f"-env:UserInstallation={profile_dir.as_uri()}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_path),
            str(docx_path),
        ],
        check=True,
        timeout=60,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
