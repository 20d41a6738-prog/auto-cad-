"""
Tests that a job records the username who ran it, and that the PDF
Conversion Report's Job Information section includes "Run by".
Uses lightweight mocks so this does not require ezdxf/cadquery/trimesh.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import report as report_mod

try:
    from backend.pipeline import LogEntry, Pipeline
    HAVE_PIPELINE = True
except ImportError:
    HAVE_PIPELINE = False
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


def _mock_result(run_by="Sai Teja", department="Computer Science", organization="ABC Engineering",
                  nlogs=1):
    logs = [LogEntry(f"10:00:{i:02d}", "SUCCESS", f"STEP generated and verified {i}", stage="exporting_step")
            for i in range(nlogs)]
    export_result = SimpleNamespace(step_path="/tmp/job/output/part.step",
                                     glb_path="/tmp/job/output/part.glb",
                                     step_size_bytes=20480, glb_size_bytes=10240,
                                     mesh_vertex_count=500, mesh_face_count=900,
                                     message="STEP written and verified.")
    validation = SimpleNamespace(valid=True, message="Geometry is valid.",
                                  solids=1, faces=12, edges=30, vertices=20,
                                  volume=1234.5, surface_area=987.6,
                                  bbox=(0, 0, 0, 100, 50, 10))
    return SimpleNamespace(
        success=True, job_id="JOB-010", job_dir="/tmp/job", logs=logs,
        inspection=None, feature_set=None, validation=validation,
        export_result=export_result, processing_time_sec=2.5, error_message="",
        run_by=run_by, department=department, organization=organization,
    )


# ---------------------------------------------------------------------
# Job-level tracking (only runnable when the full backend is installed)
# ---------------------------------------------------------------------
def test_pipeline_stores_run_by_username(tmp_path):
    if not HAVE_PIPELINE:
        return  # backend.pipeline needs ezdxf/cadquery/trimesh in this environment
    p = Pipeline(job_id="TEST-RUNBY-001", run_by="Sai Teja")
    assert p.run_by == "Sai Teja"


def test_pipeline_stores_department(tmp_path):
    if not HAVE_PIPELINE:
        return
    p = Pipeline(job_id="TEST-RUNBY-004", run_by="Sai Teja", department="Computer Science",
                 organization="ABC Engineering")
    assert p.department == "Computer Science"


def test_pipeline_stores_organization(tmp_path):
    if not HAVE_PIPELINE:
        return
    p = Pipeline(job_id="TEST-RUNBY-005", run_by="Sai Teja", department="Computer Science",
                 organization="ABC Engineering")
    assert p.organization == "ABC Engineering"


def test_pipeline_defaults_run_by_to_unknown(tmp_path):
    if not HAVE_PIPELINE:
        return
    p = Pipeline(job_id="TEST-RUNBY-002")
    assert p.run_by == "unknown"


def test_job_meta_file_records_run_by(tmp_path):
    if not HAVE_PIPELINE:
        return
    import json
    p = Pipeline(job_id="TEST-RUNBY-003", run_by="Sai Teja", department="Computer Science",
                 organization="ABC Engineering")
    meta_path = os.path.join(p.dirs["root"], "job_meta.json")
    assert os.path.exists(meta_path)
    meta = json.load(open(meta_path))
    assert meta["run_by"] == "Sai Teja"
    assert meta["job_id"] == "TEST-RUNBY-003"
    assert meta["department"] == "Computer Science"
    assert meta["organization"] == "ABC Engineering"


# ---------------------------------------------------------------------
# PDF report contains "Run by"
# ---------------------------------------------------------------------
def test_pdf_job_info_contains_run_by(tmp_path):
    out = str(tmp_path / "report.pdf")
    result = _mock_result(run_by="Sai Teja")
    report_mod.generate_pdf_report(result, "JOB-010", "sample_die_layout.dxf", out, run_by="Sai Teja",
                                    department="Computer Science", organization="ABC Engineering")
    with open(out, "rb") as f:
        pdf_bytes = f.read()
    assert pdf_bytes.startswith(b"%PDF-")

    try:
        from pypdf import PdfReader
    except ImportError:
        return
    text = "\n".join(page.extract_text() or "" for page in PdfReader(out).pages)
    assert "Run by" in text
    assert "Sai Teja" in text
    assert "Job ID" in text


def test_pdf_job_info_contains_department(tmp_path):
    out = str(tmp_path / "report_dept.pdf")
    result = _mock_result()
    report_mod.generate_pdf_report(result, "JOB-010", "sample_die_layout.dxf", out, run_by="Sai Teja",
                                    department="Computer Science", organization="ABC Engineering")
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    text = "\n".join(page.extract_text() or "" for page in PdfReader(out).pages)
    assert "Department" in text
    assert "Computer Science" in text


def test_pdf_job_info_contains_organization(tmp_path):
    out = str(tmp_path / "report_org.pdf")
    result = _mock_result()
    report_mod.generate_pdf_report(result, "JOB-010", "sample_die_layout.dxf", out, run_by="Sai Teja",
                                    department="Computer Science", organization="ABC Engineering")
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    text = "\n".join(page.extract_text() or "" for page in PdfReader(out).pages)
    assert "Organization" in text
    assert "ABC Engineering" in text


def test_pdf_falls_back_to_result_run_by_if_not_passed(tmp_path):
    out = str(tmp_path / "report2.pdf")
    result = _mock_result(run_by="Fallback User")
    report_mod.generate_pdf_report(result, "JOB-011", "sample_die_layout.dxf", out)
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    text = "\n".join(page.extract_text() or "" for page in PdfReader(out).pages)
    assert "Fallback User" in text


def test_pdf_falls_back_to_result_department_and_organization_if_not_passed(tmp_path):
    out = str(tmp_path / "report_fallback_dept.pdf")
    result = _mock_result(department="Mechanical Engineering", organization="XYZ Corp")
    report_mod.generate_pdf_report(result, "JOB-012", "sample_die_layout.dxf", out)
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    text = "\n".join(page.extract_text() or "" for page in PdfReader(out).pages)
    assert "Mechanical Engineering" in text
    assert "XYZ Corp" in text


def test_pdf_bytes_helper_accepts_run_by():
    result = _mock_result(run_by="Sai Teja")
    data = report_mod.generate_pdf_bytes(result, "JOB-010", "sample_die_layout.dxf", run_by="Sai Teja",
                                          department="Computer Science", organization="ABC Engineering")
    assert data.startswith(b"%PDF-")


# ---------------------------------------------------------------------
# PDF footer page numbering: "Page X of Y" with a correct, dynamically
# computed total page count — tested for 1-page-ish, and multi-page reports.
# ---------------------------------------------------------------------
def test_pdf_footer_uses_page_x_of_y_format(tmp_path):
    out = str(tmp_path / "report_pages_small.pdf")
    result = _mock_result(nlogs=1)
    report_mod.generate_pdf_report(result, "JOB-010", "sample_die_layout.dxf", out,
                                    run_by="Sai Teja", department="Computer Science",
                                    organization="ABC Engineering")
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    reader = PdfReader(out)
    total = len(reader.pages)
    text = "\n".join(pg.extract_text() or "" for pg in reader.pages)
    assert f"Page 1 of {total}" in text
    assert "Page 0 of" not in text  # never a raw/unset page number


def test_pdf_footer_total_page_count_scales_with_content(tmp_path):
    out_small = str(tmp_path / "report_small.pdf")
    out_large = str(tmp_path / "report_large.pdf")
    small_result = _mock_result(nlogs=1)
    large_result = _mock_result(nlogs=60)  # forces the event-log table onto extra pages

    report_mod.generate_pdf_report(small_result, "JOB-013", "small.dxf", out_small,
                                    run_by="Sai Teja", department="Computer Science",
                                    organization="ABC Engineering")
    report_mod.generate_pdf_report(large_result, "JOB-014", "large.dxf", out_large,
                                    run_by="Sai Teja", department="Computer Science",
                                    organization="ABC Engineering")
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    small_pages = len(PdfReader(out_small).pages)
    large_pages = len(PdfReader(out_large).pages)
    assert large_pages > small_pages  # total page count really is computed, not hardcoded

    small_text = "\n".join(pg.extract_text() or "" for pg in PdfReader(out_small).pages)
    large_text = "\n".join(pg.extract_text() or "" for pg in PdfReader(out_large).pages)
    assert f"Page 1 of {small_pages}" in small_text
    assert f"Page {small_pages} of {small_pages}" in small_text
    assert f"Page 1 of {large_pages}" in large_text
    assert f"Page {large_pages} of {large_pages}" in large_text
