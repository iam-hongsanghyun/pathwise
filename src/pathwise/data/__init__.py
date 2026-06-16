"""Data layer — workbook I/O, schema, assembly, validation, scenario."""

from __future__ import annotations

from pathwise.data.assemble import assemble_problem
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.validation import ValidationReport, validate
from pathwise.data.workbook import Workbook, frames_to_workbook, workbook_to_frames

__all__ = [
    "ScenarioConfig",
    "ValidationReport",
    "Workbook",
    "assemble_problem",
    "frames_to_workbook",
    "validate",
    "workbook_to_frames",
]
