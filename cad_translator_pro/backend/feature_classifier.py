"""
feature_classifier.py
Deterministic, rule-based classification of the ring containment tree
produced by profile_detector.py into engineering-meaningful feature
labels: OUTER_BOUNDARY, THROUGH_HOLE, POCKET, RECTANGULAR_CUTOUT, SLOT,
BOSS, AMBIGUOUS.

No AI / fuzzy matching. Every rule is a concrete geometric test
(nesting parity, rectangularity ratio, aspect ratio, source entity
type). If a ring does not clearly satisfy a rule, it is labeled
AMBIGUOUS with an explicit reason and EXCLUDED from solid generation
by the caller - it is never guessed into a category.

Nesting-parity logic (the actual solid/void decision used later by
solid_generator.py):
  depth 0        -> OUTER_BOUNDARY   (solid) - one per separate profile
  depth odd      -> VOID             (removes material: hole/pocket/slot)
  depth even >=2 -> SOLID ISLAND     (adds material back: boss)
This is the standard even-odd nesting rule for multiply-nested 2D
regions and requires no invented geometry - it falls directly out of
which ring contains which.
"""
from __future__ import annotations
from dataclasses import dataclass
from shapely.geometry import Polygon

from .profile_detector import ProfileDetectionResult, Ring

RECT_RATIO_THRESHOLD = 0.90     # area / min-rotated-rect-area to call something "rectangular"
SLOT_RECT_RATIO_MIN = 0.72      # rounded-end slots fill less of their bounding rect than a hard rectangle
SLOT_ASPECT_MIN = 2.0           # long/short side ratio to call something "elongated"


@dataclass
class ClassifiedFeature:
    ring_index: int
    feature_type: str        # OUTER_BOUNDARY, THROUGH_HOLE, POCKET, RECTANGULAR_CUTOUT, SLOT, BOSS, AMBIGUOUS
    role: str                 # "solid" (adds material) or "void" (removes material) or "n/a"
    geometry: object           # shapely Polygon
    depth: int
    parent_index: int | None
    confidence: str             # HIGH, MEDIUM, LOW
    reason: str
    source: str                  # "polygon" or "circle"
    area: float


@dataclass
class FeatureSet:
    features: list                # list[ClassifiedFeature], includes outer boundaries
    ambiguous: list                # list[ClassifiedFeature] with feature_type == AMBIGUOUS
    not_converted: list             # list of dicts describing rings excluded entirely (invalid geometry)
    summary: dict                    # counts by feature_type


def _shape_metrics(poly: Polygon) -> tuple[float, float]:
    """Returns (rectangularity, aspect_ratio) using the minimum rotated rectangle."""
    try:
        mrr = poly.minimum_rotated_rectangle
        mrr_area = mrr.area
        rectangularity = poly.area / mrr_area if mrr_area > 1e-9 else 0.0

        coords = list(mrr.exterior.coords)[:4]
        if len(coords) < 4:
            return rectangularity, 1.0
        side1 = ((coords[1][0] - coords[0][0]) ** 2 + (coords[1][1] - coords[0][1]) ** 2) ** 0.5
        side2 = ((coords[2][0] - coords[1][0]) ** 2 + (coords[2][1] - coords[1][1]) ** 2) ** 0.5
        long_side = max(side1, side2)
        short_side = max(min(side1, side2), 1e-9)
        aspect = long_side / short_side
        return rectangularity, aspect
    except Exception:
        return 0.0, 1.0


def _classify_void_ring(ring: Ring) -> tuple[str, str, str]:
    """Returns (feature_type, confidence, reason) for a depth-odd (void) ring."""
    if ring.source == "circle":
        return "THROUGH_HOLE", "HIGH", "Circular entity fully enclosed by parent boundary; classified as a hole."

    rectangularity, aspect = _shape_metrics(ring.polygon)

    if rectangularity >= RECT_RATIO_THRESHOLD:
        return ("RECTANGULAR_CUTOUT", "HIGH",
                f"Closed polygon fills {rectangularity*100:.0f}% of its minimum bounding "
                f"rectangle (aspect ratio {aspect:.2f}); classified as a rectangular cutout/pocket.")

    if aspect >= SLOT_ASPECT_MIN and rectangularity >= SLOT_RECT_RATIO_MIN:
        return ("SLOT", "MEDIUM",
                f"Elongated closed polygon (aspect ratio {aspect:.2f}, "
                f"{rectangularity*100:.0f}% rectangle fill) consistent with a slot "
                f"(rectangle with rounded/curved ends).")

    if rectangularity >= 0.55:
        return ("POCKET", "MEDIUM",
                f"Irregular closed polygon ({rectangularity*100:.0f}% rectangle fill, "
                f"aspect ratio {aspect:.2f}); classified as a generic pocket cutout.")

    return ("AMBIGUOUS", "LOW",
            f"Closed polygon shape is irregular enough ({rectangularity*100:.0f}% rectangle "
            f"fill) that its intended feature type cannot be determined with confidence.")


def classify(detection: ProfileDetectionResult) -> FeatureSet:
    features: list[ClassifiedFeature] = []
    ambiguous: list[ClassifiedFeature] = []
    not_converted: list[dict] = []

    for r in detection.rings:
        if not r.valid:
            not_converted.append({
                "ring_index": r.index,
                "source": r.source,
                "reason": r.invalid_reason,
                "action": "Excluded from solid generation entirely.",
            })
            continue

        if r.depth == 0:
            cf = ClassifiedFeature(
                ring_index=r.index, feature_type="OUTER_BOUNDARY", role="solid",
                geometry=r.polygon, depth=r.depth, parent_index=r.parent_index,
                confidence="HIGH", reason="Top-level closed profile (not contained by any other ring).",
                source=r.source, area=r.area,
            )
            features.append(cf)
            continue

        if r.depth % 2 == 1:
            ftype, conf, reason = _classify_void_ring(r)
            cf = ClassifiedFeature(
                ring_index=r.index, feature_type=ftype, role=("void" if ftype != "AMBIGUOUS" else "n/a"),
                geometry=r.polygon, depth=r.depth, parent_index=r.parent_index,
                confidence=conf, reason=reason, source=r.source, area=r.area,
            )
            features.append(cf)
            if ftype == "AMBIGUOUS":
                ambiguous.append(cf)
        else:
            # depth even and >= 2 -> island of solid material inside a void -> boss
            cf = ClassifiedFeature(
                ring_index=r.index, feature_type="BOSS", role="solid",
                geometry=r.polygon, depth=r.depth, parent_index=r.parent_index,
                confidence="MEDIUM",
                reason=(
                    f"Ring nested at depth {r.depth} (even) inside a removed region - "
                    f"interpreted as a solid island (boss) left standing within a "
                    f"pocket/hole, per even-odd nesting rule."
                ),
                source=r.source, area=r.area,
            )
            features.append(cf)

    summary: dict = {}
    for cf in features:
        summary[cf.feature_type] = summary.get(cf.feature_type, 0) + 1
    summary["NOT_CONVERTED_RINGS"] = len(not_converted)

    return FeatureSet(features=features, ambiguous=ambiguous, not_converted=not_converted, summary=summary)
