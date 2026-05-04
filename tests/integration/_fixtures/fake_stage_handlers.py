"""Fake stage handlers — top-level functions importable from spawn subprocesses.

Each handler writes a marker file in job_dir so the test can verify it ran.
"""

from pathlib import Path

from autoclip.pipeline.runner import register_stage_handler
from autoclip.pipeline.state import JobStateFile, Stage, StageStatus


def _make_handler(stage: Stage):
    def handler(job_dir: Path) -> None:
        # Write a marker file so test can assert which handlers ran
        (job_dir / f"{stage.value}.marker").write_text(stage.value, encoding="utf-8")
        # Mark DONE explicitly (also covers case where entrypoint fallback isn't needed)
        JobStateFile(job_dir).mark_stage(stage, StageStatus.DONE, progress=1.0)
    handler.__name__ = f"fake_{stage.value}_handler"
    return handler


# Register all 5 fake handlers at module-import time
# (so when subprocess imports this module, registration happens automatically)
for _stage in Stage.ordered():
    register_stage_handler(_stage, _make_handler(_stage))
