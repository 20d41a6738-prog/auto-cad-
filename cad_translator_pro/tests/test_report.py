"""
Tests for backend/report.py — the single PDF Conversion Report.
Uses lightweight mock objects standing in for PipelineResult so these
tests do not require cadquery/trimesh/streamlit to be installed.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    # Preferred: use the real LogEntry so this test tracks the real schema.
    from backend.pipeline import LogEntry
except ImportError:
    # backend.pipeline pulls in ezdxf/cadquery/trimesh transitively; if those
    # heavy optional deps aren't installed in this environment, fall back to
    # a schema-identical stand-in so report.py's own logic can still be
    # tested in isolation.
    from dataclasses import dataclass

    @dataclass
    class LogEntry:  # type: ignore
        timestamp: str
        level: str
        message: str
        stage: str = ""
        entity: str = ""
        reason: str = ""
        details: str = ""

from backend import report as report_mod


def _mock_success_result():
    logs = [
        LogEntry("10:00:00", "INFO", "Reading DXF", stage="reading_dxf"),
        LogEntry("10:00:01", "SUCCESS", "Entities detected: 42", stage="reading_dxf"),
        LogEntry("10:00:02", "WARNING", "Layer DIM excluded", stage="analyzing_geometry"),
        LogEntry("10:00:03", "NOT_CONVERTED", "Ring #2 (spline) not converted - unsupported",
                  stage="classifying_features", entity="ring#2 (spline)",
                  reason="unsupported curve type", details="Feature omitted from solid."),
        LogEntry("10:00:04", "ASSUMPTION", "Extrusion depth set to 10.0 mm",
                  stage="generating_solid", entity="extrusion_depth",
                  reason="2D DXF contains no 3rd-dimension data."),
        LogEntry("10:00:05", "SUCCESS", "STEP generated and verified", stage="exporting_step"),
    ]
    inspection = SimpleNamespace(dxf_version="AC1027", total_entities=42,
                                  layer_names=["OUTLINE", "DIM"], units="mm",
                                  bbox=(0, 0, 100, 50))
    feature_set = SimpleNamespace(summary={"HOLES": 3, "SLOTS": 1, "POCKETS": 0, "BOSSES": 0})
    validation = SimpleNamespace(valid=True, message="Geometry is valid.",
                                  solids=1, faces=12, edges=30, vertices=20,
                                  volume=1234.5, surface_area=987.6,
                                  bbox=(0, 0, 0, 100, 50, 10))
    export_result = SimpleNamespace(step_path="/tmp/job/output/part.step",
                                     glb_path="/tmp/job/output/part.glb",
                                     step_size_bytes=20480, glb_size_bytes=10240,
                                     mesh_vertex_count=500, mesh_face_count=900,
                                     message="STEP written and verified. GLB written and verified.")
    return SimpleNamespace(
        success=True, job_id="JOB-001", job_dir="/tmp/job", logs=logs,
        inspection=inspection, feature_set=feature_set, validation=validation,
        export_result=export_result, processing_time_sec=3.21, error_message="",
    )


def _mock_failure_result():
    logs = [
        LogEntry("10:00:00", "INFO", "Reading DXF", stage="reading_dxf"),
        LogEntry("10:00:01", "ERROR", "No closed profiles found", stage="detecting_profiles",
                  reason="No closed profiles found"),
    ]
    return SimpleNamespace(
        success=False, job_id="JOB-002", job_dir="/tmp/job2", logs=logs,
        inspection=None, feature_set=None, validation=None, export_result=None,
        processing_time_sec=0.5, error_message="No closed profiles found",
    )


def test_pdf_generated_for_success(tmp_path):
    out = str(tmp_path / "report.pdf")
    result = _mock_success_result()
    path = report_mod.generate_pdf_report(result, "JOB-001", "sample_die_layout.dxf", out)
    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000  # not empty/corrupt


def test_pdf_is_valid_pdf_bytes(tmp_path):
    out = str(tmp_path / "report2.pdf")
    result = _mock_success_result()
    report_mod.generate_pdf_report(result, "JOB-001", "sample_die_layout.dxf", out)
    with open(out, "rb") as f:
        head = f.read(5)
        f.seek(-32, os.SEEK_END)
        tail = f.read()
    assert head == b"%PDF-"
    assert b"%%EOF" in tail


def test_pdf_generated_for_failure(tmp_path):
    out = str(tmp_path / "report_fail.pdf")
    result = _mock_failure_result()
    path = report_mod.generate_pdf_report(result, "JOB-002", "broken.dxf", out)
    assert os.path.exists(path)
    assert os.path.getsize(path) > 500


def _extract_text(pdf_path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_pdf_contains_required_sections(tmp_path):
    out = str(tmp_path / "report3.pdf")
    result = _mock_success_result()
    report_mod.generate_pdf_report(result, "JOB-001", "sample_die_layout.dxf", out)
    text = _extract_text(out)
    if text is None:
        return  # pypdf not installed in this env; presence/size already checked above
    for expected in [
        "CAD CONVERSION REPORT", "Job ID", "Conversion Summary",
        "Not-Converted", "Warnings", "Errors", "Assumptions",
        "3D Model Statistics", "STEP", "GLB",
    ]:
        assert expected in text, f"Missing section: {expected}"


def test_pdf_bytes_helper_returns_bytes():
    result = _mock_success_result()
    data = report_mod.generate_pdf_bytes(result, "JOB-001", "sample_die_layout.dxf")
    assert isinstance(data, (bytes, bytearray))
    assert data.startswith(b"%PDF-")
