import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_v3.sh"


def test_run_v3_prefers_dot_venv_before_legacy_venv() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert text.index("$ROOT_DIR/.venv/bin/python") < text.index("$ROOT_DIR/venv/bin/python")
    assert "DA_PYTHON" in text
    assert 'find_spec("baostock")' in text


def test_run_v3_check_uses_explicit_da_python() -> None:
    env = os.environ.copy()
    env["DA_PYTHON"] = sys.executable

    proc = subprocess.run(
        ["bash", str(SCRIPT), "--check"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "[runtime] python=" in proc.stderr
    assert str(Path(sys.executable).resolve()) in str(Path(proc.stderr.split("python=", 1)[1].strip()).resolve())


def test_run_v3_rejects_invalid_da_python_explicitly(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["DA_PYTHON"] = str(tmp_path / "missing-python")

    proc = subprocess.run(
        ["bash", str(SCRIPT), "--check"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert proc.returncode == 2
    assert "DA_PYTHON 不可执行" in proc.stderr
