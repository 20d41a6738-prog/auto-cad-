"""
validator.py
Validates the OCCT solid produced by solid_generator.py using CadQuery's
underlying OCCT kernel. Reports real geometric properties. Never fabricates
statistics - every number here comes from BRepGProp / shape traversal.
"""
from __future__ import annotations
from dataclasses import dataclass
import cadquery as cq
from OCP.BRepCheck import BRepCheck_Analyzer


@dataclass
class ValidationResult:
    valid: bool
    message: str
    solids: int
    faces: int
    edges: int
    vertices: int
    volume: float
    surface_area: float
    bbox: tuple  # (xmin, ymin, zmin, xmax, ymax, zmax)


def validate(solid_wp: cq.Workplane) -> ValidationResult:
    try:
        shape = solid_wp.val()
        if shape is None:
            return ValidationResult(False, "No shape to validate.", 0, 0, 0, 0, 0, 0, (0,) * 6)

        occt_shape = shape.wrapped
        analyzer = BRepCheck_Analyzer(occt_shape)
        is_valid = bool(analyzer.IsValid())

        solids = solid_wp.solids().size()
        faces = solid_wp.faces().size()
        edges = solid_wp.edges().size()
        vertices = solid_wp.vertices().size()

        volume = float(shape.Volume()) if hasattr(shape, "Volume") else 0.0
        try:
            surface_area = float(shape.Area()) if hasattr(shape, "Area") else 0.0
        except Exception:
            surface_area = 0.0

        bb = shape.BoundingBox()
        bbox = (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)

        if not is_valid:
            return ValidationResult(
                False, "OCCT BRepCheck reports the shape is NOT topologically valid.",
                solids, faces, edges, vertices, volume, surface_area, bbox
            )
        if solids == 0:
            return ValidationResult(
                False, "No solid bodies present after generation.",
                solids, faces, edges, vertices, volume, surface_area, bbox
            )
        if volume <= 0:
            return ValidationResult(
                False, f"Computed solid volume is non-positive ({volume}).",
                solids, faces, edges, vertices, volume, surface_area, bbox
            )

        return ValidationResult(
            True, "Geometry is valid: watertight solid confirmed by OCCT BRepCheck.",
            solids, faces, edges, vertices, volume, surface_area, bbox
        )
    except Exception as e:
        return ValidationResult(False, f"Validation raised an exception: {e}", 0, 0, 0, 0, 0, 0, (0,) * 6)
