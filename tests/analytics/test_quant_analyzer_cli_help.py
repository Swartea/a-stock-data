"""CLI help must exit before entering the live stock-analysis pipeline."""

import sys

import pytest

from analysis import quant_analyzer_v3


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_prints_usage_without_running_analysis(monkeypatch, capsys, flag):
    monkeypatch.setattr(sys, "argv", ["da-a-analyze", flag])

    def unexpected_analysis(*args, **kwargs):
        pytest.fail("help must not run stock analysis or request market data")

    monkeypatch.setattr(quant_analyzer_v3, "analyze_single_v3", unexpected_analysis)

    assert quant_analyzer_v3.main() == 0
    output = capsys.readouterr().out
    assert "da-a-analyze <code> [name]" in output
    assert "--help" in output


@pytest.mark.parametrize(
    ("argv", "expected"),
    [(["da-a-analyze", "600000"], ("600000", "")),
     (["da-a-analyze", "600000", "浦发银行"], ("600000", "浦发银行"))],
)
def test_stock_arguments_keep_the_existing_analysis_contract(monkeypatch, argv, expected):
    calls = []
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(
        quant_analyzer_v3,
        "analyze_single_v3",
        lambda *args: calls.append(args) or {},
    )

    assert quant_analyzer_v3.main() == 0
    assert calls == [expected]
