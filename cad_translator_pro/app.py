"""
CAD Studio - Streamlit single-page 6-step DXF -> 3D CAD translation app.
Real backend: ezdxf + shapely + CadQuery/OCCT + trimesh. No mock processing.
Run with: streamlit run app.py
"""
import os
import io
import time
import shutil
import platform
import subprocess
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from backend import dxf_reader, geometry_analyzer, profile_detector, exporter
from backend.pipeline import Pipeline, STAGES, STAGE_LABELS, JOBS_ROOT
from backend.viewer import build_viewer_html
from backend.report import generate_pdf_bytes
from backend.privacy import PRIVACY_NOTICE_MD, delete_job_data
from backend.auth import verify_login

CUBE_LOGO_SVG = """
<svg width="34" height="34" viewBox="0 0 34 34" style="vertical-align:-8px; margin-right:6px;">
  <polygon points="17,2 29,9 17,16 5,9" fill="#5b9bd5"/>
  <polygon points="5,9 17,16 17,30 5,23" fill="#1f6fb2"/>
  <polygon points="29,9 17,16 17,30 29,23" fill="#154f80"/>
</svg>
"""

APP_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="CAD Studio", layout="wide", page_icon="🛠️")

with open(os.path.join(APP_DIR, "style.css")) as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# ----------------------------------------------------------------------
# Session state initialisation
# ----------------------------------------------------------------------
DEFAULTS = {
    "step": 1,
    "job_id": None,
    "pipeline": None,
    "upload_path": None,
    "upload_name": None,
    "inspection": None,
    "analysis": None,
    "selected_layers": [],
    "extrusion_depth": 10.0,
    "pipeline_result": None,
    "translation_running": False,
    "job_start_time": None,
}
AUTH_DEFAULTS = {
    "authenticated": False,
    "username": None,
    "display_name": None,
    "department": None,
    "organization": None,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v
for k, v in AUTH_DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


def reset_workflow():
    for k, v in DEFAULTS.items():
        st.session_state[k] = v


def goto(step: int):
    st.session_state.step = step


# ----------------------------------------------------------------------
# Login gate — everything below this point requires authentication.
# The 6-step workflow is untouched; this only wraps it.
# ----------------------------------------------------------------------
if not st.session_state.authenticated:
    st.markdown(f"""
    <div class="cad-header">
        <div>
            <h1>{CUBE_LOGO_SVG} CAD STUDIO</h1>
            <div class="cad-sub">DXF &rarr; Real 3D Solid &rarr; STEP / GLB</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown('<div class="cad-panel"><h3>🔐 Sign in</h3>', unsafe_allow_html=True)
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            department = st.text_input("Department")
            organization = st.text_input("Organization")
            submitted = st.form_submit_button("Login", type="primary", use_container_width=True)
        if submitted:
            ok, display_name = verify_login(username.strip(), password)
            if ok:
                st.session_state.authenticated = True
                st.session_state.username = username.strip()
                st.session_state.display_name = display_name
                st.session_state.department = department.strip() or "Not specified"
                st.session_state.organization = organization.strip() or "Not specified"
                st.rerun()
            else:
                st.error("Invalid username or password.")
        st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

with st.sidebar:
    st.markdown("### 👤 Session")
    st.write(f"**Logged in as:** {st.session_state.display_name or st.session_state.username}")
    st.write(f"**Department:** {st.session_state.department}")
    st.write(f"**Organization:** {st.session_state.organization}")
    if st.session_state.job_id:
        st.write(f"**Current job:** {st.session_state.job_id}")
        st.write(f"**Run by:** {st.session_state.username}")
    if st.button("Logout"):
        for k, v in AUTH_DEFAULTS.items():
            st.session_state[k] = v
        reset_workflow()
        st.rerun()


# ----------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------
st.markdown(f"""
<div class="cad-header">
    <div>
        <h1>{CUBE_LOGO_SVG} CAD STUDIO</h1>
        <div class="cad-sub">DXF &rarr; Real 3D Solid &rarr; STEP / GLB &middot; ezdxf + shapely + OCCT (CadQuery) + trimesh</div>
    </div>
    <div class="cad-badge">ENGINE: OCCT / CadQuery {__import__('cadquery').__version__}</div>
</div>
""", unsafe_allow_html=True)

# ----------------------------------------------------------------------
# Stepper
# ----------------------------------------------------------------------
STEP_DEFS = [
    (1, "Ready"),
    (2, "2D Files"),
    (3, "Translate"),
    (4, "3D Files"),
    (5, "Logs"),
    (6, "Close"),
]

current = st.session_state.step
html = ['<div class="stepper-wrap">']
for num, label in STEP_DEFS:
    if num < current:
        cls, icon = "step-done", "✓"
    elif num == current:
        cls, icon = "step-active", str(num)
    else:
        cls, icon = "step-locked", "🔒"
    html.append(
        f'<div class="step-item {cls}">'
        f'<div class="step-num">{icon}</div>'
        f'<div class="step-label">{num} {label}</div>'
        f'</div>'
    )
html.append('</div>')
st.markdown("".join(html), unsafe_allow_html=True)


def panel_start(title):
    st.markdown(f'<div class="cad-panel"><h3>{title}</h3>', unsafe_allow_html=True)


def panel_end():
    st.markdown('</div>', unsafe_allow_html=True)


# ========================================================================
# STEP 1 — READY TO TRANSLATE
# ========================================================================
if st.session_state.step == 1:
    panel_start("Step 1 &middot; Ready to Translate")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.write("**Application:** CAD Studio — DXF to 3D CAD Translator")
        st.write("**Engine status:** ezdxf, shapely, CadQuery/OCCT and trimesh are loaded and ready.")
        st.write("**Workflow:** Ready → 2D Files → Translate → 3D Files → Logs → Close")
        st.write(f"**Run by:** {st.session_state.username}")
        st.write(f"**Department:** {st.session_state.department}")
        st.write(f"**Organization:** {st.session_state.organization}")
    with col2:
        st.markdown(
            '<div class="metric-box"><div class="m-label">Status</div>'
            '<div class="m-value" style="color:#4caf50;">READY</div></div>',
            unsafe_allow_html=True,
        )
    st.write("")
    with st.expander("🔒 Data Privacy & Processing Notice", expanded=False):
        st.markdown(PRIVACY_NOTICE_MD)
    st.write("")
    if st.button("▶ Start Translation Job", type="primary"):
        pipeline = Pipeline(run_by=st.session_state.username,
                             department=st.session_state.department,
                             organization=st.session_state.organization)
        st.session_state.pipeline = pipeline
        st.session_state.job_id = pipeline.job_id
        st.session_state.job_start_time = time.time()
        goto(2)
        st.rerun()
    panel_end()

# ========================================================================
# STEP 2 — 2D FILES LOCATION (upload + real validation)
# ========================================================================
elif st.session_state.step == 2:
    panel_start(f"Step 2 &middot; 2D Files Location — Job {st.session_state.job_id}")

    uploaded = st.file_uploader(
        "Drop DXF file(s) here or click to browse",
        type=["dxf"],
        accept_multiple_files=True,
        help="Only .dxf files are accepted. The file is parsed and validated for real (not just checked by extension).",
    )

    if uploaded:
        # We process the first valid file as the active job input;
        # additional files are listed for context.
        st.markdown("**Uploaded files**")
        for uf in uploaded:
            size_kb = len(uf.getvalue()) / 1024
            st.write(f"- `{uf.name}` &middot; {size_kb:.1f} KB", unsafe_allow_html=True)

        active_file = uploaded[0]
        tmp_path = os.path.join(APP_DIR, "jobs", "_incoming")
        os.makedirs(tmp_path, exist_ok=True)
        save_path = os.path.join(tmp_path, active_file.name)
        with open(save_path, "wb") as f:
            f.write(active_file.getvalue())

        try:
            inspection, doc = dxf_reader.inspect(save_path)
            st.session_state.upload_path = save_path
            st.session_state.upload_name = active_file.name
            st.session_state.inspection = inspection
            st.session_state._doc = doc  # kept only for this run (not serialized)

            st.success(f"Valid DXF — {inspection.dxf_version}, {inspection.total_entities} entities parsed.")

            m1, m2, m3, m4 = st.columns(4)
            m1.markdown(f'<div class="metric-box"><div class="m-label">Entities</div><div class="m-value">{inspection.total_entities}</div></div>', unsafe_allow_html=True)
            m2.markdown(f'<div class="metric-box"><div class="m-label">Layers</div><div class="m-value">{len(inspection.layer_names)}</div></div>', unsafe_allow_html=True)
            m3.markdown(f'<div class="metric-box"><div class="m-label">Units</div><div class="m-value">{inspection.units}</div></div>', unsafe_allow_html=True)
            m4.markdown(f'<div class="metric-box"><div class="m-label">DXF Ver</div><div class="m-value">{inspection.dxf_version}</div></div>', unsafe_allow_html=True)

            st.write("")
            colA, colB = st.columns(2)
            with colA:
                st.write("**Geometry types present**")
                st.table({"Entity type": list(inspection.entity_type_counts.keys()),
                          "Count": list(inspection.entity_type_counts.values())})
            with colB:
                st.write("**Layers**")
                st.table({"Layer": list(inspection.layer_entity_counts.keys()),
                          "Entities": list(inspection.layer_entity_counts.values())})

            if inspection.bbox:
                st.write(
                    f"**Bounding box:** X [{inspection.bbox[0]:.3f}, {inspection.bbox[2]:.3f}]  "
                    f"Y [{inspection.bbox[1]:.3f}, {inspection.bbox[3]:.3f}]  "
                    f"&middot; Width {inspection.width:.3f} &middot; Height {inspection.height:.3f}",
                    unsafe_allow_html=True,
                )
            for w in inspection.warnings:
                st.warning(w)

        except dxf_reader.DXFReadError as e:
            st.session_state.upload_path = None
            st.session_state.inspection = None
            st.error(f"DXF validation failed: {e}")

    can_continue = st.session_state.inspection is not None and st.session_state.inspection.valid
    st.write("")
    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("← Back"):
            goto(1)
            st.rerun()
    with c2:
        if st.button("Continue →", disabled=not can_continue, type="primary"):
            goto(3)
            st.rerun()
    panel_end()

# ========================================================================
# STEP 3 — TRANSLATE (real backend pipeline)
# ========================================================================
elif st.session_state.step == 3:
    panel_start(f"Step 3 &middot; Translate — Job {st.session_state.job_id}")

    doc = st.session_state.get("_doc")
    if doc is None:
        st.error("No parsed DXF document available. Please go back to Step 2.")
    else:
        analysis_all = geometry_analyzer.analyze(doc, None)
        st.write("**Select the layer(s) that contain real part geometry** "
                 "(construction/outline lines). Dimension, hatch, center and hidden "
                 "layers are pre-excluded by heuristic but you can override this.")

        default_sel = analysis_all.recommended_layers or analysis_all.layer_names
        selected_layers = st.multiselect(
            "Geometry layers to use for profile detection",
            options=analysis_all.layer_names,
            default=default_sel,
        )
        st.caption(f"Excluded by default (annotation-like): {', '.join(analysis_all.excluded_layers) or 'none'}")

        # Live preview of profile detection with current layer selection
        preview_analysis = geometry_analyzer.analyze(doc, selected_layers or None)
        preview_detection = profile_detector.detect(preview_analysis.segments, preview_analysis.circles)

        if preview_detection.success:
            st.success(preview_detection.message)
        else:
            st.warning(preview_detection.message)

        st.markdown(
            '<div class="assumption-box">⚠ ASSUMPTION REQUIRED: A 2D DXF contains no extrusion '
            'depth. You must supply one explicitly below. It will be recorded as an assumption '
            'in the job log and shown in the model properties.</div>',
            unsafe_allow_html=True,
        )
        depth = st.number_input(
            "Extrusion Depth (mm)", min_value=0.1, max_value=10000.0,
            value=st.session_state.extrusion_depth, step=1.0,
        )
        st.session_state.extrusion_depth = depth
        st.session_state.selected_layers = selected_layers

        st.write("")
        run_disabled = not preview_detection.success or st.session_state.translation_running

        if st.button("⚙ Run Translation", type="primary", disabled=run_disabled):
            st.session_state.translation_running = True
            progress_area = st.empty()
            stage_area = st.empty()

            def render_stage_progress(stage_status):
                lines = []
                for s in STAGES:
                    label = STAGE_LABELS[s]
                    status = stage_status.get(s, "pending")
                    if status == "done":
                        lines.append(f"✓ {label}")
                    elif status == "active":
                        lines.append(f"→ {label}")
                    elif status == "error":
                        lines.append(f"✗ {label}")
                    else:
                        lines.append(f"○ {label}")
                stage_area.code("\n".join(lines))

            render_stage_progress({s: "pending" for s in STAGES})

            pipeline: Pipeline = st.session_state.pipeline
            with st.spinner("Running real DXF → solid → STEP → GLB pipeline..."):
                result = pipeline.run(
                    st.session_state.upload_path,
                    selected_layers or None,
                    st.session_state.extrusion_depth,
                )
            render_stage_progress(result.stage_status)
            st.session_state.pipeline_result = result
            st.session_state.translation_running = False

            if result.success:
                st.success("Translation completed successfully — real STEP and GLB generated and verified.")
                time.sleep(0.4)
                goto(4)
                st.rerun()
            else:
                st.error(f"Translation failed: {result.error_message}")

    st.write("")
    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("← Back", key="back3"):
            goto(2)
            st.rerun()
    panel_end()

# ========================================================================
# STEP 4 — 3D FILES + VIEWER
# ========================================================================
elif st.session_state.step == 4:
    result = st.session_state.pipeline_result
    panel_start(f"Step 4 &middot; 3D Files &amp; Viewer — Job {st.session_state.job_id}")

    if result is None or not result.success:
        st.error("No successful translation result available. Please go back and run translation.")
    else:
        export_result = result.export_result
        validation = result.validation

        st.write("**Live CAD Viewer** — actual generated geometry (rotate / zoom / pan / views below).")
        html = build_viewer_html(export_result.glb_path, height=520)
        components.html(html, height=540, scrolling=False)

        st.write("")
        st.write("**Model Properties** (computed from actual OCCT geometry)")
        b = validation.bbox
        width = b[3] - b[0]
        depth_y = b[4] - b[1]
        height_z = b[5] - b[2]

        m = st.columns(4)
        m[0].markdown(f'<div class="metric-box"><div class="m-label">Solids</div><div class="m-value">{validation.solids}</div></div>', unsafe_allow_html=True)
        m[1].markdown(f'<div class="metric-box"><div class="m-label">Faces</div><div class="m-value">{validation.faces}</div></div>', unsafe_allow_html=True)
        m[2].markdown(f'<div class="metric-box"><div class="m-label">Edges</div><div class="m-value">{validation.edges}</div></div>', unsafe_allow_html=True)
        m[3].markdown(f'<div class="metric-box"><div class="m-label">Vertices</div><div class="m-value">{validation.vertices}</div></div>', unsafe_allow_html=True)

        m2 = st.columns(4)
        m2[0].markdown(f'<div class="metric-box"><div class="m-label">Width (X)</div><div class="m-value">{width:.2f}</div></div>', unsafe_allow_html=True)
        m2[1].markdown(f'<div class="metric-box"><div class="m-label">Depth (Y)</div><div class="m-value">{depth_y:.2f}</div></div>', unsafe_allow_html=True)
        m2[2].markdown(f'<div class="metric-box"><div class="m-label">Height (Z)</div><div class="m-value">{height_z:.2f}</div></div>', unsafe_allow_html=True)
        m2[3].markdown(f'<div class="metric-box"><div class="m-label">Volume</div><div class="m-value">{validation.volume:.2f}</div></div>', unsafe_allow_html=True)

        m3 = st.columns(4)
        m3[0].markdown(f'<div class="metric-box"><div class="m-label">Surface Area</div><div class="m-value">{validation.surface_area:.2f}</div></div>', unsafe_allow_html=True)
        m3[1].markdown(f'<div class="metric-box"><div class="m-label">STEP Size</div><div class="m-value">{export_result.step_size_bytes/1024:.1f} KB</div></div>', unsafe_allow_html=True)
        m3[2].markdown(f'<div class="metric-box"><div class="m-label">GLB Size</div><div class="m-value">{export_result.glb_size_bytes/1024:.1f} KB</div></div>', unsafe_allow_html=True)
        m3[3].markdown(f'<div class="metric-box"><div class="m-label">Mesh Faces</div><div class="m-value">{export_result.mesh_face_count}</div></div>', unsafe_allow_html=True)

        st.write("")
        for a in result.solid_result.assumptions:
            st.markdown(f'<div class="assumption-box">⚠ ASSUMPTION: {a}</div>', unsafe_allow_html=True)

        st.write("**Output files**")
        st.write(f"- `{os.path.basename(export_result.step_path)}` — {export_result.step_size_bytes/1024:.1f} KB")
        st.write(f"- `{os.path.basename(export_result.glb_path)}` — {export_result.glb_size_bytes/1024:.1f} KB")

    st.write("")
    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("← Back", key="back4"):
            goto(3)
            st.rerun()
    with c2:
        if st.button("Continue to Logs →", type="primary", disabled=(result is None or not result.success)):
            goto(5)
            st.rerun()
    panel_end()

# ========================================================================
# STEP 5 — LOGS
# ========================================================================
elif st.session_state.step == 5:
    result = st.session_state.pipeline_result
    panel_start(f"Step 5 &middot; Logs — Job {st.session_state.job_id}")
    if result is not None:
        st.write(f"**Run by:** {getattr(result, 'run_by', st.session_state.username)}")

    if result is None:
        st.info("No logs yet.")
    else:
        logs = result.logs
        converted_events = [e for e in logs if e.level == "SUCCESS"]
        not_converted_events = [e for e in logs if e.level == "NOT_CONVERTED"]
        warning_events = [e for e in logs if e.level == "WARNING"]
        error_events = [e for e in logs if e.level == "ERROR"]
        assumption_events = [e for e in logs if e.level == "ASSUMPTION"]

        def render_log_lines(events, empty_msg):
            if not events:
                st.info(empty_msg)
                return
            lines = []
            for e in events:
                extra = ""
                if e.entity:
                    extra += f" &middot; <b>{e.entity}</b>"
                if e.reason:
                    extra += f" &middot; reason: {e.reason}"
                lines.append(
                    f'<div class="log-line log-{e.level}">[{e.timestamp}] {e.level} '
                    f'({e.stage or "-"}){extra} — {e.message}</div>'
                )
            st.markdown('<div class="cad-panel" style="background:#111318;">' + "".join(lines) + '</div>',
                         unsafe_allow_html=True)

        tab_live, tab_conv, tab_notconv, tab_warn, tab_err, tab_assume, tab_valid = st.tabs(
            ["Live Logs", "Converted", "Not Converted", "Warnings", "Errors", "Assumptions", "Validation"]
        )
        with tab_live:
            render_log_lines(logs, "No log events recorded.")
        with tab_conv:
            render_log_lines(converted_events, "No successful conversion events recorded.")
        with tab_notconv:
            if not not_converted_events:
                st.success("None — all detected geometry was converted.")
            else:
                for e in not_converted_events:
                    st.markdown(
                        f'<div class="assumption-box">⚠ <b>{e.entity or "Item"}</b> — '
                        f'not converted: {e.reason or e.message}. '
                        f'Impact: {e.details or "May result in missing geometry in the 3D model."}</div>',
                        unsafe_allow_html=True,
                    )
        with tab_warn:
            render_log_lines(warning_events, "No warnings were raised.")
        with tab_err:
            render_log_lines(error_events, "No errors were raised.")
        with tab_assume:
            render_log_lines(assumption_events, "No assumptions were required.")
        with tab_valid:
            if result.validation is not None:
                v = result.validation
                st.write(f"**OCCT BRepCheck:** {'✓ VALID' if v.valid else '✗ INVALID'}")
                st.write(v.message)
                st.write(f"Solids: {v.solids} · Faces: {v.faces} · Edges: {v.edges} · "
                         f"Vertices: {v.vertices} · Volume: {v.volume:.2f} · "
                         f"Surface area: {v.surface_area:.2f}")
            else:
                st.info("No validation result available.")

        st.write("")
        st.write("**Conversion Report**")
        try:
            pdf_bytes = generate_pdf_bytes(
                result, st.session_state.job_id, st.session_state.upload_name or "input.dxf",
                run_by=getattr(result, "run_by", st.session_state.username),
                department=getattr(result, "department", st.session_state.department),
                organization=getattr(result, "organization", st.session_state.organization),
            )
            st.download_button(
                "⬇ Download PDF Conversion Report", pdf_bytes,
                file_name=f"{st.session_state.job_id}_conversion_report.pdf",
                mime="application/pdf", type="primary",
            )
        except Exception as e:
            st.error(f"Could not generate PDF report: {e}")

    st.write("")
    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("← Back", key="back5"):
            goto(4)
            st.rerun()
    with c2:
        if st.button("Continue to Close →", type="primary", disabled=(result is None or not result.success)):
            goto(6)
            st.rerun()
    panel_end()

# ========================================================================
# STEP 6 — CLOSE
# ========================================================================
elif st.session_state.step == 6:
    result = st.session_state.pipeline_result
    panel_start(f"Step 6 &middot; Close Job — {st.session_state.job_id}")

    if result and result.success:
        elapsed = result.processing_time_sec
        st.markdown('<h2 style="color:#66bb6a;">✓ TRANSLATION COMPLETE</h2>', unsafe_allow_html=True)
        st.write(f"**Job ID:** {st.session_state.job_id}  |  **Run by:** "
                 f"{getattr(result, 'run_by', st.session_state.username)}")

        c1, c2 = st.columns(2)
        with c1:
            st.write("**Input**")
            st.write(f"- {st.session_state.upload_name}")
        with c2:
            st.write("**Output**")
            st.write(f"- {os.path.basename(result.export_result.step_path)}")
            st.write(f"- {os.path.basename(result.export_result.glb_path)}")

        st.write("**Status:** ✓ Valid CAD geometry (OCCT BRepCheck passed)")

        m = st.columns(4)
        m[0].markdown(f'<div class="metric-box"><div class="m-label">Processing Time</div><div class="m-value">{elapsed:.2f}s</div></div>', unsafe_allow_html=True)
        m[1].markdown(f'<div class="metric-box"><div class="m-label">Source Files</div><div class="m-value">1</div></div>', unsafe_allow_html=True)
        m[2].markdown(f'<div class="metric-box"><div class="m-label">Processed OK</div><div class="m-value">1</div></div>', unsafe_allow_html=True)
        m[3].markdown(f'<div class="metric-box"><div class="m-label">Failed</div><div class="m-value">0</div></div>', unsafe_allow_html=True)

        st.write("")
        st.write("**Downloads**")
        with open(result.export_result.step_path, "rb") as f:
            st.download_button("⬇ Download STEP", f.read(),
                                file_name=os.path.basename(result.export_result.step_path),
                                mime="application/step")
        with open(result.export_result.glb_path, "rb") as f:
            st.download_button("⬇ Download GLB", f.read(),
                                file_name=os.path.basename(result.export_result.glb_path),
                                mime="model/gltf-binary")
        try:
            pdf_bytes = generate_pdf_bytes(
                result, st.session_state.job_id, st.session_state.upload_name or "input.dxf",
                run_by=getattr(result, "run_by", st.session_state.username),
                department=getattr(result, "department", st.session_state.department),
                organization=getattr(result, "organization", st.session_state.organization),
            )
            st.download_button("⬇ Download PDF Conversion Report", pdf_bytes,
                                file_name=f"{st.session_state.job_id}_conversion_report.pdf",
                                mime="application/pdf")
        except Exception as e:
            st.error(f"Could not generate PDF report: {e}")

        if result.stage_status.get("classifying_features") != "error" and any(
            e.level == "NOT_CONVERTED" for e in result.logs
        ):
            st.warning("Completed with warnings: one or more entities were not converted. "
                       "See the Not Converted tab in Step 5 or the PDF report for details.")
        else:
            st.write("**Status:** ✓ Conversion completed successfully with no unconverted entities.")
    else:
        st.warning("Job did not complete successfully; nothing to close out.")

    st.write("")
    with st.expander("🔒 Job Data & Privacy"):
        st.markdown(PRIVACY_NOTICE_MD)
        st.write("")
        if st.session_state.job_id:
            if st.button("🗑 Delete Job Data (permanent)", key="delete_job_data"):
                ok, msg = delete_job_data(st.session_state.job_id)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    st.write("")
    if st.button("Close Job", type="primary"):
        reset_workflow()
        st.rerun()
    panel_end()

# ----------------------------------------------------------------------
# Sidebar — environment / FreeCAD detection info
# ----------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Engine status")
    try:
        import cadquery as cq
        st.success(f"CadQuery / OCCT: {cq.__version__}")
    except Exception as e:
        st.error(f"CadQuery unavailable: {e}")

    freecad_path = shutil.which("freecad") or shutil.which("FreeCAD") or shutil.which("freecadcmd")
    if freecad_path:
        st.success(f"FreeCAD found: {freecad_path}")
    else:
        st.info(
            "FreeCAD not detected on PATH. Not required — this app uses "
            "CadQuery's bundled OCCT kernel directly for solid modeling and "
            "STEP export. FreeCAD is an optional alternative backend."
        )
        with st.expander("Windows FreeCAD setup (optional)"):
            st.markdown(
                "1. Download FreeCAD from https://www.freecad.org/downloads.php\n"
                "2. Install it (default path: `C:\\Program Files\\FreeCAD 0.21\\bin`)\n"
                "3. Add that `bin` folder to your Windows PATH, or set an "
                "environment variable `FREECAD_PATH` pointing to `freecadcmd.exe`\n"
                "4. Restart your terminal / VS Code so PATH changes apply"
            )

    st.markdown("---")
    st.markdown("### Job")
    st.write(f"ID: `{st.session_state.job_id or '—'}`")
    st.write(f"Step: {st.session_state.step} / 6")

    st.markdown("---")
    st.markdown("### All jobs")
    if os.path.exists(JOBS_ROOT):
        job_dirs = sorted([d for d in os.listdir(JOBS_ROOT) if d.startswith("JOB-")])
        for jd in job_dirs[-10:]:
            st.caption(jd)
