"""
profile_detector.py
Uses shapely to merge raw line segments into closed rings (polygonize),
then builds a full CONTAINMENT TREE across every closed ring found
(polygon rings + circle rings), instead of assuming a single outer
profile. This is what lets the feature classifier recognise multiple
separate profiles, nested pockets, and bosses-within-pockets.

Legacy fields (outer_profile / holes / circles_as_holes / other_polygons)
are still populated for backward compatibility with existing callers,
using the single largest top-level ring as "the" outer profile - but the
new `rings` / `top_level_rings` fields expose the full picture and are
what feature_classifier.py consumes.
"""
from __future__ import annotations
from dataclasses import dataclass
from shapely.geometry import Polygon, MultiLineString, Point
from shapely.ops import polygonize


def _round_pt(p, prec=6):
    return (round(p[0], prec), round(p[1], prec))


def _connected_components(segments: list) -> list:
    """
    Groups line segments into connected components via union-find on
    shared endpoints. This matters because feeding ALL segments into a
    single polygonize() call makes GEOS return the FACES of the whole
    arrangement (e.g. alternating concentric annular bands for nested
    but non-touching loops) rather than one simple filled polygon per
    independent closed loop. Splitting by connected component first, so
    each disjoint/nested loop is polygonized on its own, gives back
    simple filled polygons whose true containment we can then determine
    ourselves.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for (p1, p2) in segments:
        union(_round_pt(p1), _round_pt(p2))

    groups: dict = {}
    for (p1, p2) in segments:
        root = find(_round_pt(p1))
        groups.setdefault(root, []).append((p1, p2))

    return list(groups.values())


@dataclass
class Ring:
    index: int
    polygon: Polygon
    area: float
    depth: int              # 0 = top-level outer boundary, 1 = direct cavity, 2 = island-in-cavity, ...
    parent_index: int | None
    source: str              # "polygon" (from LINE/ARC/LWPOLYLINE) or "circle" (from CIRCLE entity)
    valid: bool
    invalid_reason: str = ""
    circle_data: tuple | None = None  # (cx, cy, r) when source == "circle"


@dataclass
class ProfileDetectionResult:
    # New: full containment picture
    rings: list                    # list[Ring], all valid+invalid closed rings found
    top_level_rings: list          # list[Ring] with depth == 0 -> one entry per separate profile
    invalid_rings: list            # list[Ring] that were self-intersecting / degenerate (excluded)
    max_depth: int

    # Legacy fields, derived from the tree, kept for backward compatibility
    polygons_found: int
    outer_profile: Polygon | None
    holes: list
    other_polygons: list
    circles_as_holes: list
    unused_circles: list

    open_segment_count: int
    success: bool
    message: str


def _build_rings(polygons: list, circle_data: list, circle_polys: list) -> list:
    rings = []
    idx = 0
    for p in polygons:
        if p.is_valid and p.area > 1e-9:
            rings.append(Ring(idx, p, p.area, depth=-1, parent_index=None, source="polygon", valid=True))
        else:
            reason = "Self-intersecting or degenerate polygon (zero/near-zero area)."
            rings.append(Ring(idx, p, getattr(p, "area", 0.0), depth=-1, parent_index=None,
                               source="polygon", valid=False, invalid_reason=reason))
        idx += 1
    for c, cpoly in zip(circle_data, circle_polys):
        if cpoly.is_valid and cpoly.area > 1e-9:
            rings.append(Ring(idx, cpoly, cpoly.area, depth=-1, parent_index=None, source="circle",
                               valid=True, circle_data=c))
        else:
            rings.append(Ring(idx, cpoly, 0.0, depth=-1, parent_index=None, source="circle",
                               valid=False, invalid_reason="Degenerate circle geometry.", circle_data=c))
        idx += 1
    return rings


def _assign_containment(rings: list) -> None:
    """
    For each valid ring, find its immediate parent = the smallest-area
    OTHER valid ring that contains it. depth = number of ancestors.
    Mutates rings in place.
    """
    valid = [r for r in rings if r.valid]

    for r in valid:
        containers = [
            o for o in valid
            if o.index != r.index and o.area > r.area
            and o.polygon.contains(r.polygon.representative_point())
        ]
        if containers:
            parent = min(containers, key=lambda o: o.area)
            r.parent_index = parent.index
        else:
            r.parent_index = None

    by_index = {r.index: r for r in rings}
    for r in rings:
        if not r.valid:
            r.depth = -1
            continue
        depth = 0
        cur = r
        seen = set()
        while cur.parent_index is not None and cur.parent_index not in seen:
            seen.add(cur.parent_index)
            cur = by_index[cur.parent_index]
            depth += 1
            if depth > 64:
                break
        r.depth = depth


def detect(segments: list, circles: list) -> ProfileDetectionResult:
    if not segments and not circles:
        return ProfileDetectionResult(
            rings=[], top_level_rings=[], invalid_rings=[], max_depth=-1,
            polygons_found=0, outer_profile=None, holes=[], other_polygons=[],
            circles_as_holes=[], unused_circles=list(circles),
            open_segment_count=0, success=False,
            message="No line/arc geometry available to build a profile."
        )

    # Polygonize PER CONNECTED COMPONENT so that nested-but-disjoint loops
    # (e.g. a pocket outline and a boss outline that don't touch) each
    # yield a simple filled polygon, instead of GEOS merging the whole
    # arrangement into hole-bearing faces (see _connected_components docstring).
    polygons = []
    for comp_segments in _connected_components(segments):
        comp_lines = MultiLineString(comp_segments)
        polygons.extend(polygonize(comp_lines))

    circle_polys = [Point(cx, cy).buffer(r, quad_segs=32) for (cx, cy, r) in circles]

    valid_polys = [p for p in polygons if p.is_valid and p.area > 1e-9]

    if not valid_polys and not circle_polys:
        return ProfileDetectionResult(
            rings=[], top_level_rings=[], invalid_rings=[], max_depth=-1,
            polygons_found=0, outer_profile=None, holes=[], other_polygons=[],
            circles_as_holes=[], unused_circles=list(circles),
            open_segment_count=len(segments), success=False,
            message=(
                "Line/arc geometry did not form any closed loop "
                "(polygonize found 0 closed rings). The selected layer(s) likely "
                "contain open construction/reference lines rather than a closed "
                "part outline."
            ),
        )

    rings = _build_rings(polygons, circles, circle_polys)
    _assign_containment(rings)

    valid_rings = [r for r in rings if r.valid]
    invalid_rings = [r for r in rings if not r.valid]
    top_level = [r for r in valid_rings if r.depth == 0]
    max_depth = max([r.depth for r in valid_rings], default=-1)

    # --- Legacy fields, derived from the new tree, for backward compatibility ---
    outer = None
    holes = []
    other_top_level = []
    circles_as_holes = []
    unused_circles = []

    if top_level:
        top_sorted = sorted(top_level, key=lambda r: r.area, reverse=True)
        outer_ring = top_sorted[0]
        outer = outer_ring.polygon
        for r in top_sorted[1:]:
            other_top_level.append(r.polygon)

        for r in valid_rings:
            if r.parent_index == outer_ring.index:
                if r.source == "circle":
                    circles_as_holes.append(r.circle_data)
                else:
                    holes.append(r.polygon)

        direct_child_circle_indices = {
            r.index for r in valid_rings
            if r.parent_index == outer_ring.index and r.source == "circle"
        }
        for r in rings:
            if r.source == "circle" and r.index not in direct_child_circle_indices:
                unused_circles.append(r.circle_data)

    n_features = len([r for r in valid_rings if r.depth > 0])
    msg = (
        f"Detected {len(top_level)} separate outer profile(s), {n_features} nested "
        f"feature ring(s) (holes/pockets/bosses), and {len(invalid_rings)} invalid/degenerate "
        f"ring(s) excluded. Max nesting depth = {max_depth}."
    )

    return ProfileDetectionResult(
        rings=rings,
        top_level_rings=top_level,
        invalid_rings=invalid_rings,
        max_depth=max_depth,
        polygons_found=len(valid_polys),
        outer_profile=outer,
        holes=holes,
        other_polygons=other_top_level,
        circles_as_holes=circles_as_holes,
        unused_circles=unused_circles,
        open_segment_count=len(segments),
        success=len(top_level) > 0,
        message=msg,
    )
