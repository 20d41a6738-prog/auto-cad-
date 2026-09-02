"""
geometry_analyzer.py
Converts raw ezdxf entities on selected layers into shapely-ready 2D
primitives: line segments (from LINE/LWPOLYLINE/ARC-tessellated) and
circles (kept exact, not tessellated, so hole detection stays precise).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
import ezdxf

ARC_SEGMENTS = 64  # tessellation resolution for arcs/circles used in polygon boundaries


@dataclass
class GeometryAnalysis:
    layer_names: list
    segments: list          # list of ((x1,y1),(x2,y2)) line segments, all geometry layers
    circles: list           # list of (cx, cy, r)
    segments_by_layer: dict
    circles_by_layer: dict
    entity_type_counts: dict
    recommended_layers: list  # heuristic guess at "real geometry" layers
    excluded_layers: list     # layers that look like annotation/dimension/hatch


ANNOTATION_LAYER_HINTS = ("DIM", "DIMENSION", "HATCH", "TEXT", "NOTE", "TITLE", "BORDER")
NON_PROFILE_LAYER_HINTS = ("CENTER", "HIDDEN")


def _arc_points(center, radius, start_angle_deg, end_angle_deg, segments=ARC_SEGMENTS):
    start = math.radians(start_angle_deg)
    end = math.radians(end_angle_deg)
    if end < start:
        end += 2 * math.pi
    pts = []
    n = max(4, int(segments * (end - start) / (2 * math.pi)))
    for i in range(n + 1):
        a = start + (end - start) * i / n
        pts.append((center[0] + radius * math.cos(a), center[1] + radius * math.sin(a)))
    return pts


def analyze(doc, layers: list[str] | None = None) -> GeometryAnalysis:
    """
    Extract line segments and circles from modelspace entities.
    If `layers` is provided, only entities on those layers are used;
    otherwise all layers are used.
    """
    msp = doc.modelspace()
    segments = []
    circles = []
    seg_by_layer = {}
    circ_by_layer = {}
    type_counts = {}

    layer_set = set(layers) if layers else None

    for e in msp:
        t = e.dxftype()
        layer = e.dxf.layer
        if layer_set is not None and layer not in layer_set:
            continue
        type_counts[t] = type_counts.get(t, 0) + 1

        try:
            if t == "LINE":
                p1 = (e.dxf.start.x, e.dxf.start.y)
                p2 = (e.dxf.end.x, e.dxf.end.y)
                segments.append((p1, p2))
                seg_by_layer.setdefault(layer, []).append((p1, p2))

            elif t == "LWPOLYLINE":
                pts = [(p[0], p[1]) for p in e.get_points()]
                closed = e.closed
                n = len(pts)
                rng = n if closed else n - 1
                for i in range(rng):
                    p1 = pts[i]
                    p2 = pts[(i + 1) % n]
                    segments.append((p1, p2))
                    seg_by_layer.setdefault(layer, []).append((p1, p2))

            elif t == "POLYLINE":
                pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                closed = e.is_closed
                n = len(pts)
                rng = n if closed else n - 1
                for i in range(rng):
                    p1 = pts[i]
                    p2 = pts[(i + 1) % n]
                    segments.append((p1, p2))
                    seg_by_layer.setdefault(layer, []).append((p1, p2))

            elif t == "ARC":
                center = (e.dxf.center.x, e.dxf.center.y)
                pts = _arc_points(center, e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle)
                for i in range(len(pts) - 1):
                    segments.append((pts[i], pts[i + 1]))
                    seg_by_layer.setdefault(layer, []).append((pts[i], pts[i + 1]))

            elif t == "CIRCLE":
                c = (e.dxf.center.x, e.dxf.center.y, e.dxf.radius)
                circles.append(c)
                circ_by_layer.setdefault(layer, []).append(c)
        except Exception:
            # skip malformed entity but keep processing the rest
            continue

    all_layers = sorted(set(list(seg_by_layer.keys()) + list(circ_by_layer.keys())))

    recommended, excluded = [], []
    for lyr in all_layers:
        upper = lyr.upper()
        if any(hint in upper for hint in ANNOTATION_LAYER_HINTS):
            excluded.append(lyr)
        elif any(hint in upper for hint in NON_PROFILE_LAYER_HINTS):
            excluded.append(lyr)
        else:
            recommended.append(lyr)

    return GeometryAnalysis(
        layer_names=all_layers,
        segments=segments,
        circles=circles,
        segments_by_layer=seg_by_layer,
        circles_by_layer=circ_by_layer,
        entity_type_counts=type_counts,
        recommended_layers=recommended,
        excluded_layers=excluded,
    )
