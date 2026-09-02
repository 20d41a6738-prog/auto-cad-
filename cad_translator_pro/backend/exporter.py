"""
exporter.py
Exports the validated OCCT solid to:
  - STEP (AP214) via CadQuery's native OCCT STEP writer
  - GLB via an intermediate STL tessellation loaded/converted with trimesh

Both outputs are re-opened and sanity-checked after writing (non-empty,
parses back, contains real mesh/shape data) - a .step extension alone is
never treated as proof of a valid file.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
import cadquery as cq
import trimesh


@dataclass
class ExportResult:
    success: bool
    message: str
    step_path: str | None = None
    glb_path: str | None = None
    step_size_bytes: int = 0
    glb_size_bytes: int = 0
    mesh_vertex_count: int = 0
    mesh_face_count: int = 0


def export_step(solid_wp: cq.Workplane, out_path: str) -> tuple[bool, str]:
    try:
        cq.exporters.export(solid_wp, out_path, exportType="STEP")
    except Exception as e:
        return False, f"STEP export raised an exception: {e}"

    if not os.path.exists(out_path):
        return False, "STEP export did not produce a file."
    if os.path.getsize(out_path) == 0:
        return False, "STEP file was written but is empty."

    # Re-open with CadQuery/OCCT to prove the file is a real, loadable STEP model
    try:
        reimported = cq.importers.importStep(out_path)
        if reimported.val() is None:
            return False, "STEP file exists but does not contain a valid shape when re-imported."
        solids = reimported.solids().size()
        if solids == 0:
            return False, "STEP file re-imported but contains zero solids."
    except Exception as e:
        return False, f"STEP file could not be re-imported/validated: {e}"

    return True, f"STEP written and verified ({solids} solid(s) confirmed by re-import)."


def export_glb(solid_wp: cq.Workplane, stl_intermediate_path: str, glb_path: str,
                tolerance: float = 0.1) -> tuple[bool, str, int, int]:
    try:
        cq.exporters.export(solid_wp, stl_intermediate_path, exportType="STL",
                             tolerance=tolerance, angularTolerance=0.3)
    except Exception as e:
        return False, f"STL tessellation for GLB export raised an exception: {e}", 0, 0

    if not os.path.exists(stl_intermediate_path) or os.path.getsize(stl_intermediate_path) == 0:
        return False, "Intermediate STL for GLB export is missing or empty.", 0, 0

    try:
        mesh = trimesh.load(stl_intermediate_path, force="mesh")
        if mesh.vertices.shape[0] == 0 or mesh.faces.shape[0] == 0:
            return False, "Tessellated mesh has zero vertices/faces.", 0, 0
        mesh.export(glb_path, file_type="glb")
    except Exception as e:
        return False, f"GLB export raised an exception: {e}", 0, 0

    if not os.path.exists(glb_path) or os.path.getsize(glb_path) == 0:
        return False, "GLB export did not produce a valid file.", 0, 0

    # Re-open the GLB to confirm it actually contains mesh geometry
    try:
        check = trimesh.load(glb_path, force="scene")
        total_verts = sum(g.vertices.shape[0] for g in check.geometry.values())
        if total_verts == 0:
            return False, "GLB file written but re-import shows zero vertices.", 0, 0
    except Exception as e:
        return False, f"GLB file could not be re-validated: {e}", 0, 0

    return True, "GLB written and verified.", int(mesh.vertices.shape[0]), int(mesh.faces.shape[0])


def export_all(solid_wp: cq.Workplane, output_dir: str, base_name: str) -> ExportResult:
    os.makedirs(output_dir, exist_ok=True)
    step_path = os.path.join(output_dir, f"{base_name}.step")
    stl_path = os.path.join(output_dir, f"{base_name}.stl")
    glb_path = os.path.join(output_dir, f"{base_name}.glb")

    ok_step, msg_step = export_step(solid_wp, step_path)
    if not ok_step:
        return ExportResult(False, msg_step, step_path=None, glb_path=None)

    ok_glb, msg_glb, nverts, nfaces = export_glb(solid_wp, stl_path, glb_path)
    if not ok_glb:
        return ExportResult(False, f"STEP OK, but GLB failed: {msg_glb}",
                             step_path=step_path, step_size_bytes=os.path.getsize(step_path))

    return ExportResult(
        True,
        f"{msg_step} {msg_glb}",
        step_path=step_path,
        glb_path=glb_path,
        step_size_bytes=os.path.getsize(step_path),
        glb_size_bytes=os.path.getsize(glb_path),
        mesh_vertex_count=nverts,
        mesh_face_count=nfaces,
    )
