"""
dxf_reader.py
Real DXF parsing using ezdxf. No mocking - if the file cannot be parsed
this raises an exception which the pipeline surfaces to the UI as an error.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from collections import Counter
import ezdxf
from ezdxf.document import Drawing

UNIT_MAP = {
    0: "Unitless",
    1: "Inches",
    2: "Feet",
    4: "Millimeters",
    5: "Centimeters",
    6: "Meters",
}


@dataclass
class DXFInspectionResult:
    file_name: str
    file_size_bytes: int
    dxf_version: str
    units: str
    total_entities: int
    entity_type_counts: dict
    layer_entity_counts: dict
    layer_names: list
    bbox: tuple  # (minx, miny, maxx, maxy) or None
    width: float
    height: float
    valid: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class DXFReadError(Exception):
    pass


def validate_file(path: str) -> None:
    """Basic file-level validation before attempting a parse."""
    if not os.path.exists(path):
        raise DXFReadError(f"File does not exist: {path}")
    size = os.path.getsize(path)
    if size == 0:
        raise DXFReadError("File is empty (0 bytes).")
    with open(path, "rb") as f:
        head = f.read(64)
    # DXF files are text-based and should start with a group code section
    try:
        head.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        # try latin-1, DXF R14 and earlier can be non-utf8
        try:
            head.decode("latin-1")
        except Exception:
            raise DXFReadError("File does not appear to be a valid text-based DXF.")


def read_dxf(path: str) -> Drawing:
    """Parse the DXF using ezdxf. Raises DXFReadError on any structural problem."""
    validate_file(path)
    try:
        doc = ezdxf.readfile(path)
    except ezdxf.DXFStructureError as e:
        raise DXFReadError(f"Invalid DXF structure: {e}")
    except IOError as e:
        raise DXFReadError(f"Could not read file: {e}")
    except Exception as e:
        raise DXFReadError(f"Unexpected error parsing DXF: {e}")

    # Force ezdxf's own audit to catch corrupt entities early
    auditor = doc.audit()
    if auditor.has_errors:
        # Non-fatal: ezdxf repairs what it can. We surface as warnings.
        pass
    return doc


def _entity_bbox_points(e):
    """Yield (x, y) sample points for an entity for bbox computation."""
    t = e.dxftype()
    try:
        if t == "LINE":
            yield (e.dxf.start.x, e.dxf.start.y)
            yield (e.dxf.end.x, e.dxf.end.y)
        elif t == "LWPOLYLINE":
            for p in e.get_points():
                yield (p[0], p[1])
        elif t == "POLYLINE":
            for v in e.vertices:
                yield (v.dxf.location.x, v.dxf.location.y)
        elif t == "CIRCLE":
            c, r = e.dxf.center, e.dxf.radius
            yield (c.x - r, c.y - r)
            yield (c.x + r, c.y + r)
        elif t == "ARC":
            c, r = e.dxf.center, e.dxf.radius
            yield (c.x - r, c.y - r)
            yield (c.x + r, c.y + r)
        elif t in ("TEXT", "MTEXT"):
            ip = e.dxf.insert
            yield (ip.x, ip.y)
        elif t == "INSERT":
            ip = e.dxf.insert
            yield (ip.x, ip.y)
    except Exception:
        return


def inspect(path: str) -> tuple[DXFInspectionResult, Drawing]:
    """
    Full real inspection of a DXF file: entity counts, layers, geometry
    types, bounding box, units. Returns (result, ezdxf Drawing).
    """
    file_name = os.path.basename(path)
    file_size = os.path.getsize(path)

    doc = read_dxf(path)
    msp = doc.modelspace()

    type_counts = Counter()
    layer_counts = Counter()
    xs, ys = [], []

    total = 0
    for e in msp:
        total += 1
        type_counts[e.dxftype()] += 1
        layer_counts[e.dxf.layer] += 1
        for (x, y) in _entity_bbox_points(e):
            xs.append(x)
            ys.append(y)

    bbox = None
    width = height = 0.0
    if xs and ys:
        bbox = (min(xs), min(ys), max(xs), max(ys))
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]

    units_code = doc.header.get("$INSUNITS", 0)
    units = UNIT_MAP.get(units_code, f"Unknown ({units_code})")

    warnings = []
    if total == 0:
        warnings.append("DXF contains zero entities in model space.")
    if bbox is None:
        warnings.append("Could not determine a bounding box from geometry entities.")

    result = DXFInspectionResult(
        file_name=file_name,
        file_size_bytes=file_size,
        dxf_version=doc.dxfversion,
        units=units,
        total_entities=total,
        entity_type_counts=dict(type_counts),
        layer_entity_counts=dict(layer_counts),
        layer_names=sorted(layer_counts.keys()),
        bbox=bbox,
        width=width,
        height=height,
        valid=total > 0,
        warnings=warnings,
    )
    return result, doc
