# CAD Studio — DXF → Real 3D CAD Translator

A single-page Streamlit application implementing a professional, gated
6-step 2D→3D CAD translation workflow, built around a real supplied DXF
(`sample_die_layout.dxf` — a multi-view die-layout drawing with 320
entities across 8 layers).

**No mocking.** The pipeline reads real DXF geometry, builds a real OCCT
B-rep solid, exports a real, re-verified STEP file, tessellates a real GLB
mesh, and renders the actual generated geometry in a Three.js viewer.

---

## Workflow

```
1 Ready → 2 2D Files → 3 Translate → 4 3D Files → 5 Logs → 6 Close
```

Each step is gated — later steps are locked until the current one
completes successfully. The stepper stays visible at the top of the page
at all times.

---

## What the supplied DXF actually contains

`sample_die_layout.dxf` is a real AutoCAD R2004 (AC1018) multi-view
mechanical die-layout drawing:

| Property | Value |
|---|---|
| Entities | 320 (LINE ×163, DIMENSION ×101, TEXT ×18, INSERT ×15, CIRCLE ×14, HATCH ×5, LWPOLYLINE ×3, MULTILEADER ×1) |
| Layers | `0`, `CENTER`, `CONSTRUCTION`, `CONTRUCTION` (sic, typo in source file), `DIMENSION`, `HATCH`, `HIDDEN`, `LEVEL_50` |
| Units | Inches (`$INSUNITS=1`) |
| Bounding box | ~105 × 78 units |

This is **not** a clean single-outline part file. It mixes real
construction geometry with dimension leaders, hatch fills, centerlines,
hidden lines, and block inserts — exactly the kind of messy real-world
input the app is designed to handle honestly:

- The app **parses every entity for real** with `ezdxf` (not by file
  extension) and reports entity/layer statistics before anything else
  happens.
- A heuristic pre-selects the likely "real geometry" layers
  (`CONSTRUCTION`/`CONTRUCTION`) and excludes annotation-style layers
  (`DIMENSION`, `HATCH`, `CENTER`, `HIDDEN`) by name pattern — but the
  user can override the layer selection in Step 3, and the app **shows
  the live effect** of that choice (closed-polygon count, area) before
  you commit to running the translation.
- If a chosen layer selection does not close into a loop (e.g. the `0`
  layer, which only holds block `INSERT`s), the app fails **cleanly and
  visibly** at the "Detecting profiles" stage — it never invents a fake
  shape.
- Extrusion depth is **not present** in a 2D DXF. It is a required,
  user-configurable, clearly labeled assumption (Step 3), and it is
  echoed back in the model properties, logs, and job summary.

---

## Real backend architecture

```
backend/
    dxf_reader.py          real DXF parsing + structural validation (ezdxf)
    geometry_analyzer.py   entity -> line segments / circles, per layer
    profile_detector.py    shapely polygonize -> outer profile + holes
    solid_generator.py     CadQuery/OCCT extrusion + boolean hole cuts
    validator.py            OCCT BRepCheck_Analyzer + real B-rep metrics
    exporter.py              STEP (OCCT) + GLB (trimesh), both re-verified
    pipeline.py              orchestrates all stages, real logs, job dirs
    viewer.py                Three.js viewer HTML generator (loads real GLB)
```

Pipeline:

```
DXF → read → analyse → detect closed profiles → generate solid
    → validate (OCCT BRepCheck) → export STEP → export GLB → viewer
```

Every stage returns real, inspectable data. `pipeline.py` turns actual
stage outcomes into the log lines shown in Step 5 — logs are never
pre-scripted.

### CAD kernel

Solid modeling and STEP export use **CadQuery 2.x**, which wraps the
real **OCCT (OpenCascade)** kernel — the same kernel family used by
FreeCAD. This avoids depending on a separate FreeCAD installation while
still producing genuine, standards-compliant STEP AP214 files.

FreeCAD is optional. The sidebar detects whether a `freecad`/`freecadcmd`
executable is on `PATH` and shows Windows setup instructions if not — the
app does not require it and does not hard-code any machine-specific path.

### Output validation (Step 4 unlock conditions)

Before Step 4 unlocks, the pipeline has already:

1. Confirmed the STEP file exists and is non-empty.
2. **Re-imported** the STEP file with OCCT and confirmed it contains ≥1
   real solid (a `.step` extension alone proves nothing).
3. Run `BRepCheck_Analyzer` on the in-memory solid and confirmed
   topological validity, non-zero volume, and ≥1 solid body.
4. Tessellated to STL, converted to GLB with `trimesh`, and **re-loaded**
   the GLB to confirm it contains real vertices/faces.

If any of these checks fail, translation stops with a clear error and
Step 4 stays locked — never a silent fallback to placeholder geometry.

### 3D Viewer

A hand-built Three.js viewer (`backend/viewer.py`) is embedded via
`st.components.v1.html`. It loads the **actual generated GLB** (base64
data URI, no cube, no placeholder) and supports orbit, pan, zoom, fit,
isometric/front/top/right presets, shaded/wireframe toggling, edge
overlay, grid toggle, and fullscreen.

---

## Job management

```
jobs/
    JOB-001/
        input/        <- copy of the uploaded DXF (never overwritten)
        intermediate/
        output/        <- .step, .stl, .glb
        logs/
            translation.log
    JOB-002/
        ...
```

Each "Start Translation Job" allocates a new sequential `JOB-###` folder.
Existing jobs are never overwritten.

---

## Running locally (Windows / VS Code)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL Streamlit prints (typically `http://localhost:8501`).

> CadQuery's OCCT dependency (`cadquery-ocp`) is a large binary wheel.
> First install may take a few minutes.

---

## Tests

```bash
pip install pytest
pytest tests/ -v
```

`tests/test_pipeline.py` runs real (non-mocked) checks against
`sample_die_layout.dxf`: DXF-reader rejection of missing/empty/garbage
files, layer-filtered geometry extraction, closed-profile detection,
a full end-to-end pipeline run producing a verified STEP+GLB, and a
graceful-failure case (layer with no line geometry).

---

## Known limitations (by design, not hidden)

- The app extrudes a single 2D outline into a flat prismatic solid. It
  does not infer 3D features (bosses, pockets, drafts, fillets) that
  aren't representable as a 2D outline + holes — this is an inherent
  limitation of any 2D→3D DXF translation, not something this app
  papers over.
- Multi-view drawings (front/top/side views of the same part) are not
  automatically reconciled into one 3D shape. The app extrudes whichever
  layer(s) you select; if a DXF encodes multiple orthographic views on
  the same layer, you'll need to isolate the relevant view's layer(s) or
  pre-clean the DXF. This matches how the supplied `sample_die_layout.dxf`
  behaves — profile detection succeeds on `CONSTRUCTION`, but a
  production tool would still want per-view layer separation upstream.
