"""
report.py
Generates the single downloadable engineering-style PDF Conversion Report
for a completed (or failed) translation job, using ReportLab.

No external services are used. Everything in the report is derived from
the real PipelineResult produced by pipeline.py — no invented numbers.
"""
from __future__ import annotations
import io
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table,
    TableStyle, KeepTogether, HRFlowable,
)
from reportlab.pdfgen import canvas as pdfcanvas

BRAND_NAME = "CAD Studio"
BRAND_TAGLINE = "2D -> 3D CAD Translation Engine"
ACCENT = colors.HexColor("#1976d2")
DARK = colors.HexColor("#1c2733")
LIGHT_GREY = colors.HexColor("#f2f4f7")
HEADER_BG = colors.HexColor("#eaf1f8")     # light, professional CAD-style header band
HEADER_RULE = colors.HexColor("#a9c6e8")   # subtle divider line under the header band


def _draw_logo(c: pdfcanvas.Canvas, x: float, center_y: float, size: float = 14 * mm):
    """
    Simple isometric 3D-cube CAD Studio mark, drawn with vector primitives
    (no external image asset, no third-party IP). Three parallelogram faces
    (top / left / right) in different shades of the brand blue give it a
    3D/isometric look rather than a flat icon.

    `center_y` is the desired vertical center of the logo's bounding box
    (so it can be aligned precisely with adjacent header text), not the
    bottom-left corner.
    """
    c.saveState()
    top_color = colors.HexColor("#5b9bd5")
    left_color = colors.HexColor("#1f6fb2")
    right_color = colors.HexColor("#154f80")

    h = size            # overall footprint height
    w = size            # overall footprint width
    # The cube's own bounding box spans from -0.66h to +0.46h around its
    # construction origin, i.e. its box-center sits 0.10h above that origin.
    # Shift the origin down by 0.10h so the visible shape is truly centered
    # on the requested center_y.
    cx, cy = x + w / 2, center_y - h * 0.10

    # Top face (rhombus)
    top_pts = [
        (cx, cy + h * 0.46),
        (cx + w * 0.46, cy + h * 0.13),
        (cx, cy - h * 0.20),
        (cx - w * 0.46, cy + h * 0.13),
    ]
    p = c.beginPath()
    p.moveTo(*top_pts[0])
    for pt in top_pts[1:]:
        p.lineTo(*pt)
    p.close()
    c.setFillColor(top_color)
    c.drawPath(p, fill=1, stroke=0)

    # Left face (parallelogram)
    left_pts = [
        (cx - w * 0.46, cy + h * 0.13),
        (cx, cy - h * 0.20),
        (cx, cy - h * 0.66),
        (cx - w * 0.46, cy - h * 0.33),
    ]
    p = c.beginPath()
    p.moveTo(*left_pts[0])
    for pt in left_pts[1:]:
        p.lineTo(*pt)
    p.close()
    c.setFillColor(left_color)
    c.drawPath(p, fill=1, stroke=0)

    # Right face (parallelogram)
    right_pts = [
        (cx, cy - h * 0.20),
        (cx + w * 0.46, cy + h * 0.13),
        (cx + w * 0.46, cy - h * 0.33),
        (cx, cy - h * 0.66),
    ]
    p = c.beginPath()
    p.moveTo(*right_pts[0])
    for pt in right_pts[1:]:
        p.lineTo(*pt)
    p.close()
    c.setFillColor(right_color)
    c.drawPath(p, fill=1, stroke=0)
    c.restoreState()


class _NumberedCanvas(pdfcanvas.Canvas):
    """
    Canvas that defers footer page-number drawing until the document is
    fully built, so the footer can read 'Page X of Y' with a correctly
    computed total page count — works for 1, 2, 3, or any number of pages.
    """
    def __init__(self, *args, **kwargs):
        pdfcanvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_count(total_pages)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def _draw_page_count(self, total_pages):
        width, _ = A4
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#666f7a"))
        self.drawRightString(width - 14 * mm, 10 * mm, f"Page {self._pageNumber} of {total_pages}")
        self.restoreState()


def _header_footer(job_id: str, generated_at: str):
    def _draw(c: pdfcanvas.Canvas, doc):
        c.saveState()
        width, height = A4
        # Header band — light, professional CAD-style color (not a dark/strong band)
        c.setFillColor(HEADER_BG)
        c.rect(0, height - 22 * mm, width, 22 * mm, fill=1, stroke=0)
        c.setStrokeColor(HEADER_RULE)
        c.setLineWidth(0.8)
        c.line(0, height - 22 * mm, width, height - 22 * mm)

        _draw_logo(c, 14 * mm, height - 11 * mm, size=12 * mm)
        c.setFillColor(DARK)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(30 * mm, height - 9.4 * mm, BRAND_NAME)
        c.setFillColor(colors.HexColor("#4a5568"))
        c.setFont("Helvetica", 8.5)
        c.drawString(30 * mm, height - 14.6 * mm, BRAND_TAGLINE)
        c.setFillColor(DARK)
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(width - 14 * mm, height - 9.4 * mm, "CAD CONVERSION REPORT")
        c.setFillColor(colors.HexColor("#4a5568"))
        c.setFont("Helvetica", 8)
        c.drawRightString(width - 14 * mm, height - 14.6 * mm, f"Job ID: {job_id}")

        # Footer band (page number itself is drawn later by _NumberedCanvas
        # once the total page count is known)
        c.setFillColor(colors.HexColor("#666f7a"))
        c.setFont("Helvetica", 7.5)
        c.drawString(14 * mm, 10 * mm, f"Generated {generated_at} \u00b7 {BRAND_NAME} automated conversion report")
        c.setStrokeColor(colors.HexColor("#d7dce2"))
        c.setLineWidth(0.5)
        c.line(14 * mm, 13 * mm, width - 14 * mm, 13 * mm)
        c.restoreState()
    return _draw


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(name="H2", parent=ss["Heading2"], textColor=DARK,
                           spaceBefore=10, spaceAfter=4, fontSize=13))
    ss.add(ParagraphStyle(name="H3", parent=ss["Heading3"], textColor=ACCENT,
                           spaceBefore=6, spaceAfter=3, fontSize=10.5))
    ss.add(ParagraphStyle(name="Body9", parent=ss["BodyText"], fontSize=9, leading=12))
    ss.add(ParagraphStyle(name="Mono8", parent=ss["BodyText"], fontName="Courier",
                           fontSize=7.5, leading=9.5, textColor=colors.HexColor("#2b2f36")))
    ss.add(ParagraphStyle(name="EndNote", parent=ss["BodyText"], fontSize=9,
                           alignment=1, textColor=DARK, fontName="Helvetica-Bold"))
    ss.add(ParagraphStyle(name="EndSub", parent=ss["BodyText"], fontSize=7.5,
                           alignment=1, textColor=colors.HexColor("#8a93a6"),
                           fontName="Helvetica-Oblique"))
    return ss


def _kv_table(rows, col_widths=(45 * mm, 120 * mm)):
    t = Table(rows, colWidths=list(col_widths))
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), DARK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e4e7ec")),
    ]))
    return t


def _section_table(headers, data_rows, col_widths, small=False):
    if not data_rows:
        return None
    body_style = "Mono8" if small else "Body9"
    styles = _styles()
    wrapped = [[Paragraph(str(h), styles["H3"]) for h in headers]]
    for row in data_rows:
        wrapped.append([Paragraph(str(c), styles[body_style]) for c in row])
    t = Table(wrapped, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GREY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#e4e7ec")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def generate_pdf_report(result, job_id: str, input_filename: str, output_path: str,
                          run_by: str = "", department: str = "", organization: str = "") -> str:
    """
    Build the single PDF conversion report for a PipelineResult.
    `result` is a pipeline.PipelineResult (success or failure).
    `run_by`/`department`/`organization` are captured at job-start time;
    each falls back to the matching field on `result` if not passed explicitly.
    Returns output_path.
    """
    styles = _styles()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_by = run_by or getattr(result, "run_by", "") or "unknown"
    department = department or getattr(result, "department", "") or "Not specified"
    organization = organization or getattr(result, "organization", "") or "Not specified"

    doc = BaseDocTemplate(
        output_path, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=26 * mm, bottomMargin=17 * mm,
        title=f"{BRAND_NAME} Conversion Report - {job_id}",
        author=BRAND_NAME,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame],
                                        onPage=_header_footer(job_id, generated_at))])

    story = []
    status_txt = "SUCCESS" if result.success else "FAILED"
    status_color = colors.HexColor("#2e7d32") if result.success else colors.HexColor("#c62828")

    story.append(Paragraph("Job Information", styles["H2"]))
    now = datetime.now()
    job_info_rows = [
        ["Job ID", job_id],
        ["Run by", run_by],
        ["Department", department],
        ["Organization", organization],
        ["Date", now.strftime("%Y-%m-%d")],
        ["Time", now.strftime("%H:%M:%S")],
        ["Processing time", f"{result.processing_time_sec:.2f} s"],
        ["Status", Paragraph(f'<font color="{status_color.hexval()}"><b>{status_txt}</b></font>', styles["Body9"])],
    ]
    story.append(_kv_table(job_info_rows))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Conversion Summary", styles["H2"]))
    summary_rows = [
        ["Input file", input_filename],
        ["Date", now.strftime("%Y-%m-%d")],
        ["Timestamp", generated_at],
        ["Processing time", f"{result.processing_time_sec:.2f} s"],
        ["Status", Paragraph(f'<font color="{status_color.hexval()}"><b>{status_txt}</b></font>', styles["Body9"])],
    ]
    if not result.success:
        summary_rows.append(["Failure reason", result.error_message or "Unknown error"])
    story.append(_kv_table(summary_rows))
    story.append(Spacer(1, 4 * mm))

    # Drawing / entity information
    if result.inspection is not None:
        insp = result.inspection
        story.append(Paragraph("Source Drawing Information", styles["H2"]))
        rows = [
            ["DXF version", insp.dxf_version],
            ["Total entities", str(insp.total_entities)],
            ["Layers", str(len(insp.layer_names))],
            ["Units", str(insp.units)],
        ]
        if insp.bbox:
            rows.append(["Bounding box", f"X[{insp.bbox[0]:.2f}, {insp.bbox[2]:.2f}]  "
                                          f"Y[{insp.bbox[1]:.2f}, {insp.bbox[3]:.2f}]"])
        story.append(_kv_table(rows))
        story.append(Spacer(1, 4 * mm))

    # Converted features
    if result.feature_set is not None:
        story.append(Paragraph("Converted Features", styles["H2"]))
        fs = result.feature_set
        conv_rows = [[k, str(v)] for k, v in fs.summary.items()]
        t = _section_table(["Feature", "Count"], conv_rows, [90 * mm, 75 * mm])
        if t:
            story.append(t)
        else:
            story.append(Paragraph("No features were detected.", styles["Body9"]))
        story.append(Spacer(1, 4 * mm))

    # Not-converted items
    logs = result.logs or []
    not_converted = [e for e in logs if e.level == "NOT_CONVERTED"]
    story.append(Paragraph("Not-Converted Items", styles["H2"]))
    if not_converted:
        rows = [[e.entity or "-", e.reason or e.message, e.details or "May affect model completeness."]
                for e in not_converted]
        t = _section_table(["Item", "Reason not converted", "Impact"], rows,
                            [40 * mm, 65 * mm, 60 * mm], small=True)
        story.append(t)
    else:
        story.append(Paragraph("None. All detected geometry was converted.", styles["Body9"]))
    story.append(Spacer(1, 4 * mm))

    # Warnings
    warnings = [e for e in logs if e.level == "WARNING"]
    story.append(Paragraph("Warnings", styles["H2"]))
    if warnings:
        rows = [[e.timestamp, e.stage or "-", e.message] for e in warnings]
        story.append(_section_table(["Time", "Stage", "Message"], rows, [20 * mm, 40 * mm, 105 * mm], small=True))
    else:
        story.append(Paragraph("No warnings were raised.", styles["Body9"]))
    story.append(Spacer(1, 4 * mm))

    # Errors
    errors = [e for e in logs if e.level == "ERROR"]
    story.append(Paragraph("Errors", styles["H2"]))
    if errors:
        rows = [[e.timestamp, e.stage or "-", e.message] for e in errors]
        story.append(_section_table(["Time", "Stage", "Message"], rows, [20 * mm, 40 * mm, 105 * mm], small=True))
    else:
        story.append(Paragraph("No errors were raised.", styles["Body9"]))
    story.append(Spacer(1, 4 * mm))

    # Assumptions
    assumptions = [e for e in logs if e.level == "ASSUMPTION"]
    story.append(Paragraph("Assumptions", styles["H2"]))
    if assumptions:
        rows = [[e.entity or "-", e.message] for e in assumptions]
        story.append(_section_table(["Parameter", "Assumption"], rows, [40 * mm, 125 * mm], small=True))
    else:
        story.append(Paragraph("No assumptions were required.", styles["Body9"]))
    story.append(Spacer(1, 4 * mm))

    # 3D model statistics + validation
    if result.validation is not None:
        v = result.validation
        story.append(Paragraph("3D Model Statistics &amp; OCCT Validation", styles["H2"]))
        b = v.bbox
        rows = [
            ["Solids", str(v.solids)],
            ["Faces", str(v.faces)],
            ["Edges", str(v.edges)],
            ["Vertices", str(v.vertices)],
            ["Volume", f"{v.volume:.3f}"],
            ["Surface area", f"{v.surface_area:.3f}"],
            ["Bounding box", f"X[{b[0]:.2f},{b[3]:.2f}] Y[{b[1]:.2f},{b[4]:.2f}] Z[{b[2]:.2f},{b[5]:.2f}]"],
            ["OCCT BRepCheck", "VALID" if v.valid else "INVALID"],
            ["Validation message", v.message],
        ]
        story.append(_kv_table(rows))
        story.append(Spacer(1, 4 * mm))

    # STEP / GLB status
    story.append(Paragraph("STEP &amp; GLB Export Status", styles["H2"]))
    if result.export_result is not None:
        ex = result.export_result
        rows = [
            ["STEP file", os.path.basename(ex.step_path) if ex.step_path else "not generated"],
            ["STEP size", f"{ex.step_size_bytes/1024:.1f} KB" if ex.step_path else "-"],
            ["GLB file", os.path.basename(ex.glb_path) if ex.glb_path else "not generated"],
            ["GLB size", f"{ex.glb_size_bytes/1024:.1f} KB" if ex.glb_path else "-"],
            ["Mesh vertices", str(ex.mesh_vertex_count)],
            ["Mesh faces", str(ex.mesh_face_count)],
            ["Export message", ex.message],
        ]
        story.append(_kv_table(rows))
    else:
        story.append(Paragraph("STEP/GLB export was not reached before the job stopped.", styles["Body9"]))
    story.append(Spacer(1, 4 * mm))

    # Full structured event log (compact)
    story.append(Paragraph("Full Structured Event Log", styles["H2"]))
    if logs:
        rows = [[e.timestamp, e.level, e.stage or "-", e.message] for e in logs]
        story.append(_section_table(["Time", "Level", "Stage", "Message"], rows,
                                     [16 * mm, 22 * mm, 32 * mm, 95 * mm], small=True))
    else:
        story.append(Paragraph("No log events recorded.", styles["Body9"]))

    # Professional report close: 5 blank lines of space, then a closing mark.
    story.append(Spacer(1, 5 * 12))  # 5 lines at the body-text leading (12pt)
    story.append(KeepTogether([
        HRFlowable(width="35%", thickness=0.8, color=colors.HexColor("#a9c6e8"),
                   hAlign="CENTER", spaceAfter=6),
        Paragraph("End of Report", styles["EndNote"]),
        Paragraph(f"{BRAND_NAME} &middot; Automated 2D&rarr;3D CAD Conversion Report &middot; "
                  f"{len(logs)} log event(s) recorded", styles["EndSub"]),
    ]))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return output_path


def generate_pdf_bytes(result, job_id: str, input_filename: str, run_by: str = "",
                         department: str = "", organization: str = "") -> bytes:
    """Convenience wrapper returning PDF bytes without writing a permanent file
    (used by tests / in-memory download buttons when a path isn't needed)."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        generate_pdf_report(result, job_id, input_filename, tmp_path, run_by=run_by,
                             department=department, organization=organization)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
