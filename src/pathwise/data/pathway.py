"""Workbook transforms for the outer emission-pathway search.

The outer (upper) level of the bilevel solve searches a single sector-wide
per-year intensity cap. These pure helpers connect that searched vector to the
workbook the inner solve consumes: derive the starting upper bound from the
selected target set, enumerate the sector's groups, and rewrite the ``targets``
sheet so the searched cap is broadcast to every group.

All functions are pure ``dict``-in / ``dict``-out transforms — no I/O, and the
input workbook is never mutated.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from pathwise.core.entities import TargetType
from pathwise.data.trajectory import interpolate
from pathwise.data.workbook import Workbook

_INTENSITY = TargetType.INTENSITY_CAP.value


def _str(value: Any) -> str | None:
    """Trim to ``str``; ``None``/NaN → ``None`` (mirrors ``assemble``)."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value).strip()


def _is_intensity(row: dict[str, Any]) -> bool:
    """``True`` if a target row is an intensity cap (the default when absent)."""
    return (_str(row.get("target_type")) or _INTENSITY) == _INTENSITY


def _matches_set(row: dict[str, Any], target_set: str | None) -> bool:
    """``True`` if the row belongs to ``target_set`` (``None`` ⇒ any set)."""
    return target_set is None or _str(row.get("target_set")) == target_set


def sector_groups(workbook: Workbook) -> list[str]:
    """Return the sorted distinct asset groups (the sector's companies).

    Args:
        workbook: The in-memory generic workbook.

    Returns:
        Sorted unique ``group`` values from the ``assets`` sheet.
    """
    groups = {g for r in workbook.get("assets", []) if (g := _str(r.get("group"))) is not None}
    return sorted(groups)


def derive_upper_bounds(
    workbook: Workbook, target_set: str | None, years: Sequence[int]
) -> dict[int, float]:
    """Return the loosest per-year intensity cap, densified over ``years``.

    For each year the upper bound is the maximum (loosest) intensity-cap limit
    across groups in ``target_set``; the sparse result is interpolated onto every
    modelled year (held flat outside the known range).

    Args:
        workbook: The in-memory generic workbook.
        target_set: Selected target set (``None`` ⇒ all intensity-cap rows).
        years: Modelled horizon years.

    Returns:
        Dense ``{year: limit}`` [gCO2e/MJ] over ``years``.

    Raises:
        ValueError: If no matching intensity-cap target rows exist.
    """
    per_year: dict[int, float] = {}
    for r in workbook.get("targets", []):
        if not _is_intensity(r) or not _matches_set(r, target_set):
            continue
        limit = r.get("limit")
        if limit is None or (isinstance(limit, float) and math.isnan(limit)):
            continue
        y = int(r["year"])
        per_year[y] = max(per_year.get(y, float(limit)), float(limit))
    if not per_year:
        raise ValueError(
            f"no intensity-cap targets found for target_set={target_set!r}; "
            "the outer pathway search needs a starting upper bound"
        )
    return interpolate(per_year, years)


def clamp_pathway(
    x: Sequence[float], floor: Sequence[float], upper: Sequence[float]
) -> list[float]:
    """Clamp each coordinate of ``x`` into ``[floor, upper]``."""
    return [min(max(xi, lo), hi) for xi, lo, hi in zip(x, floor, upper, strict=True)]


def apply_pathway(
    workbook: Workbook,
    target_set: str | None,
    groups: Sequence[str],
    pathway: dict[int, float],
) -> Workbook:
    """Return a copy of ``workbook`` with the searched cap broadcast to all groups.

    The ``intensity_cap`` rows of ``target_set`` are dropped and replaced by one
    row per (group, year) carrying the searched limit. ``absolute_cap`` rows and
    every other target set are preserved. The input workbook is not mutated.

    Args:
        workbook: The in-memory generic workbook.
        target_set: Target set to overwrite (echoed into the new rows).
        groups: Sector groups to broadcast the pathway onto.
        pathway: The searched ``{year: limit}`` [gCO2e/MJ] sector cap.

    Returns:
        A new workbook with the rewritten ``targets`` sheet.
    """
    kept = [
        row
        for row in workbook.get("targets", [])
        if not (_is_intensity(row) and _matches_set(row, target_set))
    ]
    new_rows = [
        {
            "target_set": target_set,
            "group": group,
            "target_type": _INTENSITY,
            "year": int(year),
            "limit": float(limit),
        }
        for group in groups
        for year, limit in sorted(pathway.items())
    ]
    out: Workbook = dict(workbook)
    out["targets"] = kept + new_rows
    return out
