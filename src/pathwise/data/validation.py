"""Generic validation report and referential-integrity helpers.

Sector packs validate their workbooks before building a problem. This module
provides the shared, domain-agnostic machinery: a collect-don't-crash report
(mirroring the spirit of the legacy shipping validator) and small helpers for
the most common checks (required sheets/columns, foreign keys, shares summing
to one). Per-table dtype/range schemas live in each sector pack.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(slots=True)
class ValidationReport:
    """Accumulates validation findings without raising.

    Attributes:
        errors: Blocking problems (the run should not proceed).
        warnings: Non-blocking issues (e.g. imputed values).
    """

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """``True`` if no blocking errors were recorded."""
        return not self.errors

    def error(self, message: str) -> None:
        """Record a blocking error."""
        self.errors.append(message)

    def warn(self, message: str) -> None:
        """Record a non-blocking warning."""
        self.warnings.append(message)

    def merge(self, other: ValidationReport) -> None:
        """Absorb another report's findings."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def as_dict(self) -> dict[str, list[str]]:
        """Return a JSON-serialisable view (for the API)."""
        return {"errors": list(self.errors), "warnings": list(self.warnings)}


def require_sheets(
    frames: dict[str, pd.DataFrame], required: list[str], report: ValidationReport
) -> None:
    """Record an error for each required sheet that is absent."""
    for sheet in required:
        if sheet not in frames:
            report.error(f"missing required sheet '{sheet}'")


def require_columns(
    df: pd.DataFrame, sheet: str, columns: list[str], report: ValidationReport
) -> None:
    """Record an error for each required column missing from ``df``."""
    for col in columns:
        if col not in df.columns:
            report.error(f"sheet '{sheet}' missing required column '{col}'")


def check_foreign_key(
    df: pd.DataFrame,
    column: str,
    valid_ids: set[str],
    sheet: str,
    report: ValidationReport,
) -> None:
    """Record an error for each value in ``df[column]`` not in ``valid_ids``."""
    if column not in df.columns:
        return
    unknown = {str(v) for v in df[column].dropna().unique()} - valid_ids
    for value in sorted(unknown):
        report.error(f"sheet '{sheet}' column '{column}' references unknown id '{value}'")


def check_shares_sum_to_one(
    df: pd.DataFrame,
    group_column: str,
    share_column: str,
    sheet: str,
    report: ValidationReport,
    tol: float = 1e-6,
) -> None:
    """Record an error where per-group shares do not sum to 1 (within ``tol``)."""
    if group_column not in df.columns or share_column not in df.columns:
        return
    sums = df.groupby(group_column)[share_column].sum()
    for key, total in sums.items():
        if abs(float(total) - 1.0) > tol:
            report.error(f"sheet '{sheet}': shares for '{key}' sum to {total:.4f}, expected 1.0")
