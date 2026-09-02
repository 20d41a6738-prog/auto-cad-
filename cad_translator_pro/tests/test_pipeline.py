"""
Real, non-mocked tests for the CAD Studio backend, run against the
supplied sample DXF (a real multi-view die-layout drawing).

Run with:  pytest tests/ -v
"""
import os
import sys
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import dxf_reader, geometry_analyzer, profile_detector
from backend.pipeline import Pipeline, JOBS_ROOT

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_die_layout.dxf")


def test_dxf_reader_rejects_missing_file():
    try:
        dxf_reader.read_dxf("/tmp/does_not_exist_12345.dxf")
        assert False, "expected DXFReadError"
    except dxf_reader.DXFReadError:
        pass


def test_dxf_reader_rejects_empty_file(tmp_path):
    empty = tmp_path / "empty.dxf"
    empty.write_bytes(b"")
    try:
        dxf_reader.read_dxf(str(empty))
        assert False, "expected DXFReadError"
    except dxf_reader.DXFReadError:
        pass


def test_dxf_reader_rejects_garbage(tmp_path):
    garbage = tmp_path / "garbage.dxf"
    garbage.write_bytes(b"this is not a dxf file at all, just plain text\n" * 5)
    try:
        dxf_reader.read_dxf(str(garbage))
        assert False, "expected DXFReadError"
    except dxf_reader.DXFReadError:
        pass


def test_inspect_sample_dxf():
    inspection, doc = dxf_reader.inspect(SAMPLE)
    assert inspection.valid
    assert inspection.total_entities > 0
    assert "CONSTRUCTION" in inspection.layer_names
    assert inspection.bbox is not None
    assert inspection.width > 0 and inspection.height > 0


def test_geometry_analyzer_layer_filtering():
    _, doc = dxf_reader.inspect(SAMPLE)
    all_analysis = geometry_analyzer.analyze(doc, None)
    construction_only = geometry_analyzer.analyze(doc, ["CONSTRUCTION"])
    assert len(construction_only.segments) < len(all_analysis.segments)
    assert "DIMENSION" in all_analysis.excluded_layers


def test_profile_detector_finds_closed_profile():
    _, doc = dxf_reader.inspect(SAMPLE)
    analysis = geometry_analyzer.analyze(doc, ["CONSTRUCTION", "CONTRUCTION"])
    detection = profile_detector.detect(analysis.segments, analysis.circles)
    assert detection.success
    assert detection.outer_profile is not None
    assert detection.outer_profile.area > 0


def test_profile_detector_reports_failure_on_empty_input():
    detection = profile_detector.detect([], [])
    assert not detection.success
    assert "No line/arc geometry" in detection.message


def test_full_pipeline_end_to_end():
    pipeline = Pipeline()
    try:
        result = pipeline.run(SAMPLE, ["CONSTRUCTION", "CONTRUCTION"], extrusion_depth_mm=10.0)
        assert result.success, result.error_message
        assert result.validation.valid
        # This DXF's CONSTRUCTION layer genuinely contains multiple separate
        # closed profiles (verified by direct inspection) - the pipeline must
        # not collapse them into a single body.
        assert result.validation.solids >= 1
        assert result.validation.volume > 0
        assert result.feature_set is not None
        assert result.feature_set.summary.get("OUTER_BOUNDARY", 0) >= 1
        assert os.path.exists(result.export_result.step_path)
        assert os.path.getsize(result.export_result.step_path) > 0
        assert os.path.exists(result.export_result.glb_path)
        assert os.path.getsize(result.export_result.glb_path) > 0
        # every stage must be marked done
        for status in result.stage_status.values():
            assert status == "done"
    finally:
        shutil.rmtree(pipeline.dirs["root"], ignore_errors=True)


def test_pipeline_fails_gracefully_on_bad_layer_selection():
    """Selecting a layer with no line geometry (e.g. block-only layer '0')
    must fail cleanly with a clear message, never silently fake output."""
    pipeline = Pipeline()
    try:
        result = pipeline.run(SAMPLE, ["0"], extrusion_depth_mm=10.0)
        assert not result.success
        assert result.error_message
        assert result.export_result is None
    finally:
        shutil.rmtree(pipeline.dirs["root"], ignore_errors=True)


def test_job_directories_created_and_not_overwritten():
    p1 = Pipeline()
    p2 = Pipeline()
    assert p1.job_id != p2.job_id
    for p in (p1, p2):
        assert os.path.isdir(p.dirs["input"])
        assert os.path.isdir(p.dirs["output"])
        assert os.path.isdir(p.dirs["logs"])
        shutil.rmtree(p.dirs["root"], ignore_errors=True)
