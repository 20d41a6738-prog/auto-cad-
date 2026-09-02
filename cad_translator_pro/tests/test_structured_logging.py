"""
Tests for structured log events (SUCCESS/WARNING/ERROR/NOT_CONVERTED/ASSUMPTION).
Uses backend.pipeline.LogEntry/Pipeline.log directly so it does not require
cadquery/trimesh/streamlit to be installed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.pipeline import Pipeline, LogEntry


def _make_pipeline(tmp_path):
    p = Pipeline(job_id="TEST-LOG-001")
    p.dirs = {k: str(tmp_path / k) for k in ["root", "input", "intermediate", "output", "logs"]}
    for d in p.dirs.values():
        os.makedirs(d, exist_ok=True)
    return p


def test_log_entry_has_structured_fields():
    entry = LogEntry("12:00:00", "NOT_CONVERTED", "msg", stage="s", entity="e",
                      reason="r", details="d")
    assert entry.level == "NOT_CONVERTED"
    assert entry.stage == "s"
    assert entry.entity == "e"
    assert entry.reason == "r"
    assert entry.details == "d"


def test_all_five_levels_supported(tmp_path):
    p = _make_pipeline(tmp_path)
    levels = ["SUCCESS", "WARNING", "ERROR", "NOT_CONVERTED", "ASSUMPTION"]
    for lvl in levels:
        p.log(lvl, f"{lvl} message", stage="test_stage", entity="entity1",
              reason="reason1", details="detail1")
    seen = {e.level for e in p.logs}
    assert seen == set(levels)


def test_write_log_file_includes_stage_and_reason(tmp_path):
    p = _make_pipeline(tmp_path)
    p.log("NOT_CONVERTED", "Spline could not be converted", stage="classifying_features",
          entity="ring#3", reason="unsupported curve type")
    p._write_log_file()
    log_path = os.path.join(p.dirs["logs"], "translation.log")
    assert os.path.exists(log_path)
    content = open(log_path).read()
    assert "NOT_CONVERTED" in content
    assert "classifying_features" in content
    assert "unsupported curve type" in content


def test_not_converted_events_carry_reason_and_impact(tmp_path):
    p = _make_pipeline(tmp_path)
    p.log("NOT_CONVERTED", "Ring #2 (spline) not converted - unsupported",
          stage="classifying_features", entity="ring#2 (spline)",
          reason="unsupported curve type",
          details="Feature omitted from generated solid; part geometry incomplete.")
    e = p.logs[-1]
    assert e.reason
    assert e.details
    assert e.entity
