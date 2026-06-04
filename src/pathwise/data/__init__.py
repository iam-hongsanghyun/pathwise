"""pathwise.data — workbook/scenario loading, interpolation, validation.

Public API:
    Workbook IO: read_workbook, write_workbook, Workbook, frames_to_workbook,
        workbook_to_frames.
    Trajectories: interpolate.
    Scenario: ScenarioConfig (+ nested models).
    Validation: ValidationReport and check helpers.
    Imputation: impute_by_group_ratio.
"""

from __future__ import annotations

from pathwise.data.estimation import impute_by_group_ratio
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.trajectory import interpolate
from pathwise.data.validation import (
    ValidationReport,
    check_foreign_key,
    check_shares_sum_to_one,
    require_columns,
    require_sheets,
)
from pathwise.data.workbook import (
    Workbook,
    frames_to_workbook,
    read_workbook,
    workbook_to_frames,
    write_workbook,
)

__all__ = [
    "ScenarioConfig",
    "ValidationReport",
    "Workbook",
    "check_foreign_key",
    "check_shares_sum_to_one",
    "frames_to_workbook",
    "impute_by_group_ratio",
    "interpolate",
    "read_workbook",
    "require_columns",
    "require_sheets",
    "workbook_to_frames",
    "write_workbook",
]
