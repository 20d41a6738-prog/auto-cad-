"""
solid_generator.py
Builds a REAL OCCT B-rep solid (via CadQuery) from the 2D profile detected
by profile_detector.py, extruded by a user-supplied depth.

The extrusion depth is NOT present in a 2D DXF - it is an explicit,
user-configurable assumption. This module never invents it silently;
the caller must pass `depth_mm` and the UI must display it.
"""
from __future__ import annotations
from dataclasses import dataclass
import cadquery as cq
from shapely.geometry import Polygon


@dataclass
class SolidGenerationResult:
    success: bool
    solid: object | None       # cadquery.Workplane
    message: str
    assumptions: list


def _polygon_to_wire_points(poly: Polygon):
    coords = list(poly.exterior.coords)
    # ensure not duplicated last==first for cadquery polyline().close()
    if coords[0] == coords[-1]:
        coords = coords[:-1]
    return coords


def build_solid(outer_profile: Polygon, holes: list[Polygon], circle_holes: list,
                 depth_mm: float) -> SolidGenerationResult:
    assumptions = [
        f"Extrusion depth of {depth_mm} mm applied uniformly (not present in source 2D DXF).",
        "Flat planar solid assumed - no draft angle, fillets, or chamfers inferred from 2D data.",
    ]
    if depth_mm <= 0:
        return SolidGenerationResult(False, None, "Extrusion depth must be greater than 0.", assumptions)
    if outer_profile is None or not outer_profile.is_valid or outer_profile.area <= 0:
        return SolidGenerationResult(False, None, "No valid outer profile to extrude.", assumptions)

    try:
        outer_pts = _polygon_to_wire_points(outer_profile)
        wp = cq.Workplane("XY").polyline(outer_pts).close()
        solid = wp.extrude(depth_mm)

        # Cut polygonal holes
        for h in holes:
            if not h.is_valid or h.area <= 0:
                continue
            hpts = _polygon_to_wire_points(h)
            try:
                hole_wp = cq.Workplane("XY").polyline(hpts).close().extrude(depth_mm)
                solid = solid.cut(hole_wp)
            except Exception:
                continue

        # Cut circular holes
        for (cx, cy, r) in circle_holes:
            try:
                hole_wp = (
                    cq.Workplane("XY")
                    .center(cx, cy)
                    .circle(r)
                    .extrude(depth_mm)
                )
                solid = solid.cut(hole_wp)
            except Exception:
                continue

        if solid.val() is None:
            return SolidGenerationResult(False, None, "CadQuery produced an empty solid.", assumptions)

        return SolidGenerationResult(
            True, solid,
            f"Solid generated: outer profile extruded {depth_mm} mm with "
            f"{len(holes)} polygon hole(s) and {len(circle_holes)} circular hole(s) cut.",
            assumptions,
        )
    except Exception as e:
        return SolidGenerationResult(False, None, f"Solid generation failed: {e}", assumptions)


def build_solid_from_features(feature_set, depth_mm: float) -> SolidGenerationResult:
    """
    Builds a solid from a feature_classifier.FeatureSet using the even-odd
    nesting rule: each OUTER_BOUNDARY is extruded, every void-role feature
    (hole/pocket/rect-cutout/slot) directly or transitively cut, and every
    BOSS (solid island at even depth >= 2) added back - all deterministically,
    with no invented geometry. AMBIGUOUS features are skipped and reported,
    never guessed into a shape.

    Supports MULTIPLE separate top-level profiles: each becomes its own
    extruded body, unioned into the final result (as a compound if disjoint).
    """
    assumptions = [
        f"Extrusion depth of {depth_mm} mm applied uniformly to every profile "
        f"(not present in source 2D DXF).",
        "Flat planar extrusion assumed for all profiles - no draft angle, "
        "fillets, or chamfers inferred from 2D data.",
        "Pockets/cutouts are cut FULLY THROUGH the extrusion depth: 2D DXF "
        "geometry alone does not specify partial cut depth, so no blind-pocket "
        "depth is invented.",
        "Bosses (solid islands nested inside a cut region) are extruded to the "
        "SAME depth as the surrounding solid - true boss height is not "
        "recoverable from 2D geometry alone.",
    ]
    if depth_mm <= 0:
        return SolidGenerationResult(False, None, "Extrusion depth must be greater than 0.", assumptions)

    outer_features = [f for f in feature_set.features if f.feature_type == "OUTER_BOUNDARY"]
    if not outer_features:
        return SolidGenerationResult(False, None, "No outer boundary (top-level profile) to extrude.", assumptions)

    by_ring_index = {f.ring_index: f for f in feature_set.features}
    # build parent -> children map for void/boss features only (excludes AMBIGUOUS/NOT_CONVERTED)
    children_of: dict = {}
    for f in feature_set.features:
        if f.feature_type in ("OUTER_BOUNDARY",):
            continue
        if f.feature_type == "AMBIGUOUS":
            continue
        children_of.setdefault(f.parent_index, []).append(f)

    used_feature_counts = {"holes": 0, "pockets": 0, "slots": 0, "bosses": 0, "skipped_ambiguous": len(feature_set.ambiguous)}

    bodies = []
    try:
        for outer in outer_features:
            body = (
                cq.Workplane("XY")
                .polyline(_polygon_to_wire_points(outer.geometry))
                .close()
                .extrude(depth_mm)
            )

            # BFS through the containment tree from this outer boundary,
            # cutting void features and adding back boss features in
            # depth order so nested bosses-within-pockets resolve correctly.
            frontier = list(children_of.get(outer.ring_index, []))
            frontier.sort(key=lambda f: f.depth)
            while frontier:
                feat = frontier.pop(0)
                if not feat.geometry.is_valid or feat.geometry.area <= 0:
                    continue
                pts = _polygon_to_wire_points(feat.geometry)
                try:
                    feat_body = cq.Workplane("XY").polyline(pts).close().extrude(depth_mm)
                except Exception:
                    continue

                if feat.role == "void":
                    body = body.cut(feat_body)
                    if feat.feature_type == "THROUGH_HOLE":
                        used_feature_counts["holes"] += 1
                    elif feat.feature_type == "SLOT":
                        used_feature_counts["slots"] += 1
                    else:
                        used_feature_counts["pockets"] += 1
                elif feat.role == "solid":  # BOSS
                    body = body.union(feat_body)
                    used_feature_counts["bosses"] += 1

                frontier.extend(children_of.get(feat.ring_index, []))

            bodies.append(body)

        solid = bodies[0]
        for extra in bodies[1:]:
            solid = solid.union(extra)

        if solid.val() is None:
            return SolidGenerationResult(False, None, "CadQuery produced an empty solid.", assumptions)

        msg = (
            f"Solid generated from {len(outer_features)} outer profile(s): "
            f"{used_feature_counts['holes']} hole(s), {used_feature_counts['pockets']} pocket(s)/"
            f"cutout(s), {used_feature_counts['slots']} slot(s), {used_feature_counts['bosses']} "
            f"boss(es) applied; {used_feature_counts['skipped_ambiguous']} ambiguous feature(s) "
            f"skipped (not converted)."
        )
        return SolidGenerationResult(True, solid, msg, assumptions)

    except Exception as e:
        return SolidGenerationResult(False, None, f"Solid generation failed: {e}", assumptions)
