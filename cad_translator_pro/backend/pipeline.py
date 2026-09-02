"""
pipeline.py
Orchestrates: DXF read -> geometry analysis -> profile detection ->
solid generation -> validation -> STEP export -> GLB export.

Every stage returns real, inspectable results. Logs are generated from
actual stage outcomes - never pre-scripted "fake" log lines.
"""
from __future__ import annotations
import os
import time
import shutil
from dataclasses import dataclass, field
from datetime import datetime

from . import dxf_reader, geometry_analyzer, profile_detector, feature_classifier, solid_generator, validator, exporter

JOBS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jobs")


@dataclass
class LogEntry:
    timestamp: str
    level: str  # INFO, SUCCESS, WARNING, ERROR, NOT_CONVERTED, ASSUMPTION
    message: str
    stage: str = ""
    entity: str = ""
    reason: str = ""
    details: str = ""


@dataclass
class PipelineResult:
    success: bool
    job_id: str
    job_dir: str
    logs: list = field(default_factory=list)
    inspection: object = None
    analysis: object = None
    detection: object = None
    feature_set: object = None
    solid_result: object = None
    validation: object = None
    export_result: object = None
    stage_status: dict = field(default_factory=dict)  # stage_name -> "done"|"active"|"pending"|"error"
    processing_time_sec: float = 0.0
    error_message: str = ""
    run_by: str = ""
    department: str = ""
    organization: str = ""


STAGES = [
    "reading_dxf",
    "analyzing_geometry",
    "detecting_profiles",
    "generating_solid",
    "validating_geometry",
    "exporting_step",
    "preparing_viewer",
]

STAGE_LABELS = {
    "reading_dxf": "Reading DXF",
    "analyzing_geometry": "Analysing geometry",
    "detecting_profiles": "Detecting profiles",
    "generating_solid": "Generating solid",
    "validating_geometry": "Validating geometry",
    "exporting_step": "Exporting STEP",
    "preparing_viewer": "Preparing 3D viewer",
}


def new_job_id() -> str:
    existing = []
    if os.path.exists(JOBS_ROOT):
        for name in os.listdir(JOBS_ROOT):
            if name.startswith("JOB-"):
                try:
                    existing.append(int(name.split("-")[1]))
                except (IndexError, ValueError):
                    pass
    next_n = (max(existing) + 1) if existing else 1
    return f"JOB-{next_n:03d}"


def _make_job_dirs(job_id: str) -> dict:
    job_dir = os.path.join(JOBS_ROOT, job_id)
    dirs = {
        "root": job_dir,
        "input": os.path.join(job_dir, "input"),
        "intermediate": os.path.join(job_dir, "intermediate"),
        "output": os.path.join(job_dir, "output"),
        "logs": os.path.join(job_dir, "logs"),
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs


class Pipeline:
    """Stateful pipeline for a single translation job, with live log capture."""

    def __init__(self, job_id: str | None = None, run_by: str = "unknown",
                 department: str = "", organization: str = ""):
        self.job_id = job_id or new_job_id()
        self.dirs = _make_job_dirs(self.job_id)
        self.logs: list[LogEntry] = []
        self.stage_status = {s: "pending" for s in STAGES}
        self.run_by = run_by or "unknown"
        self.department = department or "Not specified"
        self.organization = organization or "Not specified"
        self._write_job_meta()

    def _write_job_meta(self):
        import json
        meta_path = os.path.join(self.dirs["root"], "job_meta.json")
        meta = {"job_id": self.job_id, "run_by": self.run_by,
                "department": self.department, "organization": self.organization,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        try:
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
        except OSError:
            pass

    def log(self, level: str, message: str, stage: str = "", entity: str = "",
            reason: str = "", details: str = ""):
        entry = LogEntry(datetime.now().strftime("%H:%M:%S"), level, message,
                          stage=stage, entity=entity, reason=reason, details=details)
        self.logs.append(entry)
        return entry

    def _write_log_file(self):
        log_path = os.path.join(self.dirs["logs"], "translation.log")
        with open(log_path, "w") as f:
            for e in self.logs:
                extra = ""
                if e.entity:
                    extra += f" entity={e.entity}"
                if e.reason:
                    extra += f" reason={e.reason}"
                f.write(f"[{e.timestamp}] {e.level:<13} stage={e.stage or '-':<20}{extra} {e.message}\n")

    def run(self, input_dxf_path: str, selected_layers: list[str] | None,
             extrusion_depth_mm: float) -> PipelineResult:
        t0 = time.time()
        base_name = os.path.splitext(os.path.basename(input_dxf_path))[0]

        # Copy the source file into the job's input/ directory (never overwritten)
        job_input_path = os.path.join(self.dirs["input"], os.path.basename(input_dxf_path))
        shutil.copy2(input_dxf_path, job_input_path)

        result = PipelineResult(success=False, job_id=self.job_id, job_dir=self.dirs["root"],
                                 run_by=self.run_by, department=self.department, organization=self.organization)

        # --- Stage 1: reading_dxf ---
        self.stage_status["reading_dxf"] = "active"
        self.log("INFO", "Reading DXF", stage="reading_dxf")
        try:
            inspection, doc = dxf_reader.inspect(job_input_path)
            result.inspection = inspection
            self.log("SUCCESS", f"Entities detected: {inspection.total_entities}", stage="reading_dxf")
            self.stage_status["reading_dxf"] = "done"
        except dxf_reader.DXFReadError as e:
            self.stage_status["reading_dxf"] = "error"
            self.log("ERROR", str(e), stage="reading_dxf", reason=str(e))
            result.error_message = str(e)
            self._write_log_file()
            result.logs = self.logs
            result.stage_status = self.stage_status
            result.processing_time_sec = time.time() - t0
            return result

        # --- Stage 2: analyzing_geometry ---
        self.stage_status["analyzing_geometry"] = "active"
        self.log("INFO", "Analysing geometry" + (f" on layers: {', '.join(selected_layers)}" if selected_layers else " on all layers"), stage="analyzing_geometry")
        analysis = geometry_analyzer.analyze(doc, selected_layers)
        result.analysis = analysis
        self.log("INFO", f"Segments extracted: {len(analysis.segments)}, circles: {len(analysis.circles)}", stage="analyzing_geometry")
        self.stage_status["analyzing_geometry"] = "done"

        # --- Stage 3: detecting_profiles ---
        self.stage_status["detecting_profiles"] = "active"
        self.log("INFO", "Detecting closed profiles", stage="detecting_profiles")
        detection = profile_detector.detect(analysis.segments, analysis.circles)
        result.detection = detection
        if detection.success:
            self.log("SUCCESS", f"{detection.polygons_found} closed polygon(s) detected; "
                                 f"{len(detection.holes) + len(detection.circles_as_holes)} hole(s) identified", stage="detecting_profiles")
            self.stage_status["detecting_profiles"] = "done"
        else:
            self.stage_status["detecting_profiles"] = "error"
            self.log("ERROR", detection.message, stage="detecting_profiles", reason=detection.message)
            result.error_message = detection.message
            self._write_log_file()
            result.logs = self.logs
            result.stage_status = self.stage_status
            result.processing_time_sec = time.time() - t0
            return result

        # --- Stage 3b: classifying features (deterministic, no AI) ---
        feature_set = feature_classifier.classify(detection)
        result.feature_set = feature_set
        for amb in feature_set.ambiguous:
            self.log("WARNING", f"Ring #{amb.ring_index} at depth {amb.depth}: AMBIGUOUS - {amb.reason}",
                     stage="classifying_features", entity=f"ring#{amb.ring_index}", reason=amb.reason)
        for nc in feature_set.not_converted:
            self.log("NOT_CONVERTED", f"Ring #{nc['ring_index']} ({nc['source']}) not converted - {nc['reason']}",
                     stage="classifying_features", entity=f"ring#{nc['ring_index']} ({nc['source']})",
                     reason=nc["reason"], details=nc.get("impact", "May result in missing geometry in the 3D model."))
        self.log("INFO", "Feature classification: " + ", ".join(
            f"{k}={v}" for k, v in feature_set.summary.items() if v), stage="classifying_features")

        # --- Stage 4: generating_solid ---
        self.stage_status["generating_solid"] = "active"
        self.log("ASSUMPTION", f"Extrusion depth set to {extrusion_depth_mm} mm — a 2D DXF carries no Z "
                 f"information, so this value was supplied by the user/operator, not derived from the drawing.",
                 stage="generating_solid", entity="extrusion_depth",
                 reason="2D DXF contains no 3rd-dimension data.")
        solid_result = solid_generator.build_solid_from_features(feature_set, extrusion_depth_mm)
        result.solid_result = solid_result
        if solid_result.success:
            self.log("SUCCESS", "Solid generated", stage="generating_solid")
            self.stage_status["generating_solid"] = "done"
        else:
            self.stage_status["generating_solid"] = "error"
            self.log("ERROR", solid_result.message, stage="generating_solid", reason=solid_result.message)
            result.error_message = solid_result.message
            self._write_log_file()
            result.logs = self.logs
            result.stage_status = self.stage_status
            result.processing_time_sec = time.time() - t0
            return result

        # --- Stage 5: validating_geometry ---
        self.stage_status["validating_geometry"] = "active"
        self.log("INFO", "Validating geometry", stage="validating_geometry")
        validation = validator.validate(solid_result.solid)
        result.validation = validation
        if validation.valid:
            self.log("SUCCESS", "Geometry valid", stage="validating_geometry")
            self.stage_status["validating_geometry"] = "done"
        else:
            self.stage_status["validating_geometry"] = "error"
            self.log("ERROR", validation.message, stage="validating_geometry", reason=validation.message)
            result.error_message = validation.message
            self._write_log_file()
            result.logs = self.logs
            result.stage_status = self.stage_status
            result.processing_time_sec = time.time() - t0
            return result

        # --- Stage 6: exporting_step (+GLB) ---
        self.stage_status["exporting_step"] = "active"
        self.log("INFO", "Exporting STEP and GLB", stage="exporting_step")
        export_result = exporter.export_all(solid_result.solid, self.dirs["output"], base_name)
        result.export_result = export_result
        if export_result.success:
            self.log("SUCCESS", "STEP generated and verified", stage="exporting_step", details=export_result.message)
            self.stage_status["exporting_step"] = "done"
        else:
            self.stage_status["exporting_step"] = "error"
            self.log("ERROR", export_result.message, stage="exporting_step", reason=export_result.message)
            result.error_message = export_result.message
            self._write_log_file()
            result.logs = self.logs
            result.stage_status = self.stage_status
            result.processing_time_sec = time.time() - t0
            return result

        # --- Stage 7: preparing_viewer ---
        self.stage_status["preparing_viewer"] = "active"
        self.log("INFO", "Preparing 3D viewer (GLB verified)", stage="preparing_viewer")
        if export_result.glb_path and os.path.exists(export_result.glb_path):
            self.log("SUCCESS", f"Viewer ready: {export_result.mesh_vertex_count} vertices, "
                                 f"{export_result.mesh_face_count} faces", stage="preparing_viewer")
            self.stage_status["preparing_viewer"] = "done"
            result.success = True
        else:
            self.stage_status["preparing_viewer"] = "error"
            self.log("ERROR", "GLB not available for viewer.", stage="preparing_viewer", reason="GLB not available for viewer.")
            result.error_message = "GLB not available for viewer."

        result.processing_time_sec = time.time() - t0
        result.logs = self.logs
        result.stage_status = self.stage_status
        self._write_log_file()
        return result
