"""
Real (non-mocked) tests for backend/feature_classifier.py and the
multi-profile / multi-feature upgrade to profile_detector.py.

Built from synthetic-but-real shapely geometry (constructed segment
lists, exactly like geometry_analyzer.py would produce from a DXF) so
these tests do not depend on the shape of any particular DXF file.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import profile_detector, feature_classifier, solid_generator


def _square_segments(cx, cy, half):
    """Closed square outline as a segment list, corners at (cx±half, cy±half)."""
    pts = [
        (cx - half, cy - half), (cx + half, cy - half),
        (cx + half, cy + half), (cx - half, cy + half),
    ]
    return [(pts[i], pts[(i + 1) % 4]) for i in range(4)]


def _rect_segments(cx, cy, hw, hh):
    pts = [
        (cx - hw, cy - hh), (cx + hw, cy - hh),
        (cx + hw, cy + hh), (cx - hw, cy + hh),
    ]
    return [(pts[i], pts[(i + 1) % 4]) for i in range(4)]


def test_single_outer_square_no_features():
    segs = _square_segments(0, 0, 10)
    detection = profile_detector.detect(segs, [])
    assert detection.success
    assert len(detection.top_level_rings) == 1
    fs = feature_classifier.classify(detection)
    assert fs.summary.get("OUTER_BOUNDARY") == 1
    assert not fs.ambiguous


def test_multiple_separate_profiles():
    """Two disjoint squares in the same layer -> two independent outer boundaries."""
    segs = _square_segments(0, 0, 10) + _square_segments(100, 100, 5)
    detection = profile_detector.detect(segs, [])
    assert len(detection.top_level_rings) == 2
    fs = feature_classifier.classify(detection)
    assert fs.summary.get("OUTER_BOUNDARY") == 2


def test_circle_inside_square_is_through_hole():
    segs = _square_segments(0, 0, 10)
    circles = [(0, 0, 3)]
    detection = profile_detector.detect(segs, circles)
    fs = feature_classifier.classify(detection)
    assert fs.summary.get("THROUGH_HOLE") == 1
    hole = next(f for f in fs.features if f.feature_type == "THROUGH_HOLE")
    assert hole.role == "void"
    assert hole.depth == 1


def test_rectangular_cutout_detected():
    outer = _square_segments(0, 0, 20)
    inner_rect = _rect_segments(0, 0, 5, 3)  # small rectangle, fully inside
    detection = profile_detector.detect(outer + inner_rect, [])
    fs = feature_classifier.classify(detection)
    assert fs.summary.get("RECTANGULAR_CUTOUT") == 1


def test_nested_boss_inside_pocket():
    """Outer square > pocket square > boss square: even-odd nesting."""
    outer = _square_segments(0, 0, 30)
    pocket = _square_segments(0, 0, 15)
    boss = _square_segments(0, 0, 5)
    detection = profile_detector.detect(outer + pocket + boss, [])
    assert detection.max_depth == 2
    fs = feature_classifier.classify(detection)
    assert fs.summary.get("BOSS") == 1
    boss_feat = next(f for f in fs.features if f.feature_type == "BOSS")
    assert boss_feat.role == "solid"
    assert boss_feat.depth == 2


def test_ambiguous_shape_reported_not_guessed():
    """A wildly irregular void shape (star-ish, low rectangularity) should be
    flagged AMBIGUOUS rather than forced into a category."""
    # Star-like polygon: alternating near-far vertices around origin
    import math
    pts = []
    for i in range(10):
        r = 6 if i % 2 == 0 else 1.5
        a = math.radians(i * 36)
        pts.append((r * math.cos(a), r * math.sin(a)))
    star_segs = [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    outer = _square_segments(0, 0, 20)
    detection = profile_detector.detect(outer + star_segs, [])
    fs = feature_classifier.classify(detection)
    assert len(fs.ambiguous) >= 1
    assert fs.ambiguous[0].feature_type == "AMBIGUOUS"
    assert fs.ambiguous[0].reason


def test_open_geometry_not_treated_as_profile():
    """A 3-sided (open) 'square' must not silently become a closed profile."""
    pts = [(0, 0), (10, 0), (10, 10)]  # missing closing edge
    segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    detection = profile_detector.detect(segs, [])
    assert not detection.success


def test_solid_generator_builds_multi_feature_solid():
    outer = _square_segments(0, 0, 20)
    pocket = _rect_segments(-10, 0, 3, 2)
    detection = profile_detector.detect(outer + pocket, [(10, 0, 2)])
    fs = feature_classifier.classify(detection)
    result = solid_generator.build_solid_from_features(fs, depth_mm=5.0)
    assert result.success, result.message
    assert result.solid is not None
    assert result.solid.val() is not None


def test_solid_generator_skips_ambiguous_features():
    """Ambiguous features must be excluded from the solid, not guessed."""
    import math
    pts = []
    for i in range(10):
        r = 6 if i % 2 == 0 else 1.5
        a = math.radians(i * 36)
        pts.append((r * math.cos(a), r * math.sin(a)))
    star_segs = [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    outer = _square_segments(0, 0, 20)
    detection = profile_detector.detect(outer + star_segs, [])
    fs = feature_classifier.classify(detection)
    result = solid_generator.build_solid_from_features(fs, depth_mm=5.0)
    assert result.success
    assert "ambiguous feature(s) skipped" in result.message
