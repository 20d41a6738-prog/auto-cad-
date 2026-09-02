"""
privacy.py
Accurate, implementation-derived privacy / data-processing notice, plus a
real "delete job data" action. Makes no claims beyond what the code
actually does.
"""
from __future__ import annotations
import os
import shutil

from .pipeline import JOBS_ROOT

PRIVACY_NOTICE_MD = """
**Where files are stored**
Uploaded DXF files and all files this job produces (intermediate STL,
STEP, GLB, log file, PDF report) are written to local disk under
`jobs/<JOB-ID>/` inside this application's own project folder
(`input/`, `intermediate/`, `output/`, `logs/`). Each job gets its own
isolated folder — jobs never read or write another job's files.

**Is processing local?**
Yes. DXF parsing, geometry analysis, solid modelling (CadQuery/OCCT),
validation, and STEP/GLB export all run inside this local Python process.

**Are any external/network services contacted?**
No. This application does not upload your drawing or job files to any
third-party API, cloud storage, or analytics service. The only network
calls made anywhere in the app are by the in-browser 3D viewer, which
loads the Three.js JavaScript library itself from a public CDN
(unpkg.com) so the page can render — your model geometry is embedded
directly in the page and is not sent anywhere; only the generic
Three.js library code is fetched.

**How long do files remain?**
Job folders are **not** automatically deleted. They persist on local
disk until you remove them yourself (see below) or until the
application's `jobs/` folder is cleared manually, e.g. by an
administrator.

**Can you delete job data?**
Yes. Use **Delete Job Data** (Step 6 or the sidebar) to permanently
remove a job's entire folder — input, intermediate files, output
(STEP/GLB), logs, and the PDF report — from local disk. This action
cannot be undone.
"""


def delete_job_data(job_id: str) -> tuple[bool, str]:
    """Permanently delete a job's folder from local disk. Returns (ok, message)."""
    if not job_id:
        return False, "No job ID supplied."
    job_dir = os.path.join(JOBS_ROOT, job_id)
    real_root = os.path.realpath(JOBS_ROOT)
    real_job = os.path.realpath(job_dir)
    if not real_job.startswith(real_root + os.sep):
        return False, "Refused to delete a path outside the jobs directory."
    if not os.path.isdir(job_dir):
        return False, f"Job folder for {job_id} does not exist (already deleted?)."
    try:
        shutil.rmtree(job_dir)
        return True, f"Job {job_id} data permanently deleted from local disk."
    except Exception as e:
        return False, f"Failed to delete job data: {e}"
