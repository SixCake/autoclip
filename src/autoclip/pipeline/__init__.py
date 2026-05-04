"""Pipeline orchestration: state machine + stage handlers + runner.

Public API:
- Stage / StageStatus enums (state machine vocabulary)
- JobStateFile (atomic state.json read/write + cancel signal)
"""

from .state import JobStateFile, Stage, StageStatus

__all__ = ["JobStateFile", "Stage", "StageStatus"]
