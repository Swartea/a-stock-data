import analysis.pipeline as pipeline
from analysis.orchestration import fetching


def test_pipeline_uses_call_new_fetching_boundary():
    assert pipeline._call_new is fetching._call_new


def test_pipeline_uses_margin_fetching_boundary():
    assert pipeline._fetch_margin is fetching._fetch_margin


def test_pipeline_uses_supplements_fetching_boundary():
    assert pipeline._fetch_supplements is fetching._fetch_supplements


def test_pipeline_uses_section_fetching_boundary():
    assert pipeline._fetch_sections is fetching._fetch_sections
